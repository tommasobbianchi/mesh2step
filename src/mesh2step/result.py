"""RESULT payload construction and emission for the stl2step parity contract.

The CLI prints ``RESULT {json}`` as its last stdout line. The object carries the
fields the reference engine emits; on failure only ``ok`` and ``error`` are
present, matching stl2step's ``Result::toJson``.
"""
import json
import sys
from dataclasses import dataclass, field


@dataclass
class ParityResult:
    ok: bool = True
    input: str = ""
    output: str = ""
    error: str | None = None
    triangles: int = 0
    vertices: int = 0
    components: int = 0
    solids: int = 0
    open_shells: int = 0
    faces_before_unify: int = 0
    faces_after_unify: int = 0
    mesh_volume_mm3: float = 0.0
    step_volume_mm3: float = 0.0
    volume_delta_pct: float = -1.0
    watertight: bool = True
    seconds: float = 0.0
    warnings: list = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if not self.ok:
            return 1
        return 0 if not self.warnings else 2

    def to_dict(self) -> dict:
        if not self.ok:
            return {"ok": False, "error": self.error or ""}
        return {
            "ok": True,
            "input": self.input,
            "output": self.output,
            "triangles": self.triangles,
            "vertices": self.vertices,
            "components": self.components,
            "solids": self.solids,
            "openShells": self.open_shells,
            "facesBeforeUnify": self.faces_before_unify,
            "facesAfterUnify": self.faces_after_unify,
            "meshVolumeMM3": self.mesh_volume_mm3,
            "stepVolumeMM3": self.step_volume_mm3,
            "volumeDeltaPct": self.volume_delta_pct,
            "watertight": self.watertight,
            "seconds": self.seconds,
            "warnings": self.warnings,
        }


def emit_result(result: ParityResult, file=None) -> None:
    file = file or sys.stdout
    print(f"RESULT {json.dumps(result.to_dict())}", file=file)
