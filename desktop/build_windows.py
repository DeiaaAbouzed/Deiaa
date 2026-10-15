"""Build the Windows desktop package: dist/Rushd-Windows-<version>.zip

    python desktop/build_windows.py

Runs on any OS - nothing is compiled. It assembles the official CPython for Windows from NuGet
(published by the Python Software Foundation; its SHA-512 is checked against NuGet's registry),
the pinned dependencies as ready-made win_amd64 wheels, the app itself and the double-click
launchers. The user unzips it and runs Start-Rushd.cmd; nothing has to be installed.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
PYTHON_VERSION = "3.13.16"
NUPKG_URL = "https://api.nuget.org/v3-flatcontainer/python/{v}/python.{v}.nupkg"
REGISTRATION_URL = "https://api.nuget.org/v3/registration5-gz-semver2/python/{v}.json"
# Parts of the Python distribution the app never uses (build headers, IDLE, Tk, pip, tests).
PRUNE = ["include", "libs", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo", "Lib/test", "Lib/ensurepip", "tcl"]
PRUNE_GLOBS = ["Lib/site-packages/pip*", "DLLs/_tkinter.pyd", "DLLs/tcl*.dll", "DLLs/tk*.dll"]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def windows_python(version: str, cache: Path) -> Path:
    """The NuGet package, verified against the SHA-512 that NuGet's registry publishes for it."""
    package = cache / f"python.{version}.nupkg"
    if not package.exists():
        cache.mkdir(parents=True, exist_ok=True)
        package.write_bytes(fetch(NUPKG_URL.format(v=version)))
    leaf = json.loads(fetch(REGISTRATION_URL.format(v=version)))
    entry = leaf["catalogEntry"]
    catalog = json.loads(fetch(entry)) if isinstance(entry, str) else entry
    actual = base64.b64encode(hashlib.sha512(package.read_bytes()).digest()).decode()
    if catalog.get("packageHashAlgorithm") != "SHA512" or catalog.get("packageHash") != actual:
        package.unlink()
        sys.exit("error: the downloaded Python package does not match NuGet's published hash")
    if "Python Software Foundation" not in str(catalog.get("authors")):
        sys.exit(f"error: unexpected package author {catalog.get('authors')!r}")
    return package


def app_version() -> str:
    text = (ROOT / "backend" / "rushd" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def build(version: str, out: Path) -> Path:
    stage = out / "build" / "Rushd"
    shutil.rmtree(stage.parent, ignore_errors=True)
    python = stage / "python"

    with zipfile.ZipFile(windows_python(version, out / "cache")) as nupkg:
        for info in nupkg.infolist():
            if info.filename.startswith("tools/") and not info.is_dir():
                target = python / info.filename.removeprefix("tools/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(nupkg.read(info))
    for rel in PRUNE:
        shutil.rmtree(python / rel, ignore_errors=True)
    for pattern in PRUNE_GLOBS:
        for path in python.glob(pattern):
            shutil.rmtree(path) if path.is_dir() else path.unlink()

    site = python / "Lib" / "site-packages"
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet", "--target", str(site),
            "--platform", "win_amd64", "--python-version", version.rsplit(".", 1)[0],
            "--implementation", "cp", "--abi", f"cp{''.join(version.split('.')[:2])}", "--abi", "abi3",
            "--abi", "none", "--only-binary=:all:", "--no-compile",
            "-r", str(DESKTOP / "requirements-windows.txt"),
        ],
        check=True,
    )  # fmt: skip
    shutil.rmtree(site / "bin", ignore_errors=True)  # Linux-style console scripts, unused
    for leftover in site.rglob("*.so"):
        sys.exit(f"error: a non-Windows binary slipped in: {leftover}")

    app = stage / "app"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "backend" / "rushd", app / "backend" / "rushd", ignore=ignore)
    shutil.copytree(ROOT / "frontend", app / "frontend", ignore=ignore)
    shutil.copy2(DESKTOP / "launcher.py", app / "launcher.py")
    for name in ("Start-Rushd.cmd", "Share-with-phones.cmd", "README-AR.txt"):
        shutil.copy2(DESKTOP / name, stage / name)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    (stage / "VERSION.txt").write_text(
        f"Rushd {app_version()} ({commit.stdout.strip() or 'unknown'})\r\nPython {version} (Windows x64)\r\n",
        encoding="utf-8",
    )
    for cache in stage.rglob("__pycache__"):
        shutil.rmtree(cache)

    archive = out / f"Rushd-Windows-{app_version()}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zf.write(path, Path("Rushd") / path.relative_to(stage))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", default=PYTHON_VERSION, help="Windows CPython version (from NuGet)")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()
    archive = build(args.python, Path(args.out))
    print(f"{archive} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
