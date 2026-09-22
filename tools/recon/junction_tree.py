"""Decision tree: junction/blend signature -> the exact tool that reproduces it (docs/JUNCTIONS.md).

`TREE` maps a signature (the `sig` field of a junction or blend record, from junctions.py or
mesh_junctions.py) to the `recon_tools` function that builds it and, in `how`, which record fields
give that tool's parameters. `advise(extracted)` turns one `extract()` result into the one-line
recommendations the recon brief carries. Nothing here redefines the fields: see docs/JUNCTIONS.md.
"""

# Each value: tool = "rt.<name>" (must exist in recon_tools), how = one line, param = the tool
# keyword the record's `radius` fills when it is exactly that parameter (advise uses it).
TREE: dict[str, dict] = {
    # sharp edges between planes: no blend face, round the edge only if the mesh shows one
    "plane|plane|line|convex": {
        "tool": "rt.edge_round",
        "how": "no radius: a sharp convex edge needs no tool; pass the edge selector and the round radius only if the mesh rounds it",
    },
    "plane|plane|line|concave": {
        "tool": "rt.edge_round",
        "how": "no radius: a sharp inside corner; edge selector over the concave edge, radius only if the mesh shows a fillet",
    },
    # rounded edges: a cylinder tangent to two planes IS the round
    "blend:cylinder|plane+plane|round": {
        "tool": "rt.edge_round",
        "how": "blend `radius` is the round radius; round the two-plane edge with that radius",
        "param": "radius",
    },
    "blend:cylinder|plane+plane|fillet": {
        "tool": "rt.edge_round",
        "how": "blend `radius` is the fillet radius; fillet the inside two-plane edge with that radius",
        "param": "radius",
    },
    # torus blends on a boss: the minor radius is the fillet/round amount
    "blend:torus|cylinder+plane|fillet": {
        "tool": "rt.boss",
        "how": "torus minor radius = base_fillet; build the boss of the `cylinder` face radius with that base_fillet",
        "param": "base_fillet",
    },
    "blend:torus|cylinder+plane|round": {
        "tool": "rt.boss",
        "how": "torus minor radius = top_round; build the boss with that top_round",
        "param": "top_round",
    },
    "blend:torus|plane+plane|round": {
        "tool": "rt.edge_round",
        "how": "torus minor radius = the round radius; round the two-plane edge",
        "param": "radius",
    },
    "blend:torus|plane+plane|fillet": {
        "tool": "rt.ring_fillet",
        "how": "torus minor radius = fillet; blend the cylinder of that radius into the plane",
        "param": "fillet",
    },
    # hole mouths and their chamfers
    "cylinder|plane|circle|convex": {
        "tool": "rt.hole",
        "how": "circle radius = hole radius, `coaxial` says the cylinder axis is the hole axis; rt.hole drills it (or rt.boss if the cylinder is material)",
        "param": "radius",
    },
    "cone|plane|circle|convex": {
        "tool": "rt.hole",
        "how": "mouth radius = circle radius; mouth_chamfer = that radius minus the coaxial hole cylinder's radius (a following cylinder|plane|circle|convex junction)",
    },
    "cone|cylinder|circle|convex": {
        "tool": "rt.hole",
        "how": "the cone is the chamfer between mouth and hole wall; radius = the coaxial hole radius, chamfer from the mouth circle",
        "param": "radius",
    },
    # counterbore floor: bore wall meets its annular floor in an inside circle
    "cylinder|plane|circle|concave": {
        "tool": "rt.counterbore",
        "how": "bore wall radius = bore_radius; the plane on the far side of the bore gives bore_depth; depth from the pilot cylinder",
        "param": "bore_radius",
    },
}


def _call(entry, radius):
    """The recommended tool call, with its radius filled when it maps exactly to a parameter."""
    name = entry["tool"]
    param = entry.get("param")
    if param and radius is not None:
        return f"{name}({param}={radius:.3f})"
    if radius is not None:
        return f"{name}(radius={radius:.3f})"
    return f"{name}()"


def advise(extracted):
    """One line per junction/blend with a TREE entry: signature, radius, location, tool call."""
    out = []
    for rec in list(extracted.get("junctions", ())) + list(extracted.get("blends", ())):
        entry = TREE.get(rec.get("sig"))
        if entry is None:
            continue
        radius = rec.get("radius")
        centre = rec.get("centre")
        loc = "at (%.2f, %.2f, %.2f)" % tuple(centre) if centre else "location unknown"
        rtxt = f"{radius:.3f} mm" if radius is not None else "no radius"
        out.append(f"{rec['sig']} radius {rtxt} {loc} -> {_call(entry, radius)}"
                   f"  # {entry['how']}")
    return out
