import csv, json, os, sys
from pathlib import Path

DEFAULT_WORKDIR = Path(__file__).resolve().parent / "runs"


def part_status(workdir, part):
    workdir = Path(workdir)
    d = workdir / f"recon2_{part}"
    if (d / "best.json").exists():
        return "done"
    if d.exists():
        return "failed"
    return "not_run"


def parts_to_run(workdir, parts):
    return [p for p in parts if part_status(workdir, p) != "done"]


def tally(rows):
    out = {"better": 0, "worse": 0, "same": 0, "failed": 0, "not_run": 0}
    for r in rows:
        st = r.get("status")
        if st == "not_run":
            out["not_run"] += 1
        elif st == "failed":
            out["failed"] += 1
            if r.get("live", 0) > 0:
                out["worse"] += 1
        else:  # done
            live, loop = r.get("live", 0), r.get("loop", 0)
            if loop > live:
                out["better"] += 1
            elif loop < live:
                out["worse"] += 1
            else:
                out["same"] += 1
    return out


def main():
    S = Path(os.environ.get("RECON_WORKDIR", str(DEFAULT_WORKDIR)))
    base = {r["model"]: (int(r["curved"]), int(r["patches"]), r["backend"])
            for r in csv.DictReader(open(str(Path(__file__).resolve().parents[2] / "mechparts-baseline.tsv")), delimiter="\t")}
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from patch_representation import represent
    # uploads: runs/uploads/<name>.stl scored against <name>.served.step (what production served)
    for stl in sorted((S / "uploads").glob("*.stl")):
        served = stl.with_suffix(".served.step")
        if served.exists():
            r = represent(stl, served); base[stl.stem] = (r["curved"], r["patches"], "live")
    tb = tl = tp = 0; rows = []; tallies = []
    for part in sorted(base, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x)):
        b = base[part]; bj = S / f"recon2_{part}" / "best.json"
        status = part_status(S, part)
        if bj.exists():
            d = json.load(open(bj)); f = d["represent"]; rep = d["report"]
            lc, lp = f["curved"], f["patches"]
            note = f"valid={rep['valid']} faces={rep['faces']} cyl/cone/tor={rep['cylinders']}/{rep['cones']}/{rep['tori']} bspl={rep['bsplines']} p95={max(rep['p95_mesh_to_solid'], rep['p95_solid_to_mesh'])}"
        else:
            lc, lp, note = 0, b[1], "NO RESULT (counted as 0 - a failure is a failure)"
        tb += b[0]; tl += lc; tp += b[1]
        d_ = lc - b[0]
        tallies.append({"part": part, "live": b[0], "loop": lc, "status": status})
        rows.append(f"{part:>9}  live {b[0]:>3}/{b[1]:<3}  loop {lc:>3}/{lp:<3}  {('+' if d_>0 else '')+str(d_) if d_ else '=':>5}  {status:<7}  {note}")
    print("\n".join(rows))
    print(f"\nTOTAL  live {tb}/{tp} = {100*tb/tp:.1f}%   loop {tl}/{tp} = {100*tl/tp:.1f}%")
    print(tally(tallies))


if __name__ == "__main__":
    main()
