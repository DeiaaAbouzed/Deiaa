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
    import scipy.stats, statsmodels.api  # noqa: F401
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
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        w.open_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
