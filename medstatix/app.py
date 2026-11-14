"""MedStatix Pro — entry point."""
import os
import sys


def main():
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
