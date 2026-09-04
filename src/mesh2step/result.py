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

    # TrueForm (smooth) counters — verbatim payloads never carry these keys.
    smooth: bool = False
    smooth_planes: int = 0
    smooth_cylinders: int = 0
    smooth_fillets: int = 0
    smooth_distinct_radii: int = 0
    smooth_rejected: int = 0
    smooth_facet_faces: int = 0
    faces_after_smooth: int = 0
    smooth_skipped_components: int = 0
    smooth_max_dev_mm: float = 0.0
    smooth_max_edge_tol_mm: float = 0.0
    smooth_vol_predicted_mm3: float = 0.0
    smooth_built_planes: int = 0
    smooth_built_cylinders: int = 0
    smooth_built_fillets: int = 0
    smooth_built_components: int = 0
    smooth_reverted_components: int = 0

    @property
    def exit_code(self) -> int:
        if not self.ok:
            return 1
        return 0 if not self.warnings else 2

    @classmethod
    def from_native(cls, d: dict) -> "ParityResult":
        """Build a ParityResult from a native stl2step RESULT payload (camelCase keys)."""
        if not d.get("ok"):
            return cls(ok=False, error=d.get("error") or "")
        return cls(
            ok=True,
            input=d.get("input", ""),
            output=d.get("output", ""),
            error=d.get("error"),
            triangles=d.get("triangles", 0),
            vertices=d.get("vertices", 0),
            components=d.get("components", 0),
            solids=d.get("solids", 0),
            open_shells=d.get("openShells", 0),
            faces_before_unify=d.get("facesBeforeUnify", 0),
            faces_after_unify=d.get("facesAfterUnify", 0),
            mesh_volume_mm3=d.get("meshVolumeMM3", 0.0),
            step_volume_mm3=d.get("stepVolumeMM3", 0.0),
            volume_delta_pct=d.get("volumeDeltaPct", -1.0),
            watertight=d.get("watertight", True),
            seconds=d.get("seconds", 0.0),
            warnings=d.get("warnings", []),
            smooth="facesAfterSmooth" in d,
            smooth_planes=d.get("smoothPlanes", 0),
            smooth_cylinders=d.get("smoothCylinders", 0),
            smooth_fillets=d.get("smoothFillets", 0),
            smooth_distinct_radii=d.get("smoothDistinctRadii", 0),
            smooth_rejected=d.get("smoothRejected", 0),
            smooth_facet_faces=d.get("smoothFacetFaces", 0),
            faces_after_smooth=d.get("facesAfterSmooth", 0),
            smooth_skipped_components=d.get("smoothSkippedComponents", 0),
            smooth_max_dev_mm=d.get("smoothMaxDevMM", 0.0),
            smooth_max_edge_tol_mm=d.get("smoothMaxEdgeTolMM", 0.0),
            smooth_vol_predicted_mm3=d.get("smoothVolPredictedMM3", 0.0),
            smooth_built_planes=d.get("smoothBuiltPlanes", 0),
            smooth_built_cylinders=d.get("smoothBuiltCylinders", 0),
            smooth_built_fillets=d.get("smoothBuiltFillets", 0),
            smooth_built_components=d.get("smoothBuiltComponents", 0),
            smooth_reverted_components=d.get("smoothRevertedComponents", 0),
        )

    def to_dict(self) -> dict:
        if not self.ok:
            return {"ok": False, "error": self.error or ""}
        payload = {
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
        if self.smooth:
            payload.update(
                {
                    "smoothPlanes": self.smooth_planes,
                    "smoothCylinders": self.smooth_cylinders,
                    "smoothFillets": self.smooth_fillets,
                    "smoothDistinctRadii": self.smooth_distinct_radii,
                    "smoothRejected": self.smooth_rejected,
                    "smoothFacetFaces": self.smooth_facet_faces,
                    "facesAfterSmooth": self.faces_after_smooth,
                    "smoothSkippedComponents": self.smooth_skipped_components,
                    "smoothMaxDevMM": self.smooth_max_dev_mm,
                    "smoothMaxEdgeTolMM": self.smooth_max_edge_tol_mm,
                    "smoothVolPredictedMM3": self.smooth_vol_predicted_mm3,
                    "smoothBuiltPlanes": self.smooth_built_planes,
                    "smoothBuiltCylinders": self.smooth_built_cylinders,
                    "smoothBuiltFillets": self.smooth_built_fillets,
                    "smoothBuiltComponents": self.smooth_built_components,
                    "smoothRevertedComponents": self.smooth_reverted_components,
                }
            )
        return payload


def emit_result(result: ParityResult, file=None) -> None:
    file = file or sys.stdout
    print(f"RESULT {json.dumps(result.to_dict())}", file=file)
