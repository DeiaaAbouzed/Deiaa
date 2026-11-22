"""v2.1.1: quick-access toolbar buttons for the newest tools."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QToolBar


def test_quick_access_toolbar():
    app = QApplication.instance() or QApplication([])
    from medstatix.core.settings import SETTINGS
    from medstatix.ui.main_window import MainWindow
    xp = SETTINGS.expert_mode
    w = MainWindow()
    try:
        tbs = [t for t in w.findChildren(QToolBar) if t.objectName() or True]
        acts = [a for t in tbs for a in t.actions()]
        for a in (w.a_recs, w.a_q_paper, w.a_q_images, w.a_q_comment, w.a_settings):
            assert a in acts
        main = [t for t in tbs if w.a_recs in t.actions()][0]
        order = main.actions()
        assert order.index(w.a_q_paper) == order.index(w.a_recs) + 2          # right after the separator
        menu = w._new_menu_btn.menu().actions()
        for a in (w.a_q_paper, w.a_q_images, w.a_q_comment, w.a_q_batch, w.a_q_cong, w.a_q_expert):
            assert a in menu
        w.a_q_images.trigger()
        assert w.tabs.currentWidget() is w.figstudio
        assert w.a_q_expert.isCheckable() and w.a_q_expert.isChecked() == bool(xp)
    finally:
        SETTINGS.expert_mode = xp
        w.close(); w.deleteLater(); app.processEvents()
