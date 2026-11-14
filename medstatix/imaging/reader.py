"""Image reader: AI-assisted description of a histology / IHC image.

1. Nuclei are detected by a deep-learning model (StarDist, see nuclei.py).
2. Each nucleus is typed by a small neural network (inflammatory / epithelial / spindle / other, see cellclass.py).
3. Inflammatory cells lying close together are grouped into candidate infiltrate foci.
4. Colour-based detectors add candidate congestion (RBC-rich) areas and vacuoles / fat droplets; in IHC each nucleus is
   graded by its own DAB optical density.

Everything is computed on the native-colour image (never on cosmetic edits), and every finding is a *suggestion* with a
confidence that the user reviews (accept / delete) before it is counted or drawn on a figure."""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi

from . import cellclass as CC
from . import core as IC
from . import nuclei as NU

LABELS = {  # key: (English label for the figure, Arabic)
    "inflammatory": ("Inflammatory cells", "خلايا التهابية"),
    "focus": ("Inflammatory infiltrate", "ارتشاح التهابي"),
    "congestion": ("Congestion", "احتقان"),
    "vacuole": ("Vacuolation", "تفجّي (فجوات)"),
    "dab_pos": ("Positive (DAB) cells", "خلايا موجبة (DAB)"),
}
COLOURS = {"inflammatory": "#00E5FF", "focus": "#FFD600", "congestion": "#FF4081", "vacuole": "#76FF03",
           "dab_pos": "#FF6D00", "epithelial": "#B388FF", "spindle": "#69F0AE"}
METHOD_TEXT = ("Nuclei were detected with the pretrained StarDist 2D 'versatile H&E' deep-learning model (Schmidt et al., "
               "2018) and classified as inflammatory, epithelial, spindle-shaped or other by a neural-network classifier "
               "trained on the CoNSeP dataset (Graham et al., 2019), run in MedStatix Pro on the native-colour image. "
               "Groups of ≥{min_focus} inflammatory nuclei within {eps_um} µm of each other were proposed as inflammatory "
               "foci. All automated suggestions were reviewed and confirmed or rejected by the investigator before counting.")


def _clusters(pts, eps, min_pts):
    """DBSCAN-like grouping (connected components of points within eps that have ≥ min_pts neighbours)."""
    from scipy.spatial import cKDTree
    if len(pts) < min_pts:
        return []
    t = cKDTree(pts)
    nb = t.query_ball_point(pts, eps)
    core = np.array([len(b) >= min_pts for b in nb])
    lab = -np.ones(len(pts), int); c = 0
    for i in np.where(core)[0]:
        if lab[i] >= 0:
            continue
        stack = [i]; lab[i] = c
        while stack:
            j = stack.pop()
            if not core[j]:
                continue
            for k in nb[j]:
                if lab[k] < 0:
                    lab[k] = c; stack.append(k)
        c += 1
    return [np.where(lab == k)[0] for k in range(c)]


def _hull(pts, pad):
    from scipy.spatial import ConvexHull
    if len(pts) < 3:
        return None
    try:
        h = ConvexHull(pts)
    except Exception:
        return None
    poly = pts[h.vertices]
    c = poly.mean(0)
    v = poly - c
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return c + v * (n + pad) / np.maximum(n, 1e-6)


def _vacuoles(img, nuc_area_px, tissue):
    """Clear, round holes enclosed by tissue (fat droplets / cytoplasmic vacuoles); vessel lumens can also qualify."""
    from skimage import measure, morphology
    g = img[..., :3].astype(np.float32).mean(2) / 255.0
    bright = g > np.percentile(g[tissue], 90) if tissue.any() else g > 0.85
    bright &= g > 0.78
    holes = ndi.binary_fill_holes(~bright) & bright      # bright regions fully enclosed by darker tissue
    holes = morphology.binary_opening(holes, morphology.disk(1))
    lab = measure.label(holes)
    out = []
    lo, hi = 3 * nuc_area_px, 80 * nuc_area_px
    dark = ~bright
    for p in measure.regionprops(lab):
        if not (lo <= p.area <= hi):
            continue
        # the rim around the space must be tissue (not dust or debris floating in an empty lumen / background)
        r = max(2, int(round(math.sqrt(p.area / math.pi) * 0.6)))
        y0, x0, y1, x1 = p.bbox
        ya, xa, yb, xb = max(0, y0 - r), max(0, x0 - r), min(g.shape[0], y1 + r), min(g.shape[1], x1 + r)
        m = lab[ya:yb, xa:xb] == p.label
        rim = ndi.binary_dilation(m, iterations=r) & ~m
        if not rim.any() or tissue[ya:yb, xa:xb][rim].mean() < 0.8 or dark[ya:yb, xa:xb][rim].mean() < 0.6:
            continue
        circ = 4 * math.pi * p.area / max(p.perimeter, 1) ** 2
        if circ < 0.75 or p.solidity < 0.92:
            continue
        conf = float(np.clip(0.5 + 0.5 * (circ - 0.75) / 0.25, 0, 1) * np.clip(p.solidity, 0, 1))
        out.append({"y": p.centroid[0], "x": p.centroid[1], "r": math.sqrt(p.area / math.pi), "conf": conf, "area": p.area})
    return out


def _merge(lab_s, nu, lab2, nu2, s, shape):
    from skimage.transform import resize
    lab_s = lab_s.copy(); nu = list(nu)
    for j, n in enumerate(nu2, 1):
        m = lab2 == j
        if not m.any():
            continue
        if (lab_s[m] > 0).mean() > 0.3:
            continue
        k = len(nu) + 1
        lab_s[m & (lab_s == 0)] = k
        nu.append(n)
    lab = lab_s if s == 1 else resize(lab_s, shape, order=0, preserve_range=True, anti_aliasing=False).astype(np.int32)
    return lab, nu, lab_s


def _hematoxylin_view(img):
    """For detection only: render hematoxylin + DAB optical density as one hematoxylin-like stain, so that brown
    (DAB-positive) nuclei look like ordinary nuclei to the network. Never shown or measured."""
    from skimage.color import hed2rgb
    hed = IC.stain_channels(img)
    h = np.clip(hed[0], 0, None) + 1.6 * np.clip(hed[2], 0, None)
    z = np.zeros_like(h)
    rgb = hed2rgb(np.stack([h, 0.25 * h, z], -1))
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def _dab_thresholds(d):
    """Per-image DAB thresholds relative to the negative nuclei: weak / moderate / strong = negative level + 0.012 /
    0.03 / 0.05 OD (colour-deconvolution units). The negative level is the median of the lowest third of nuclei."""
    d = np.sort(np.asarray(d, float))
    n0 = float(np.median(d[:max(1, len(d) // 3)]))
    return (n0 + 0.012, n0 + 0.03, n0 + 0.05)


def read_image(img, px_um=0.0, stain="auto", min_conf=0.65, min_focus=8, focus_um=12.0, dab="auto", vacuoles=False):
    """Return dict: cells (list), foci, congestion regions, vacuoles, summary (dict of numbers), stain, scale."""
    img = np.ascontiguousarray(img[..., :3])
    H, W = img.shape[:2]
    stain = IC.guess_stain(img) if stain == "auto" else ("IHC" if stain.startswith("IHC") else "H&E")
    lab, nu, s, img_s, lab_s = NU.detect(img, scale="auto", prob_thresh=0.5, keep_scaled=True)
    if stain == "IHC":
        # strongly brown nuclei can be missed by an H&E-trained network: run it a second time on a hematoxylin-like
        # rendering (hematoxylin + DAB density) at the same scale and add the nuclei not already found
        _, nu2, _, _, lab2 = NU.detect(img, scale=s, prob_thresh=0.5, keep_scaled=True, detect_on=_hematoxylin_view(img))
        lab, nu, lab_s = _merge(lab_s, nu, lab2, nu2, s, img.shape[:2])
    cells = []
    dab_used = None
    if nu:
        # features are measured at the working scale (nuclei at the size the networks were trained on)
        nu_s = [{"y": n["y"] * s, "x": n["x"] * s, "prob": n["prob"], "poly": n["poly"] * s} for n in nu]
        X, cen = CC.features(img_s, lab_s, nu_s, 1.0)
        cen = cen / s
        P = CC.predict_proba(X) if CC.available() else np.zeros((len(nu), 4))
        if stain == "IHC":
            d_all = IC.stain_channels(img_s)[2]
            dab_mean = np.nan_to_num(ndi.mean(d_all, lab_s, np.arange(1, len(nu) + 1)))
            dab_used = _dab_thresholds(dab_mean) if dab == "auto" else tuple(dab)
        rg = X[:, CC.FEATURES.index("ring_gray")]
        for i, n in enumerate(nu):
            if rg[i] < 0.2:      # surrounded by black: eyepiece ring / outside the field of view
                continue
            k = int(P[i].argmax())
            c = {"y": float(cen[i, 0]), "x": float(cen[i, 1]), "poly": n["poly"], "det": n["prob"],
                 "type": ["other", "inflammatory", "epithelial", "spindle"][k], "p": float(P[i, k]),
                 "p_infl": float(P[i, 1]), "area_px": float(X[i, 0] / (s * s))}
            if stain == "IHC":
                d = float(dab_mean[i]); c["dab"] = d
                c["grade"] = 3 if d >= dab_used[2] else 2 if d >= dab_used[1] else 1 if d >= dab_used[0] else 0
            cells.append(c)
    n_cells = len(cells)
    med_area = float(np.median([c["area_px"] for c in cells])) if cells else 0.0
    # inflammatory cells (in IHC the classifier is less reliable: show only in H&E)
    infl = [c for c in cells if stain == "H&E" and c["type"] == "inflammatory" and c["p"] >= min_conf]
    # foci: radius in pixels of this image (20 µm; uncalibrated → 80 px at the model's 40× scale)
    eps = (focus_um / px_um) if px_um else 48.0 / s
    foci = []
    if len(infl) >= min_focus:
        pts = np.array([[c["y"], c["x"]] for c in infl])
        strong = np.array([c["p"] >= max(0.7, min_conf) for c in infl])
        for idx in _clusters(pts, eps, min_pts=4):
            if strong[idx].sum() < 0.6 * len(idx):
                continue
            if len(idx) < min_focus:
                continue
            hull = _hull(pts[idx][:, ::-1], pad=eps * 0.35)  # x, y
            conf = float(np.clip(np.mean([infl[i]["p"] for i in idx]) * min(1.0, len(idx) / (2 * min_focus) + 0.5), 0, 1))
            foci.append({"n": len(idx), "hull": hull, "conf": conf, "y": float(pts[idx, 0].mean()), "x": float(pts[idx, 1].mean())})
    # congestion and vacuoles
    tissue = IC._tissue_mask(img, 0.85)
    cong = []
    if stain == "H&E":
        _, rbc = IC.congestion_area(img)
        from skimage import measure, morphology
        rbc = ndi.binary_fill_holes(morphology.closing(rbc, morphology.disk(max(2, int(round(3 / s))))))
        min_area = max(200, 25 * med_area) if med_area else 400
        for p in measure.regionprops(measure.label(rbc)):
            if p.area >= min_area:
                conf = float(np.clip(0.5 + 0.15 * math.log10(p.area / min_area + 1), 0, 0.95))
                cs = measure.find_contours(np.pad(p.image, 1).astype(float), 0.5)
                cong.append({"y": p.centroid[0], "x": p.centroid[1], "area": p.area, "conf": conf,
                             "contours": [max(cs, key=len)] if cs else [], "bbox": p.bbox})
    vac = _vacuoles(img, med_area or 150 / (s * s), tissue) if (stain == "H&E" and vacuoles) else []
    vac = [v for v in vac if v["conf"] >= min_conf]
    # summary numbers
    area_mm2 = tissue.sum() * (px_um / 1000) ** 2 if px_um else 0.0
    S = {"Nuclei detected": n_cells}
    if stain == "H&E" and cells:
        counts = {t: sum(c["type"] == t for c in cells) for t in ("inflammatory", "epithelial", "spindle", "other")}
        S["Inflammatory cells (suggested)"] = len(infl)
        S["Inflammatory cells % of nuclei"] = 100 * len(infl) / n_cells
        S["Epithelial nuclei"] = counts["epithelial"]; S["Spindle nuclei"] = counts["spindle"]
        S["Inflammatory foci (≥%d cells)" % min_focus] = len(foci)
        S["Congestion area % of tissue"] = 100 * sum(c["area"] for c in cong) / max(tissue.sum(), 1)
        S["Vacuoles (suggested)"] = len(vac)
        S["Vacuolated area % of tissue"] = 100 * sum(v["area"] for v in vac) / max(tissue.sum(), 1)
        if area_mm2:
            S["Inflammatory cells per mm²"] = len(infl) / area_mm2
    if stain == "IHC" and cells:
        g = np.array([c["grade"] for c in cells])
        S["Positive nuclei %"] = 100 * (g > 0).mean()
        S["Weak / moderate / strong %"] = " / ".join(f"{100 * (g == k).mean():.1f}" for k in (1, 2, 3))
        S["Cell H-score (0–300)"] = float(((g == 1) * 1 + (g == 2) * 2 + (g == 3) * 3).mean() * 100)
        S["Median nuclear DAB OD"] = float(np.median([c["dab"] for c in cells]))
    if area_mm2:
        S["Tissue area (mm²)"] = area_mm2
    return {"stain": stain, "scale": s, "cells": cells, "inflammatory": infl, "foci": foci, "congestion": cong,
            "vacuoles": vac, "summary": S, "median_nucleus_px": med_area, "dab_thresholds": dab_used,
            "methods": METHOD_TEXT.format(min_focus=min_focus, eps_um=int(focus_um))}


def describe(r, ar=False):
    """Plain-language reading of the image (a draft for the investigator, not a diagnosis)."""
    S = r["summary"]
    n = S.get("Nuclei detected", 0)
    if r["stain"] == "IHC":
        if not n:
            return "لم يتم العثور على أنوية." if ar else "No nuclei were found."
        pos = S["Positive nuclei %"]; hs = S["Cell H-score (0–300)"]
        lvl = ("سلبي تقريبًا" if pos < 5 else "منخفض" if pos < 25 else "متوسط" if pos < 60 else "مرتفع") if ar else \
              ("essentially negative" if pos < 5 else "low" if pos < 25 else "moderate" if pos < 60 else "high")
        if ar:
            return (f"تم اكتشاف {n} نواة. نسبة الأنوية الموجبة لـ DAB {pos:.1f}% (ضعيف/متوسط/قوي: {S['Weak / moderate / strong %']}%)، "
                    f"وH-score الخلوي {hs:.0f} من 300، أي تعبير {lvl}. راجع الخلايا المحددة قبل اعتماد النتيجة.")
        return (f"{n} nuclei were detected. {pos:.1f}% were DAB-positive (weak/moderate/strong: {S['Weak / moderate / strong %']}%), "
                f"cell H-score {hs:.0f}/300, i.e. {lvl} expression. Review the marked cells before accepting the result.")
    if not n:
        return "لم يتم العثور على أنوية؛ قد تكون الصورة بتكبير صغير جدًا أو خارج التركيز." if ar else \
               "No nuclei were found; the magnification may be too low or the image out of focus."
    ni = S.get("Inflammatory cells (suggested)", 0); pct = S.get("Inflammatory cells % of nuclei", 0)
    nf = len(r["foci"]); cg = S.get("Congestion area % of tissue", 0); nv = S.get("Vacuoles (suggested)", 0)
    deg = ("قليلة" if pct < 5 else "متوسطة" if pct < 15 else "كثيفة") if ar else ("few" if pct < 5 else "moderate" if pct < 15 else "dense")
    parts = []
    if ar:
        parts.append(f"تم اكتشاف {n} نواة، منها {ni} يُقترح أنها خلايا التهابية ({pct:.1f}%، درجة {deg}).")
        if nf:
            parts.append(f"توجد {nf} بؤرة ارتشاح التهابي محتملة (أكبرها {max(f['n'] for f in r['foci'])} خلية).")
        if cg >= 0.5:
            parts.append(f"مناطق غنية بكرات الدم الحمراء (احتقان/نزف محتمل) تمثل {cg:.1f}% من النسيج.")
        if nv:
            parts.append(f"{nv} فجوة واضحة مستديرة (تفجّي أو دهون محتملة) تمثل {S['Vacuolated area % of tissue']:.1f}% من النسيج.")
        parts.append("هذه قراءة آلية مساعدة؛ راجع كل اقتراح قبل اعتماده، والتشخيص النهائي للباثولوجي.")
    else:
        parts.append(f"{n} nuclei were detected; {ni} are suggested to be inflammatory cells ({pct:.1f}%, {deg}).")
        if nf:
            parts.append(f"{nf} possible inflammatory infiltrate focus/foci (largest {max(f['n'] for f in r['foci'])} cells).")
        if cg >= 0.5:
            parts.append(f"RBC-rich areas (possible congestion/haemorrhage) cover {cg:.1f}% of the tissue.")
        if nv:
            parts.append(f"{nv} clear round spaces (possible vacuolation / fat) cover {S['Vacuolated area % of tissue']:.1f}% of the tissue.")
        parts.append("This is an automated aid: review every suggestion before accepting it; the diagnosis rests with the pathologist.")
    return " ".join(parts)
