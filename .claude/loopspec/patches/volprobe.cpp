// Volume truth instrument: load a BREP or STEP, report what every measurement says.
#include <BRep_Builder.hxx>
#include <BRepTools.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopExp_Explorer.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <ShapeFix_Solid.hxx>
#include <ShapeFix_Shell.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <BRepLib.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <BRepGProp_Face.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <ShapeFix_Shape.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <STEPControl_Reader.hxx>
#include <Precision.hxx>
#include <cstdio>
#include <cstring>
#include <string>

static double vol(const TopoDS_Shape& s) {
    GProp_GProps p; BRepGProp::VolumeProperties(s, p); return p.Mass();
}
static double area(const TopoDS_Shape& s){GProp_GProps p;BRepGProp::SurfaceProperties(s,p);return p.Mass();}
static int nFaces(const TopoDS_Shape& s) {
    int n = 0; for (TopExp_Explorer e(s, TopAbs_FACE); e.More(); e.Next()) n++; return n;
}
int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string path = argv[1];
    TopoDS_Shape sh;
    if (path.size() > 5 && (path.substr(path.size()-5) == ".step" || path.substr(path.size()-4) == ".stp")) {
        STEPControl_Reader rd;
        if (rd.ReadFile(path.c_str()) != IFSelect_RetDone) { std::printf("READ FAIL\n"); return 1; }
        rd.TransferRoots();
        sh = rd.OneShape();
    } else {
        BRep_Builder b;
        if (!BRepTools::Read(sh, path.c_str(), b)) { std::printf("READ FAIL\n"); return 1; }
    }
    std::printf("%-28s type=%d faces=%d\n", path.c_str(), (int)sh.ShapeType(), nFaces(sh));
    std::printf("  raw Gauss volume        %15.4f\n", vol(sh));
    std::printf("  surface area            %15.4f\n", area(sh));
    {int nrev=0,nfwd=0;for(TopExp_Explorer e(sh,TopAbs_FACE);e.More();e.Next()){if(e.Current().Orientation()==TopAbs_REVERSED)nrev++;else nfwd++;}std::printf("  faces FORWARD/REVERSED  %d / %d\n",nfwd,nrev);}
    std::printf("  BRepCheck valid         %d\n", (int)BRepCheck_Analyzer(sh, Standard_True).IsValid());
    // as a solid, as the shipping path builds it
    if (sh.ShapeType() == TopAbs_SHELL) {
        BRep_Builder b; TopoDS_Solid so; b.MakeSolid(so); b.Add(so, TopoDS::Shell(sh));
        BRepClass3d_SolidClassifier cl(so); cl.PerformInfinitePoint(Precision::Confusion());
        std::printf("  infinite point          %s\n", cl.State() == TopAbs_IN ? "IN (inside-out)" : "OUT");
        std::printf("  as-solid volume         %15.4f\n", vol(so));
    }
    // sew, then fix into a solid -- the orientation-independent reading
    try {
        BRepBuilderAPI_Sewing sew(1e-6, Standard_True, Standard_True, Standard_True, Standard_False);
        sew.Load(sh); sew.Perform();
        TopoDS_Shape sewn = sew.SewedShape();
        std::printf("  sewn faces              %d   vol %15.4f\n", nFaces(sewn), vol(sewn));
        if (sewn.ShapeType() == TopAbs_SHELL) {
            BRep_Builder b; TopoDS_Solid so; b.MakeSolid(so); b.Add(so, TopoDS::Shell(sewn));
            ShapeFix_Solid sfs(so); sfs.Perform();
            std::printf("  ShapeFix_Solid volume   %15.4f\n", vol(sfs.Solid()));
        }
    } catch (const Standard_Failure& e) { std::printf("  sew threw: %s\n", e.GetMessageString()); }
    // what the shipping path does next: unify coplanar faces, then write
    try {
        ShapeUpgrade_UnifySameDomain usd(sh, Standard_True, Standard_True, Standard_False);
        usd.Build();
        const TopoDS_Shape u = usd.Shape();
        std::printf("  UNIFIED faces           %d   vol %15.4f\n", nFaces(u), vol(u));
    } catch (const Standard_Failure& e) { std::printf("  unify threw: %s\n", e.GetMessageString()); }
    // the engine unifies the SOLID, not a bare shell -- does that differ?
    if (sh.ShapeType() == TopAbs_SHELL) {
        try {
            BRep_Builder b; TopoDS_Solid so; b.MakeSolid(so); b.Add(so, TopoDS::Shell(sh));
            ShapeUpgrade_UnifySameDomain u2(so, Standard_True, Standard_True, Standard_False);
            u2.Build();
            std::printf("  UNIFIED as SOLID        %d   vol %15.4f\n", nFaces(u2.Shape()), vol(u2.Shape()));
        } catch (const Standard_Failure& e) { std::printf("  solid-unify threw: %s\n", e.GetMessageString()); }
    }
    // orientation repairs, measured against the STEP round-trip truth
    try {
        TopoDS_Shape t = sh;
        if (t.ShapeType() == TopAbs_SHELL) {
            BRep_Builder b; TopoDS_Solid so; b.MakeSolid(so); b.Add(so, TopoDS::Shell(t)); t = so;
        }
        TopoDS_Shape a = t;
        BRepLib::OrientClosedSolid(TopoDS::Solid(a));
        std::printf("  OrientClosedSolid       %15.4f\n", vol(a));
        TopoDS_Shape c = t;
        ShapeFix_Shape sfx(c); sfx.Perform();
        std::printf("  ShapeFix_Shape          %15.4f\n", vol(sfx.Shape()));
        ShapeFix_Solid sfo; sfo.CreateOpenSolidMode() = Standard_False;
        TopoDS_Shape d2 = sfo.SolidFromShell(TopoDS::Shell(sh.ShapeType()==TopAbs_SHELL?TopoDS::Shell(sh):TopoDS::Shell(sh)));
        std::printf("  SolidFromShell          %15.4f\n", vol(d2));
    } catch (const Standard_Failure& e) { std::printf("  orient probes threw: %s\n", e.GetMessageString()); }
    // n17 candidate repair: a face whose stored orientation disagrees with its
    // surface normal integrates with the wrong sign. Decide per face by taking a
    // point on it, stepping along the ORIENTED normal, and classifying: if that
    // point is inside the solid, the face points inward -- reverse it.
    if (sh.ShapeType() == TopAbs_SHELL || sh.ShapeType() == TopAbs_SOLID) {
        try {
            TopoDS_Shape base = sh;
            BRep_Builder bb;
            TopoDS_Solid so;
            if (base.ShapeType() == TopAbs_SHELL) { bb.MakeSolid(so); bb.Add(so, TopoDS::Shell(base)); }
            else so = TopoDS::Solid(base);
            BRepClass3d_SolidClassifier cls(so);
            TopoDS_Shell ns; bb.MakeShell(ns);
            int flipped = 0, tested = 0;
            double step = 1e-4;
            for (TopExp_Explorer e(so, TopAbs_FACE); e.More(); e.Next()) {
                TopoDS_Face f = TopoDS::Face(e.Current());
                BRepGProp_Face gf(f);
                Standard_Real u1,u2,v1,v2; gf.Bounds(u1,u2,v1,v2);
                gp_Pnt pt; gp_Vec nv;
                gf.Normal(0.5*(u1+u2), 0.5*(v1+v2), pt, nv);
                if (nv.Magnitude() < 1e-12) { bb.Add(ns, f); continue; }
                nv.Normalize();
                tested++;
                cls.Perform(pt.Translated(nv * step), 1e-7);
                if (cls.State() == TopAbs_IN) { f.Reverse(); flipped++; }
                bb.Add(ns, f);
            }
            BRep_Builder b2; TopoDS_Solid so2; b2.MakeSolid(so2); b2.Add(so2, ns);
            std::printf("  N17 per-face orient     tested=%d flipped=%d  vol %15.4f\n",
                        tested, flipped, vol(so2));
        } catch (const Standard_Failure& e) { std::printf("  n17 threw: %s\n", e.GetMessageString()); }
    }
    return 0;
}
