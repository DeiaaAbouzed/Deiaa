"""MedStatix Pro — entry point."""
import os
import sys


def selftest() -> int:
    """Headless check used by the build pipeline: imaging + statistics stack load and run in the frozen app."""
    import glob
    from .imaging import core as IC
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "sample_images")
    lines, ok = [], True
    for f in sorted(glob.glob(os.path.join(here, "*.png"))):
        img = IC.load_image(f)
        out, _ = IC.apply_pipeline(img, [{"op": "white_balance"}, {"op": "reinhard"}, {"op": "denoise", "params": {"strength": 0.3}}])
        rep = IC.integrity_report(img, out)
        dab = IC.ihc_dab(img)[0]["DAB positive area %"]
        lines.append(f"{os.path.basename(f)}: integrity={rep['passed']} DAB%={dab:.2f}")
        ok &= bool(rep["passed"]) or "IHC" in f
        qc = IC.image_qc(img)
        _, _, rep2, _ = IC.auto_enhance(img, qc["steps"])
        lines.append(f"   QC score={qc['score']} auto-enhance integrity={rep2['passed']}")
        ok &= bool(rep2["passed"])
        _, _, rep3, _, info = IC.publication_ready(img)
        lines.append(f"   publication-ready ({info['stain']}) integrity={rep3['passed']}")
        ok &= bool(rep3["passed"])
    import scipy.stats, statsmodels.api  # noqa: F401
    from .core import animal as AN
    from .report import manuscript, journals  # noqa: F401
    ok &= [v for _, v, _, _ in AN.rout([10.1, 9.8, 10.3, 9.9, 10.0, 10.2, 9.7, 25.0])] == [25.0]
    import docx  # noqa: F401
    from .imaging import nuclei as NU, reader as RD
    if NU.available():
        img = IC.load_image(os.path.join(here, "HE_breast_carcinoma_1.png"))
        r = RD.read_image(img, stain="H&E")
        n = r["summary"]["Nuclei detected"]
        lines.append(f"AI reader: {n} nuclei, {len(r['inflammatory'])} inflammatory suggestions")
        ok &= n > 150
    else:
        lines.append("AI reader: onnxruntime missing"); ok = False
    from .analyses.bayes import jzs_bf_t
    from .analyses.gpower import solve_n, FAMILIES
    bf = jzs_bf_t(-4.0621, 10, 9); n = solve_n(FAMILIES[0], .5, .05, .8, 2, 1, 2)[0]
    lines.append(f"Bayes factor (sleep, paired) = {bf:.4f}; G*Power N (d = 0.5) = {n}")
    ok &= abs(bf - 17.2589) < 0.01 and n == 128
    from .imaging import forensics as FO
    a = IC.load_image(os.path.join(here, "HE_breast_carcinoma_1.png"))
    ok &= FO.clone_check(a) is None and FO.external_edit_check(a, a)["clean"]
    from .core import pzfx, assistant, updater, rbridge, fallback  # noqa: F401
    import pyreadstat  # noqa: F401
    lines.append("forensics, Prism/SPSS I/O, assistant, updater, R bridge: loaded")
    lines.append("OK" if ok else "FAIL")
    print("\n".join(lines))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    import matplotlib
    matplotlib.use("QtAgg")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    app = QApplication(sys.argv)
    app.setApplicationName("MedStatix Pro")
    app.setOrganizationName("MedStatix")
    app.setFont(QFont("Segoe UI", 10))
    from .ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    w.startup_update_check()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        w.open_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
