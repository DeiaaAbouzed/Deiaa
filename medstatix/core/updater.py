"""In-app update check: reads the public GitHub releases of MedStatix Pro, compares the newest version with the
installed one and downloads the Windows installer when the user agrees. Nothing is sent except the standard request."""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request

REPO = "DeiaaAbouzed/Deiaa"
TAG_PREFIX = "medstatix-v"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PAGE = f"https://github.com/{REPO}/releases"


def parse_version(s):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(s))
    if not m:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in m.groups())


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def pick_latest(releases):
    """From the GitHub releases JSON, return the newest non-draft MedStatix release with its installer asset."""
    best = None
    for r in releases:
        tag = r.get("tag_name", "")
        if not tag.startswith(TAG_PREFIX) or r.get("draft") or r.get("prerelease"):
            continue
        v = parse_version(tag)
        if best is None or v > best["v"]:
            exe = next((a for a in r.get("assets", []) if a.get("name", "").lower().endswith(".exe")
                        and "setup" in a.get("name", "").lower()), None)
            best = {"v": v, "version": ".".join(map(str, v)), "tag": tag, "name": r.get("name") or tag,
                    "notes": r.get("body") or "", "page": r.get("html_url") or PAGE,
                    "url": exe.get("browser_download_url") if exe else None, "size": exe.get("size") if exe else None,
                    "asset": exe.get("name") if exe else None}
    return best


def check_latest(timeout=8):
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "MedStatix-Pro-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return pick_latest(json.loads(fh.read().decode("utf-8")))


def download(url, name=None, progress=None, chunk=1 << 16):
    """Download to the temp folder; progress(done_bytes, total_bytes) may return False to cancel."""
    dest = os.path.join(tempfile.gettempdir(), name or os.path.basename(url))
    req = urllib.request.Request(url, headers={"User-Agent": "MedStatix-Pro-updater"})
    with urllib.request.urlopen(req, timeout=30) as fh, open(dest + ".part", "wb") as out:
        total = int(fh.headers.get("Content-Length") or 0); done = 0
        while True:
            b = fh.read(chunk)
            if not b:
                break
            out.write(b); done += len(b)
            if progress and progress(done, total) is False:
                out.close(); os.remove(dest + ".part")
                return None
    os.replace(dest + ".part", dest)
    return dest
