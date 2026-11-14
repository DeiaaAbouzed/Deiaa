"""Typical artwork / statistics requirements of major publishers (from their public author guidelines).

Values are the common defaults; individual journals can differ, so the UI always says "check your journal's guide".
Widths in mm; font sizes in pt (size of the smallest text at final print size).
"""
from __future__ import annotations

JOURNALS = {
    "Elsevier": {"widths": {"single": 90, "1.5 column": 140, "double": 190}, "font": "Arial", "font_size": 8.0,
                 "dpi_photo": 300, "dpi_combo": 500, "dpi_line": 1000, "formats": ["tiff", "eps", "pdf"],
                 "p_style": "p", "max_height": 240,
                 "ar": "إلسفير (Elsevier)"},
    "Springer": {"widths": {"single": 84, "1.5 column": 129, "double": 174}, "font": "Arial", "font_size": 8.0,
                 "dpi_photo": 300, "dpi_combo": 600, "dpi_line": 1200, "formats": ["tiff", "eps"], "p_style": "P",
                 "max_height": 234, "ar": "سبرينجر (Springer)"},
    "Nature Portfolio": {"widths": {"single": 89, "double": 183}, "font": "Arial", "font_size": 7.0,
                         "dpi_photo": 300, "dpi_combo": 600, "dpi_line": 1200, "formats": ["tiff", "pdf", "eps"],
                         "p_style": "P", "max_height": 247, "ar": "نيتشر (Nature Portfolio)"},
    "Wiley": {"widths": {"single": 80, "double": 180}, "font": "Arial", "font_size": 8.0,
              "dpi_photo": 300, "dpi_combo": 600, "dpi_line": 1200, "formats": ["tiff", "eps", "pdf"], "p_style": "P",
              "max_height": 230, "ar": "وايلي (Wiley)"},
    "PLOS": {"widths": {"single": 132, "double": 190}, "font": "Arial", "font_size": 8.0,
             "dpi_photo": 300, "dpi_combo": 600, "dpi_line": 600, "formats": ["tiff", "eps"], "p_style": "p",
             "max_height": 222, "ar": "بلوس (PLOS)"},
    "Cell Press": {"widths": {"single": 85, "1.5 column": 114, "double": 174}, "font": "Arial", "font_size": 7.0,
                   "dpi_photo": 300, "dpi_combo": 500, "dpi_line": 1000, "formats": ["tiff", "pdf", "eps"], "p_style": "p",
                   "max_height": 225, "ar": "سيل بريس (Cell Press)"},
    "MDPI": {"widths": {"single": 85, "double": 170}, "font": "Arial", "font_size": 8.0,
             "dpi_photo": 300, "dpi_combo": 600, "dpi_line": 1000, "formats": ["tiff", "png", "eps"], "p_style": "p",
             "max_height": 230, "ar": "إم دي بي آي (MDPI)"},
}


def apply_journal(name: str, settings, width_key: str = "single"):
    """Set figure font, size and export resolution in the global settings to the journal's typical requirements."""
    j = JOURNALS[name]
    settings.journal = name
    settings.font_family = j["font"]
    settings.font_size = max(j["font_size"], 7.0) + 1.0  # axis text slightly above the minimum
    w = j["widths"].get(width_key) or list(j["widths"].values())[0]
    settings.fig_width_mm = float(w)
    settings.fig_height_mm = float(round(w * 0.8))
    settings.export_dpi = int(j["dpi_combo"])
    return j


def summary(name: str, ar: bool = False) -> str:
    j = JOURNALS[name]
    ws = ", ".join(f"{k} {v} mm" for k, v in j["widths"].items())
    if ar:
        return (f"{j['ar']}: عرض الرسوم {ws}؛ الخط {j['font']} لا يقل عن {j['font_size']:g} نقطة؛ الدقة {j['dpi_photo']} للصور، "
                f"{j['dpi_combo']} للرسوم المركبة، {j['dpi_line']} للرسوم الخطية؛ الصيغ {', '.join(f.upper() for f in j['formats'])}. "
                "تحقق دائمًا من دليل المؤلفين الخاص بمجلتك.")
    return (f"{name}: figure widths {ws}; font {j['font']} ≥ {j['font_size']:g} pt; {j['dpi_photo']} dpi photos, "
            f"{j['dpi_combo']} dpi combination, {j['dpi_line']} dpi line art; formats {', '.join(f.upper() for f in j['formats'])}. "
            "Always check your journal's own guide for authors.")
