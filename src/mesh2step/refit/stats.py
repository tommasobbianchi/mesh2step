"""The smooth-pass counter record — port of `refit::RefitStats` (refs/stl2step/src/refit.hpp).

Counters are accumulated per clean component by the segmentation stage and merged
into the RESULT payload by convert.py only for components that accepted the
analytic build — matching the reference's `refitTotals` accounting in stl2step.cpp.
"""
from dataclasses import dataclass


@dataclass
class RefitStats:
    planes: int = 0
    cylinders: int = 0
    fillets: int = 0
    rejected: int = 0
    facet_islands: int = 0
    facet_triangles: int = 0
    distinct_radii: int = 0
    max_vertex_dev: float = 0.0
    max_edge_tol: float = 0.0
    dvol_predicted: float = 0.0

    def absorb(self, other: "RefitStats") -> None:
        """Reference refitTotals merge (stl2step.cpp): sums, maxima, signed dVol."""
        self.planes += other.planes
        self.cylinders += other.cylinders
        self.fillets += other.fillets
        self.rejected += other.rejected
        self.facet_islands += other.facet_islands
        self.facet_triangles += other.facet_triangles
        self.distinct_radii += other.distinct_radii
        self.max_vertex_dev = max(self.max_vertex_dev, other.max_vertex_dev)
        self.max_edge_tol = max(self.max_edge_tol, other.max_edge_tol)
        self.dvol_predicted += other.dvol_predicted
