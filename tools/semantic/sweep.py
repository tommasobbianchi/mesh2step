#!/usr/bin/env python3
"""Sweep: denoise every input at N levels, run the UNCHANGED analyser, score against the reference."""
import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/semantic"))
sys.path.insert(0, str(ROOT / "tools/tree"))

import afar  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Sweep denoise levels and score results.")
    parser.add_argument("out_dir", help="Output directory")
    parser.add_argument("meshes", nargs="+", help="Mesh paths, optionally with ::reference_mesh")
    parser.add_argument("--levels", default=None, help="Comma-separated list of levels (fractions of bbox diagonal)")
    return parser.parse_args()


def get_levels(args):
    if args.levels:
        return [float(x) for x in args.levels.split(",")]
    return list(np.geomspace(0.0025, 0.08, 10))


def score_tree(tree_json, ref_mesh):
    """Score a feature tree against a reference mesh (same as tests/test_semantic_compile.py)."""
    import analyse as A
    import tree as T
    tol = max(3e-3 * float(np.linalg.norm(ref_mesh.extents)), 0.05)
    occ = T.occupancy(ref_mesh, ref_mesh.bounds, n=60)
    return A.measure(tree_json, ref_mesh, tol, occ)


def score_in_child(tree_json_path, ref_mesh_path, timeout=300):
    """Fork a child to run scoring (OCCT can hang). Returns the measure dict or {"error": ...}."""
    r_fd, w_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        # Child
        os.close(r_fd)
        os.dup2(w_fd, 1)
        os.close(w_fd)
        try:
            with open(tree_json_path) as f:
                tree_json = json.load(f)
            ref_mesh = trimesh.load(ref_mesh_path, force="mesh")
            result = score_tree(tree_json, ref_mesh)
            sys.stdout.write(json.dumps(result))
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(json.dumps({"error": str(e)}))
            sys.stdout.flush()
        os._exit(0)
    else:
        # Parent
        os.close(w_fd)
        chunks = []
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                os.close(r_fd)
                return {"error": "timeout"}
            ready, _, _ = select.select([r_fd], [], [], min(remaining, 1.0))
            if ready:
                data = os.read(r_fd, 65536)
                if not data:
                    break
                chunks.append(data)
            else:
                p, _ = os.waitpid(pid, os.WNOHANG)
                if p != 0:
                    while True:
                        data = os.read(r_fd, 65536)
                        if not data:
                            break
                        chunks.append(data)
                    break
        os.close(r_fd)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        output = b"".join(chunks).decode()
        if output:
            return json.loads(output)
        return {"error": "no output from child"}


def process_level(out_dir, name, p, mesh_path, ref_path):
    """Process one (mesh, level) pair. Returns the result dict."""
    d = Path(out_dir) / name / f"p{p:.4f}"
    result_json = d / "result.json"
    if result_json.exists():
        return json.loads(result_json.read_text())

    d.mkdir(parents=True, exist_ok=True)

    # Simplify
    mesh = trimesh.load(mesh_path, force="mesh")
    faces_in = len(mesh.faces)
    out, T = afar.simplify(mesh, p)
    out.apply_transform(T)
    faces_simplified = len(out.faces)
    out.export(str(d / "simplified.stl"))

    # Meaning-lost gate
    ref_vol = mesh.volume
    volume_ratio = out.volume / ref_vol if ref_vol > 0 else 0.0
    if abs(volume_ratio - 1) > 0.5:
        result = {
            "p": p,
            "faces_in": faces_in,
            "faces_simplified": faces_simplified,
            "lost": True,
            "volume_ratio": volume_ratio,
            "score": {"error": "meaning lost"},
        }
        result_json.write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        return result

    # Run analyser as subprocess
    t0 = time.time()
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    devnull = open(os.devnull, "w")
    proc = subprocess.Popen(
        ["python3", "tools/tree/analyse.py", str(d / "simplified.stl"), str(d)],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=devnull,
        stderr=devnull,
        start_new_session=True,
    )
    try:
        proc.wait(timeout=900)
        analyse_rc = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), 9)
        proc.wait()
        analyse_rc = -1
    devnull.close()

    seconds = time.time() - t0

    # Score against reference
    tree_json_path = d / "tree.json"
    if tree_json_path.exists():
        score = score_in_child(str(tree_json_path), str(ref_path))
    else:
        score = {"error": "tree.json not found"}

    result = {
        "p": p,
        "faces_in": faces_in,
        "faces_simplified": faces_simplified,
        "volume_ratio": volume_ratio,
        "analyse_rc": analyse_rc,
        "seconds": seconds,
        "score": score,
    }
    result_json.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return result


def main():
    args = parse_args()
    levels = get_levels(args)
    out_dir = args.out_dir

    for mesh_spec in args.meshes:
        if "::" in mesh_spec:
            mesh_path, ref_path = mesh_spec.split("::", 1)
        else:
            mesh_path = ref_path = mesh_spec

        name = Path(mesh_path).stem.replace(" ", "_")

        results = []
        for p in levels:
            r = process_level(out_dir, name, p, mesh_path, ref_path)
            results.append(r)

        # BEST: highest score["score"] among those with score["iou"] >= 0.9
        candidates = [
            r for r in results
            if isinstance(r.get("score"), dict)
            and "iou" in r["score"]
            and r["score"]["iou"] >= 0.9
        ]
        if candidates:
            best = max(candidates, key=lambda r: r["score"].get("score", 0))
            print(f"BEST {name} {json.dumps(best)}", flush=True)

        # Curve
        curve = []
        for r in results:
            s = r.get("score")
            if isinstance(s, dict) and "iou" in s:
                curve.append([r["p"], s.get("iou"), s.get("explained"), s.get("steps")])
            else:
                curve.append([r["p"], None, None, None])
        print(f"CURVE {name} {json.dumps(curve)}", flush=True)


if __name__ == "__main__":
    main()
