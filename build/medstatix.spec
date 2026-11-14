# PyInstaller spec — build with:  pyinstaller build/medstatix.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
hidden = (collect_submodules("statsmodels") + collect_submodules("scipy.stats") + collect_submodules("scipy.optimize")
          + collect_submodules("scipy.special") + collect_submodules("scipy.ndimage") + collect_submodules("skimage") + collect_submodules("medstatix") + ["pyreadstat", "openpyxl", "docx", "PIL", "onnxruntime"])
datas = [(os.path.join(ROOT, "medstatix", "resources"), "medstatix/resources"),
         (os.path.join(ROOT, "tests", "test_validation.py"), "medstatix/validation")]
datas += collect_data_files("onnxruntime") + collect_data_files("docx") + collect_data_files("statsmodels") + collect_data_files("skimage")

a = Analysis([os.path.join(ROOT, "run_medstatix.py")], pathex=[ROOT], hiddenimports=hidden, datas=datas,
             excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "notebook", "pytest", "sphinx",
                       "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
                       "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
             noarchive=False)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "build", "icon.ico")
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MedStatixPro", console=False,
          icon=icon if os.path.exists(icon) else None, version=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MedStatixPro")
