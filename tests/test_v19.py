"""v1.9: research-image studio (photographs, blots, graphs, scans, fluorescence): enhancement, resolution and dpi."""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import general as GN  # noqa: E402


def _photo():
    from skimage import data
    return (np.asarray(Image.fromarray(data.coffee()).resize((300, 200))) * 0.7 + 20).astype(np.uint8)


def _blot(angle=2.0):
    b = np.full((200, 500), 0.92)
    for i, x in enumerate(range(40, 480, 70)):
        b[90:110, x:x + 50] -= 0.15 + 0.1 * i
    from scipy import ndimage as ndi
    b = ndi.rotate(b, angle, reshape=False, mode="nearest") + np.random.default_rng(0).normal(0, 0.02, b.shape)
    return GN.to_u8(np.repeat(b[..., None], 3, -1))


def _chart():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import io
    fig, ax = plt.subplots(figsize=(4, 3), dpi=80); ax.bar(["A", "B"], [1, 3])
    buf = io.BytesIO(); fig.savefig(buf, format="jpg", dpi=80, pil_kwargs={"quality": 60}); plt.close(fig)
    return np.asarray(Image.open(buf).convert("RGB"))


def test_detect_kind():
    assert GN.detect_kind(_photo()) == "photo"
    assert GN.detect_kind(_blot()) == "blot"
    assert GN.detect_kind(_chart()) == "chart"
    dark = np.zeros((100, 100, 3), np.uint8); dark[40:60, 40:60, 1] = 200
    assert GN.detect_kind(dark) == "fluorescence"


def test_blot_only_linear_and_not_clipped():
    img = _blot()
    out, done = GN.apply(img, GN.preset("blot", img) + [{"op": "sharpen", "params": {}}, {"op": "gamma", "params": {}}], "blot")
    ops = [s["op"] for s in done]
    assert "sharpen" not in ops and "gamma" not in ops and "grayscale" in ops
    assert abs(done[0]["details"]["angle_deg"] + 2.0) < 0.6 or abs(done[0]["details"]["angle_deg"] - 2.0) < 0.6
    assert (out[..., 0] == 0).mean() < 0.01           # bands are not crushed to black


def test_print_plan():
    p = GN.print_plan((200, 300), 85, 300)
    assert p["need_px"][0] == round(85 / 25.4 * 300) and p["effective_dpi"] == round(300 / (85 / 25.4)) and p["verdict"] == "low"
    assert GN.print_plan((3000, 4000), 85, 300)["verdict"] == "ok"


def test_upscale_is_faithful_to_original():
    img = _photo()
    up, info = GN.upscale(img, 2.0, "sharp")
    assert up.shape[:2] == (400, 600) and info["consistency_error"] < 1.5
    back = np.asarray(Image.fromarray(up).resize((300, 200), Image.LANCZOS)).astype(float)
    assert np.abs(back - img).mean() < 2.0
    lz, _ = GN.upscale(img, 2.0, "lanczos")
    assert GN.sharpness(GN.to_f(up)) > GN.sharpness(GN.to_f(lz))


def test_process_dpi_and_methods(tmp_path):
    out, log, plan = GN.process(_chart(), "auto", width_mm=85, dpi=1000)
    assert plan["factor"] > 4 and log.resize["factor"] == 4.0
    real = out.shape[1] / (85 / 25.4)
    assert log.output["dpi"] <= real + 1 and log.output["requested_dpi"] == 1000
    t = log.methods_text()
    assert "back-projection" in t and "No local editing" in t and f"{log.output['dpi']} dpi" in t
    p = str(tmp_path / "a.tif")
    GN.save(out, p, log.output["dpi"])
    assert round(GN.read_dpi(p)) == log.output["dpi"]
    GN.save(out, str(tmp_path / "a.jpg"), 300, "CMYK")
    assert Image.open(str(tmp_path / "a.jpg")).mode == "CMYK"


def test_photo_enhancement_improves_contrast():
    img = _photo()
    out, log, _ = GN.process(img, "photo")
    assert GN.quality(out)["contrast (SD)"] > GN.quality(img)["contrast (SD)"]
    assert GN.quality(out)["clipped bright %"] < 1.0


def test_figure_studio_offscreen(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from medstatix.ui.figure_studio import FigureStudio
    paths = []
    for n, im in (("p.png", _photo()), ("b.png", _blot())):
        Image.fromarray(im).save(str(tmp_path / n)); paths.append(str(tmp_path / n))
    w = FigureStudio()
    w.add_paths(paths); w._update()
    assert w.preview_out is not None and w.cur_kind == "photo" and "dpi" in w.plan_lbl.text()
    w.list.setCurrentRow(1)
    assert w.cur_kind == "blot"
    out, log, dpi = w.render_full(paths[1])
    assert log.kind == "blot" and dpi >= 1
    w.close(); w.deleteLater(); app.processEvents()
    del w
