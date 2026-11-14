"""MedStatix project files (.msx).

A project is a ZIP archive of plain JSON / PNG (no pickled code, so a project received from a colleague is safe to
open). It stores the dataset, every analysis that was run (analysis id + options + the data it was run on), figure
edits made in the Prism-style editor, edited captions, and the histology studio state (original image + edit
pipeline). On opening, every analysis is re-run, so results are always reproducible from the data; "Re-run all" does
the same on the current data after the data have changed.
"""
from __future__ import annotations

import base64
import dataclasses
import io
import json
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

FORMAT = "medstatix-project"
VERSION = 1


# ---------------------------------------------------------------------------- JSON helpers
def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return {"__nd__": x.tolist()}
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, float) and np.isnan(x):
        return None
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _unjson(x):
    if isinstance(x, dict):
        if set(x) == {"__nd__"}:
            return np.asarray(x["__nd__"], float)
        return {k: _unjson(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_unjson(v) for v in x]
    return x


def df_to_json(df: pd.DataFrame | None) -> str | None:
    if df is None:
        return None
    return df.to_json(orient="table", index=False, date_format="iso")


def df_from_json(s: str | None) -> pd.DataFrame | None:
    if not s:
        return None
    df = pd.read_json(io.StringIO(s), orient="table")
    return df.reset_index(drop=True)


def spec_to_dict(spec) -> dict:
    d = dataclasses.asdict(spec)
    d["groups"] = {k: np.asarray(v, float).tolist() for k, v in spec.groups.items()}
    d["comparisons"] = [list(c) for c in spec.comparisons]
    return _jsonable(d)


def spec_from_dict(d: dict):
    from ..plots.groupfig import GroupFigSpec
    d = dict(d)
    d["groups"] = {k: np.asarray(v, float) for k, v in d["groups"].items()}
    d["comparisons"] = [tuple(c) for c in d.get("comparisons", [])]
    names = {f.name for f in dataclasses.fields(GroupFigSpec)}
    return GroupFigSpec(**{k: v for k, v in d.items() if k in names})


STYLE_FIELDS = ("plot_type", "error_bar", "colors", "fill_alpha", "point_size", "marker", "point_edge", "line_width",
                "bar_width", "font_family", "font_size", "width_mm", "height_mm", "y_min", "y_max", "y_log", "label_mode",
                "sig_mode", "sig_style", "sig_layout", "star_scheme", "show_ns", "ref1", "ref2", "selected", "caption",
                "title", "ylabel", "xlabel")


def restyle(new_spec, old_spec):
    """Carry the user's figure edits over to a re-computed figure (new data, same design)."""
    s = new_spec.copy()
    for f in STYLE_FIELDS:
        setattr(s, f, getattr(old_spec, f))
    order = [g for g in old_spec.groups if g in s.groups] + [g for g in s.groups if g not in old_spec.groups]
    s.groups = {g: s.groups[g] for g in order}
    return s


# ---------------------------------------------------------------------------- save / load
def save_project(path: str, state: dict):
    """state = {dataset_name, df, entries: [{aid, kwargs, df, edited: {fi: spec}, captions: [..]}], histology: {...},
    settings: {...}}"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {"format": FORMAT, "version": VERSION, "saved": datetime.now().isoformat(timespec="seconds"),
                    "dataset_name": state.get("dataset_name", ""), "settings": _jsonable(state.get("settings", {})),
                    "entries": []}
        z.writestr("data.json", df_to_json(state.get("df")) or "")
        for i, e in enumerate(state.get("entries", [])):
            item = {"aid": e["aid"], "kwargs": _jsonable(e.get("kwargs", {})), "title": e.get("title", ""),
                    "captions": e.get("captions", []),
                    "edited": {str(k): spec_to_dict(v) for k, v in (e.get("edited") or {}).items()}}
            if e.get("df") is not None:
                z.writestr(f"entries/{i}.json", df_to_json(e["df"]))
                item["df"] = f"entries/{i}.json"
            if e.get("html"):
                item["html"] = e["html"]
            manifest["entries"].append(item)
        h = state.get("histology")
        if h and h.get("original") is not None:
            from PIL import Image
            buf = io.BytesIO(); Image.fromarray(h["original"]).save(buf, "PNG")
            z.writestr("histology/original.png", buf.getvalue())
            manifest["histology"] = {"name": h.get("name", ""), "steps": _jsonable(h.get("steps", [])),
                                     "px": h.get("px", 0.0), "quant": _jsonable(h.get("quant") or {})}
        z.writestr("project.json", json.dumps(manifest, indent=1, ensure_ascii=False))


def load_project(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        man = json.loads(z.read("project.json").decode("utf-8"))
        if man.get("format") != FORMAT:
            raise ValueError("Not a MedStatix project file.")
        out = {"dataset_name": man.get("dataset_name", ""), "settings": man.get("settings", {}),
               "df": df_from_json(z.read("data.json").decode("utf-8")), "entries": [], "saved": man.get("saved", "")}
        for item in man.get("entries", []):
            e = {"aid": item["aid"], "kwargs": _unjson(item.get("kwargs", {})), "captions": item.get("captions", []),
                 "title": item.get("title", ""), "html": item.get("html"),
                 "edited": {int(k): spec_from_dict(v) for k, v in item.get("edited", {}).items()},
                 "df": df_from_json(z.read(item["df"]).decode("utf-8")) if item.get("df") else None}
            out["entries"].append(e)
        if "histology" in man:
            from PIL import Image
            img = np.asarray(Image.open(io.BytesIO(z.read("histology/original.png"))).convert("RGB")).copy()
            h = man["histology"]
            out["histology"] = {"original": img, "name": h.get("name", ""), "steps": _unjson(h.get("steps", [])),
                                "px": h.get("px", 0.0), "quant": h.get("quant", {})}
        return out


def png_b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
