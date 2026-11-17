"""Research-figure enhancer for everything that is not a histology / IHC slide: photographs of animals, organs and
gross specimens, Western blots and gels, graphs and screenshots, scanned documents and fluorescence images.

Principles (the same as the histology studio):
* only global operations, applied identically to the whole image, every one logged and written into a methods text;
* no generative / AI pixel synthesis: enlarging an image adds pixels, not detail. Upscaling uses Lanczos resampling
  followed by an edge-sharpening step that is then corrected by iterative back-projection, so that the enlarged image,
  shrunk back to the original size, reproduces the original pixels (Irani & Peleg, 1991). Nothing that was not in the
  original can appear;
* Western blots and gels get linear adjustments only (no gamma, no denoising, no sharpening, no background
  subtraction), as required by journal image-integrity policies; band quantification must use the raw file.

Resolution: journals ask for a size in print (column width in mm) at a minimum resolution (300 dpi for photographs,
600 for combinations, 1000–1200 for line art). ``print_plan`` computes how many pixels that needs, how much of it the
original already has (its effective dpi at that width), and whether enlarging is needed."""
from __future__ import annotations

import io
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import color, exposure, restoration, transform

KINDS = {
    "photo": ("Photograph (animals, organs, gross specimens, equipment)", "صورة فوتوغرافية (حيوانات، أعضاء، عينات، أجهزة)"),
    "blot": ("Western blot / gel", "ويسترن بلوت / جل"),
    "chart": ("Graph, diagram or screenshot", "رسم بياني أو مخطط أو لقطة شاشة"),
    "scan": ("Scanned page or printed figure", "صفحة ممسوحة أو شكل مطبوع"),
    "fluorescence": ("Fluorescence / dark-background image", "صورة فلورسنت / خلفية داكنة"),
}

WIDTHS_MM = {"single": 85.0, "1.5": 114.0, "double": 174.0, "full page": 180.0}
WIDTH_UI = {"single": ("Single column (85 mm)", "عمود واحد (85 مم)"), "1.5": ("1.5 columns (114 mm)", "عمود ونصف (114 مم)"),
            "double": ("Double column (174 mm)", "عمودان (174 مم)"), "full page": ("Full page (180 mm)", "صفحة كاملة (180 مم)")}
DPI_FOR = {"photo": 300, "fluorescence": 300, "blot": 600, "scan": 600, "chart": 1000}

# ----------------------------------------------------------------------------- helpers


def to_f(img):
    return np.clip(img[..., :3].astype(np.float64) / 255.0, 0, 1)


def to_u8(f):
    return (np.clip(f, 0, 1) * 255 + 0.5).astype(np.uint8)


def _gray(f):
    return color.rgb2gray(f)


def _is_gray(f, tol=0.02):
    return float(np.abs(f[..., 0] - f[..., 1]).mean() + np.abs(f[..., 1] - f[..., 2]).mean()) < tol


def noise_sigma(f):
    from .core import noise_sigma as ns
    return ns(f)


def sharpness(f):
    """Variance of the Laplacian of the grey image (higher = crisper)."""
    return float(ndi.laplace(_gray(f)).var() * 1e4)


def detect_kind(img) -> str:
    """Guess the image type from its pixels."""
    f = to_f(img)
    g = _gray(f)
    sat = color.rgb2hsv(f)[..., 1]
    dark_bg = np.median(g) < 0.18
    if dark_bg:
        return "fluorescence"
    hist = np.histogram((g * 63).astype(int), bins=64, range=(0, 64))[0] / g.size
    flat = (hist > 0.002).sum()
    paper = (g > 0.97).mean()
    q = (f * 31).astype(int)
    ncol = len(np.unique(q[..., 0] * 1024 + q[..., 1] * 32 + q[..., 2]))
    if paper > 0.4 and (flat < 40 or np.sort(hist)[-3:].sum() > 0.6 or ncol < 400):
        return "chart"
    if _is_gray(f, 0.04) or sat.mean() < 0.06:
        # grey: blots/gels have horizontal band structure; scans have text-like fine strokes
        rows = np.abs(np.diff(g.mean(1))).mean(); cols = np.abs(np.diff(g.mean(0))).mean()
        return "blot" if rows > 1.3 * cols else "scan"
    return "photo"


# ----------------------------------------------------------------------------- operations (all global)


def op_autocrop(f, tol=0.04, pad=4):
    """Remove uniform borders (scanner margins, screenshot frames)."""
    g = _gray(f)
    ref = np.median(np.r_[g[0], g[-1], g[:, 0], g[:, -1]])
    m = np.abs(g - ref) > tol
    if not m.any():
        return f, {"cropped": False}
    ys, xs = np.nonzero(m)
    y0, y1 = max(0, ys.min() - pad), min(g.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(g.shape[1], xs.max() + pad + 1)
    if (y1 - y0) * (x1 - x0) > 0.97 * g.size or (y1 - y0) < 16 or (x1 - x0) < 16:
        return f, {"cropped": False}
    return f[y0:y1, x0:x1], {"cropped": True, "box": [int(y0), int(x0), int(y1), int(x1)]}


def skew_angle(f, max_deg=8.0):
    """Dominant small rotation (deg) of straight lines / text rows, by maximising projection-profile sharpness."""
    g = _gray(f)
    s = min(1.0, 900 / max(g.shape))
    g = transform.rescale(g, s, anti_aliasing=True) if s < 1 else g
    ink = 1 - g if np.median(g) > 0.5 else g
    best, ang = -1, 0.0
    for a in np.arange(-max_deg, max_deg + 0.01, 0.25):
        r = ndi.rotate(ink, a, reshape=False, order=1, mode="nearest")
        v = np.var(r.sum(1))
        if v > best:
            best, ang = v, float(a)
    return ang


def op_straighten(f, angle=None):
    a = skew_angle(f) if angle is None else float(angle)
    if abs(a) < 0.2:
        return f, {"angle_deg": 0.0}
    bg = np.median(np.r_[f[0], f[-1]], 0)
    out = np.stack([ndi.rotate(f[..., c], a, reshape=False, order=3, mode="constant", cval=bg[c]) for c in range(3)], -1)
    return np.clip(out, 0, 1), {"angle_deg": round(a, 2)}


def op_white_balance(f, strength=1.0):
    """White-patch balance on the brightest near-neutral pixels (paper, white fur, bench, highlights), one gain per
    channel. Skipped when the image has no such reference, so naturally coloured scenes are not neutralised."""
    g = _gray(f)
    sat = color.rgb2hsv(f)[..., 1]
    m = (g > np.percentile(g, 95)) & (sat < 0.25) & (g < 0.995)
    if m.mean() < 0.005:
        return f, {"skipped": "no neutral reference"}
    ref = f[m].mean(0)
    gain = ref.mean() / np.maximum(ref, 1e-4)
    gain = np.clip(1 + strength * (gain - 1), 0.85, 1.18)
    return np.clip(f * gain, 0, 1), {"gains_rgb": [round(float(x), 3) for x in gain]}


def op_levels(f, low=0.3, high=99.7, joint=True):
    """Linear stretch between two percentiles (the same mapping for all channels when joint)."""
    if joint:
        lo, hi = np.percentile(f, [low, high])
        lo, hi = float(lo), float(max(hi, lo + 0.05))
        return np.clip((f - lo) / (hi - lo), 0, 1), {"black": round(lo, 3), "white": round(hi, 3)}
    lo = np.percentile(f.reshape(-1, 3), low, axis=0); hi = np.percentile(f.reshape(-1, 3), high, axis=0)
    return np.clip((f - lo) / np.maximum(hi - lo, 0.05), 0, 1), {"black": lo.round(3).tolist(), "white": hi.round(3).tolist()}


def op_brightness_contrast(f, brightness=0.0, contrast=1.0):
    return np.clip((f - 0.5) * contrast + 0.5 + brightness, 0, 1), {"brightness": brightness, "contrast": contrast}


def op_gamma_auto(f, target=0.47, limit=(0.7, 1.5)):
    """Gamma that brings the median lightness toward a mid-tone (photographs only)."""
    m = float(np.median(_gray(f)))
    if m <= 0.02 or m >= 0.98:
        return f, {"gamma": 1.0}
    gam = float(np.clip(math.log(target) / math.log(m), *limit))
    return np.clip(f, 0, 1) ** gam, {"gamma": round(gam, 3)}


def op_clahe(f, strength=0.3):
    lab = color.rgb2lab(f)
    L = lab[..., 0] / 100
    eq = exposure.equalize_adapthist(L, clip_limit=0.01)
    lab[..., 0] = 100 * ((1 - strength) * L + strength * eq)
    return np.clip(color.lab2rgb(lab), 0, 1), {"strength": strength}


def op_saturation(f, factor=1.0):
    hsv = color.rgb2hsv(f); hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0, 1)
    return color.hsv2rgb(hsv), {"factor": factor}


def op_denoise(f, strength=0.5):
    sig = noise_sigma(f)
    if sig < 0.004:
        return f, {"skipped": "noise already low", "noise_sigma": round(sig, 4)}
    h = (0.5 + 0.5 * strength) * sig
    out = restoration.denoise_nl_means(f, h=h, sigma=sig, patch_size=5, patch_distance=6, channel_axis=-1, fast_mode=True)
    return np.clip(out, 0, 1), {"noise_sigma": round(sig, 4), "h": round(h, 4)}


def op_dejpeg(f, strength=0.5):
    """Mild edge-preserving smoothing for JPEG block / ringing artefacts (bilateral filter)."""
    out = restoration.denoise_bilateral(f, sigma_color=0.04 + 0.06 * strength, sigma_spatial=1.0 + strength, channel_axis=-1)
    return np.clip(out, 0, 1), {"strength": strength}


def op_sharpen(f, amount=0.5, radius=1.0):
    blur = np.stack([ndi.gaussian_filter(f[..., c], radius) for c in range(3)], -1)
    return np.clip(f + amount * (f - blur), 0, 1), {"amount": amount, "radius_px": radius}


def op_grayscale(f):
    g = _gray(f)
    return np.repeat(g[..., None], 3, -1), {}


def op_invert(f):
    return 1 - f, {}


def op_paper_white(f, size=0.06):
    """Scans only: divide by a large-scale background estimate so the paper is uniformly white (not for data images)."""
    g = _gray(f)
    k = max(15, int(size * max(g.shape)))
    bg = ndi.grey_closing(g, size=(k, k))
    bg = ndi.gaussian_filter(bg, k / 3)
    out = np.clip(f / np.maximum(bg[..., None], 0.2), 0, 1)
    return out, {"window_px": k}


def op_crisp_lineart(f, low=0.12, high=0.88):
    """Charts / text: push near-white to white and near-black to black (linear levels on the grey range)."""
    return np.clip((f - low) / (high - low), 0, 1), {"black": low, "white": high}


OPS = {
    "autocrop": (op_autocrop, "Uniform borders removed", "إزالة الحواف المتجانسة"),
    "straighten": (op_straighten, "Straightened (rotation)", "تعديل الميل (تدوير)"),
    "white_balance": (op_white_balance, "White balance", "توازن اللون الأبيض"),
    "levels": (op_levels, "Linear levels (contrast stretch)", "مستويات خطية (تمديد التباين)"),
    "brightness_contrast": (op_brightness_contrast, "Brightness / contrast", "الإضاءة / التباين"),
    "gamma": (op_gamma_auto, "Mid-tone gamma", "جاما للدرجات المتوسطة"),
    "clahe": (op_clahe, "Local contrast (CLAHE, blended)", "تباين موضعي (CLAHE)"),
    "saturation": (op_saturation, "Saturation", "التشبع"),
    "denoise": (op_denoise, "Noise reduction (non-local means)", "إزالة التشويش"),
    "dejpeg": (op_dejpeg, "JPEG-artefact smoothing", "تنعيم تشوهات JPEG"),
    "sharpen": (op_sharpen, "Unsharp mask", "زيادة الحدة"),
    "grayscale": (op_grayscale, "Converted to greyscale", "تحويل إلى رمادي"),
    "invert": (op_invert, "Inverted", "عكس الألوان"),
    "paper_white": (op_paper_white, "Paper background evened", "توحيد خلفية الورق"),
    "crisp": (op_crisp_lineart, "Line-art levels", "مستويات الرسوم الخطية"),
}

# operations that change the relation between pixel values in a way blots must not undergo
NOT_FOR_BLOTS = {"gamma", "clahe", "denoise", "dejpeg", "sharpen", "paper_white", "saturation", "white_balance"}


def preset(kind: str, img=None) -> list[dict]:
    """One-click recipe for each image type (conservative)."""
    f = to_f(img) if img is not None else None
    if kind == "photo":
        st = [{"op": "white_balance", "params": {"strength": 0.8}}, {"op": "levels", "params": {"low": 0.2, "high": 99.9}},
              {"op": "gamma", "params": {}}, {"op": "clahe", "params": {"strength": 0.25}}]
        if f is not None and noise_sigma(f) > 0.012:
            st.append({"op": "denoise", "params": {"strength": 0.4}})
        st.append({"op": "sharpen", "params": {"amount": 0.4, "radius": 1.0}})
        return st
    if kind == "blot":
        st = [{"op": "straighten", "params": {}}, {"op": "grayscale", "params": {}}]
        if f is not None and np.median(_gray(f)) < 0.4:
            st.append({"op": "invert", "params": {}})
        return st + [{"op": "levels", "params": {"low": 0.0, "high": 100.0}}]      # min–max: no band is clipped
    if kind == "chart":
        return [{"op": "autocrop", "params": {}}, {"op": "dejpeg", "params": {"strength": 0.4}}, {"op": "crisp", "params": {}}]
    if kind == "scan":
        return [{"op": "autocrop", "params": {}}, {"op": "straighten", "params": {}}, {"op": "paper_white", "params": {}},
                {"op": "levels", "params": {"low": 0.5, "high": 99.5}}, {"op": "sharpen", "params": {"amount": 0.5, "radius": 1.0}}]
    if kind == "fluorescence":
        st = [{"op": "levels", "params": {"low": 0.05, "high": 99.95}}]
        if f is not None and noise_sigma(f) > 0.01:
            st.append({"op": "denoise", "params": {"strength": 0.3}})
        return st
    raise ValueError(kind)


def apply(img, steps, kind=None):
    """Apply steps in order. Returns (uint8 image, recorded steps)."""
    f = to_f(img)
    done = []
    for st in steps:
        if kind == "blot" and st["op"] in NOT_FOR_BLOTS:
            continue
        fn = OPS[st["op"]][0]
        f, det = fn(f, **st.get("params", {}))
        done.append({"op": st["op"], "params": st.get("params", {}), "details": det})
    return to_u8(f), done


# ----------------------------------------------------------------------------- resolution


def print_plan(shape, width_mm: float, dpi: int) -> dict:
    """Pixels needed to print `width_mm` wide at `dpi`, and what the image has now."""
    H, W = shape[:2]
    need_w = int(round(width_mm / 25.4 * dpi))
    need_h = int(round(need_w * H / W))
    eff = W / (width_mm / 25.4)
    factor = need_w / W
    if factor <= 1.0:
        verdict = "ok"
    elif factor <= 2.0:
        verdict = "upscale"
    else:
        verdict = "low"
    return {"width_mm": width_mm, "height_mm": round(width_mm * H / W, 1), "dpi": dpi, "need_px": (need_w, need_h),
            "have_px": (W, H), "effective_dpi": round(eff), "factor": round(factor, 2), "verdict": verdict,
            "native_width_mm_at_dpi": round(W / dpi * 25.4, 1)}


def _resize_f(x, h, w, resample=Image.BICUBIC):
    """Float resize, channel by channel, with PIL (mode 'F') — much faster than scipy on large images."""
    return np.stack([np.asarray(Image.fromarray(x[..., c].astype(np.float32), "F").resize((w, h), resample))
                     for c in range(x.shape[2])], -1).astype(np.float64)


def _down(x, shape):
    return _resize_f(x, shape[0], shape[1], Image.LANCZOS)


def upscale(img, factor: float, method: str = "sharp", iterations: int = 5):
    """Enlarge by `factor`.
    'lanczos' : plain Lanczos-3 resampling;
    'sharp'   : Lanczos, a mild unsharp mask on the enlarged image, then iterative back-projection so that the result,
                reduced to the original size, matches the original (no invented detail; halos are removed);
    'pixel'   : nearest neighbour (pixel art, masks)."""
    if factor <= 1.0:
        return img.copy(), {"factor": 1.0, "method": "none"}
    H, W = img.shape[:2]
    nh, nw = int(round(H * factor)), int(round(W * factor))
    if method == "pixel":
        return np.asarray(Image.fromarray(img).resize((nw, nh), Image.NEAREST)), {"factor": factor, "method": "nearest"}
    up = np.asarray(Image.fromarray(img).resize((nw, nh), Image.LANCZOS)).astype(np.float64) / 255
    if method == "lanczos":
        return to_u8(up), {"factor": round(factor, 3), "method": "Lanczos-3"}
    orig = to_f(img)
    x = op_sharpen(up, amount=0.6, radius=0.6 * factor)[0]
    for _ in range(iterations):
        d = orig - _down(x, orig.shape)
        x = np.clip(x + _resize_f(d, nh, nw), 0, 1)
    resid = float(np.abs(orig - _down(x, orig.shape)).mean())
    return to_u8(x), {"factor": round(factor, 3), "method": "Lanczos-3 + unsharp + iterative back-projection",
                      "consistency_error": round(resid * 255, 2)}


# ----------------------------------------------------------------------------- quality metrics


def quality(img) -> dict:
    f = to_f(img)
    g = _gray(f)
    return {"pixels": f"{img.shape[1]} × {img.shape[0]}", "sharpness": round(sharpness(f), 1),
            "noise": round(noise_sigma(f) * 255, 2), "contrast (SD)": round(float(g.std()) * 100, 1),
            "clipped dark %": round(float((g < 0.01).mean() * 100), 2), "clipped bright %": round(float((g > 0.99).mean() * 100), 2)}


# ----------------------------------------------------------------------------- log, methods and saving


@dataclass
class FigureLog:
    source: str = ""
    kind: str = "photo"
    steps: list = field(default_factory=list)
    resize: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def methods_text(self) -> str:
        if not self.steps and not self.resize:
            return "Images are presented without processing."
        names = [OPS[s["op"]][1].lower() for s in self.steps]
        t = ("Images were adjusted in MedStatix Pro with global operations applied equally to the whole image"
             + (f" ({', '.join(names)})" if names else "") + ". No local editing, cloning or generative/AI-based pixel "
             "synthesis was performed and no features were added, removed or obscured. Original files were retained.")
        if self.kind == "blot":
            t += (" Blot and gel images received only linear adjustments (greyscale conversion, rotation and levels) "
                  "applied to the whole image; quantification was performed on the unprocessed images.")
        if self.resize and self.resize.get("method", "none") != "none":
            m = self.resize["method"]
            t += (f" Images were resampled by a factor of {self.resize['factor']:.2f} ({m})"
                  + ("; iterative back-projection ensured that the enlarged image reproduces the original pixels when "
                     "reduced to the original size, so no detail absent from the original was introduced" if "back-projection" in m else "")
                  + ".")
        if self.output.get("dpi"):
            t += f" Figures were exported at {self.output['dpi']} dpi" + (f" for a printed width of {self.output['width_mm']:.0f} mm" if self.output.get("width_mm") else "") + "."
        return t

    def to_json(self):
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, default=str)


def process(img, kind="auto", steps=None, width_mm=None, dpi=None, upscale_method="sharp", allow_upscale=True,
            max_factor=4.0):
    """Full pipeline for one image: enhancement, then resampling to the print size. Returns (image, FigureLog, plan)."""
    kind = detect_kind(img) if kind == "auto" else kind
    steps = preset(kind, img) if steps is None else steps
    out, done = apply(img, steps, kind)
    log = FigureLog(kind=kind, steps=done)
    plan = None
    if width_mm and dpi:
        plan = print_plan(out.shape, width_mm, dpi)
        f = plan["factor"]
        if f > 1.0 and allow_upscale:
            meth = "pixel" if upscale_method == "pixel" else upscale_method
            out, log.resize = upscale(out, min(f, max_factor), meth)
        elif f < 1.0:
            nw, nh = plan["need_px"]
            out = np.asarray(Image.fromarray(out).resize((nw, nh), Image.LANCZOS))
            log.resize = {"factor": round(f, 3), "method": "Lanczos-3 reduction"}
        # when enlargement was capped (or refused), keep the printed width and write the dpi the pixels really give
        real = out.shape[1] / (width_mm / 25.4)
        log.output = {"dpi": int(dpi if real >= dpi - 1 else math.floor(real)), "width_mm": width_mm,
                      "requested_dpi": dpi}
    return out, log, plan


def save(img, path, dpi=300, mode="RGB", quality_jpeg=95):
    """Save with dpi metadata. mode: RGB, L (greyscale) or CMYK (TIFF/JPEG only; naive conversion, check proofs)."""
    im = Image.fromarray(img)
    if mode == "L":
        im = im.convert("L")
    elif mode == "CMYK":
        im = im.convert("CMYK")
    ext = path.lower().rsplit(".", 1)[-1]
    kw = {"dpi": (dpi, dpi)}
    if ext in ("tif", "tiff"):
        kw["compression"] = "tiff_lzw"
    elif ext in ("jpg", "jpeg"):
        if im.mode not in ("RGB", "L", "CMYK"):
            im = im.convert("RGB")
        kw.update(quality=quality_jpeg, subsampling=0)
    elif ext == "png" and im.mode == "CMYK":
        im = im.convert("RGB")
    elif ext == "pdf":
        im.convert("RGB").save(path, "PDF", resolution=float(dpi)); return
    im.save(path, **kw)


def read_dpi(path) -> float:
    try:
        d = Image.open(path).info.get("dpi")
        return float(d[0]) if d else 0.0
    except Exception:
        return 0.0
