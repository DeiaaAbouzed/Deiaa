"""Build the Android app: dist/Rushd-Android-<version>.apk

    python android/build_apk.py [--keystore PATH]

No Android Studio needed - only the build tools Ubuntu/Debian package, a JDK and Pillow:

    apt install android-sdk-platform-23 aapt dalvik-exchange zipalign apksigner

The app compiles against the API 23 platform library and declares current Android as its target in
the manifest. The signing key is created on first use, outside the repository; keep it: Android only
installs an update over an existing app when both are signed with the same key.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
PLATFORM = Path("/usr/lib/android-sdk/platforms/android-23/android.jar")
ICON_SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def run(*cmd: str | Path, **kw) -> subprocess.CompletedProcess:
    result = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if result.returncode != 0:
        sys.exit(f"error: {' '.join(map(str, cmd[:3]))} failed\n{result.stdout}\n{result.stderr}")
    return result


def unit_tests(work: Path) -> None:
    classes = work / "test-classes"
    classes.mkdir(parents=True)
    sources = [ANDROID / "src/com/rushd/rx/ServerAddress.java", ANDROID / "test/ServerAddressTest.java"]
    run("javac", "--release", "8", "-Xlint:-options", "-encoding", "UTF-8", "-d", classes, *sources)
    print(run("java", "-ea", "-cp", classes, "com.rushd.rx.ServerAddressTest").stdout.strip())


def launcher_icons(res: Path) -> None:
    from PIL import Image

    source = Image.open(ROOT / "frontend/img/icon-512.png").convert("RGBA")
    for density, size in ICON_SIZES.items():
        folder = res / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        source.resize((size, size), Image.LANCZOS).save(folder / "ic_launcher.png", optimize=True)


def signing_key(keystore: Path) -> Path:
    """The release key; created once with a random password kept next to it (both outside git)."""
    password = keystore.with_suffix(".pass")
    if not keystore.exists():
        keystore.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        password.write_text(secrets.token_urlsafe(24))
        password.chmod(0o600)
        run(
            "keytool", "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12", "-alias", "rushd",
            "-keyalg", "RSA", "-keysize", "3072", "-validity", "10950",
            "-dname", "CN=Rushd, O=Rushd, C=EG", "-storepass:file", password, "-keypass:file", password,
        )  # fmt: skip
        keystore.chmod(0o600)
        print(f"created signing key {keystore} - back it up together with {password.name}")
    return password


def build(keystore: Path, out: Path) -> Path:
    if not PLATFORM.exists():
        sys.exit(
            f"error: {PLATFORM} missing - apt install android-sdk-platform-23 aapt dalvik-exchange zipalign apksigner"
        )
    version = re.search(r'android:versionName="([^"]+)"', (ANDROID / "AndroidManifest.xml").read_text()).group(1)
    work = out / "android-build"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    unit_tests(work)

    res = work / "res"
    shutil.copytree(ANDROID / "res", res)
    launcher_icons(res)
    gen, classes, unsigned = work / "gen", work / "classes", work / "app.unsigned.apk"
    gen.mkdir()
    classes.mkdir()
    run(
        "aapt",
        "package",
        "-f",
        "-m",
        "-J",
        gen,
        "-M",
        ANDROID / "AndroidManifest.xml",
        "-S",
        res,
        "-I",
        PLATFORM,
        "-F",
        unsigned,
    )

    sources = sorted((ANDROID / "src").rglob("*.java")) + sorted(gen.rglob("*.java"))
    # -bootclasspath (not --release): java.* must also be what Android 7+ provides, not the JDK.
    run(
        "javac", "-source", "8", "-target", "8", "-bootclasspath", PLATFORM, "-Xlint:-options",
        "-encoding", "UTF-8", "-d", classes, *sources,
    )  # fmt: skip
    run("dalvik-exchange", "--dex", "--min-sdk-version=24", f"--output={work / 'classes.dex'}", classes)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(work / "classes.dex", "classes.dex")

    aligned = work / "app.aligned.apk"
    run("zipalign", "-p", "-f", "4", unsigned, aligned)
    password = signing_key(keystore)
    apk = out / f"Rushd-Android-{version}.apk"
    run(
        "apksigner", "sign", "--ks", keystore, "--ks-key-alias", "rushd",
        "--ks-pass", f"file:{password}",  # PKCS12: the key shares the keystore's password
        "--min-sdk-version", "24", "--out", apk, aligned,
    )  # fmt: skip
    print(run("apksigner", "verify", "--verbose", "--print-certs", apk).stdout.strip())
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    apk.with_name(apk.name + ".sha256").write_text(f"{digest}  {apk.name}\n", encoding="utf-8")
    Path(str(apk) + ".idsig").unlink(missing_ok=True)  # v4 signature file, only for adb streaming installs
    return apk


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keystore", default=str(Path.home() / ".rushd" / "android" / "rushd-release.p12"))
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()
    apk = build(Path(args.keystore), Path(args.out))
    print(f"{apk} ({apk.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
