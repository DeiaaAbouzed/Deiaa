"""رُشد للكمبيوتر - runs the whole app on this PC and opens it in an app window.

Started by Start-Rushd.cmd (or Share-with-phones.cmd with --lan) using the bundled Python:

    python\\python.exe -X utf8 -I app\\launcher.py [--lan] [--no-browser] [--port 8000]

Data lives in %LOCALAPPDATA%\\Rushd (override with RUSHD_HOME), outside the app folder, so
unzipping a newer version keeps everything. Settings such as the Claude API key go in
rushd.env there; the first run writes the temporary admin password to a note and opens it.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
HOME = Path(os.environ.get("RUSHD_HOME") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Rushd")
CONFIG = HOME / "rushd.env"
FIRST_RUN_NOTE = HOME / "first-run-admin-password.txt"
PHONES_PAGE = HOME / "phones.html"

CONFIG_TEMPLATE = """\
# إعدادات رُشد على هذا الكمبيوتر - احفظ الملف ثم أعد تشغيل رُشد.
# Rushd settings for this computer - save, then restart Rushd.

# مفتاح Claude API (من console.anthropic.com) لتفعيل القراءة بالذكاء الاصطناعي:
ANTHROPIC_API_KEY=
"""
ALLOWED_KEYS = ("ANTHROPIC_API_KEY",)  # plus any RUSHD_* setting


def say(arabic: str, english: str) -> None:
    """Windows consoles cannot shape Arabic, so every console line is also in English."""
    print(f"{english}\n  {arabic}", flush=True)


def load_config() -> None:
    if not CONFIG.exists():
        CONFIG.write_text(CONFIG_TEMPLATE, encoding="utf-8-sig", newline="\r\n")
    for line in CONFIG.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        key, value = key.strip(), value.strip().strip('"')
        if sep and value and not key.startswith("#") and (key in ALLOWED_KEYS or key.startswith("RUSHD_")):
            os.environ.setdefault(key, value)


def lan_addresses() -> list[str]:
    found: set[str] = set()
    try:  # the address this PC uses to reach the network (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith(("127.", "169.254.")))


def rushd_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, ValueError):
        return False


def port_free(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def open_app(url: str) -> None:
    """Edge or Chrome in app mode looks like a desktop program; fall back to the default browser."""
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    candidates = [
        Path(r) / sub
        for r in roots
        if r
        for sub in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe")
    ]
    for path in [*candidates, *(Path(p) for p in map(shutil.which, ("msedge", "chrome", "google-chrome")) if p)]:
        if path.is_file():
            subprocess.Popen([str(path), f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url)


def write_phones_page(urls: list[str]) -> None:
    import qrcode
    import qrcode.image.svg

    cards = []
    for url in urls:
        svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12).to_string(encoding="unicode")
        cards.append(f'<div class="card">{svg}<p class="url" dir="ltr">{html.escape(url)}</p></div>')
    page = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>رُشد على موبايلات الصيدلية</title>
<style>body{{font-family:Segoe UI,Tahoma,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#10201d;background:#f4f7f6}}
h1{{color:#00796b}}.card{{background:#fff;border-radius:16px;padding:20px;margin:16px 0;text-align:center;box-shadow:0 1px 4px #0002}}
.card svg{{width:260px;height:260px}}.url{{font-size:1.4rem;font-weight:bold}}li{{margin:8px 0;line-height:1.7}}
.warn{{background:#fff4d6;border-radius:12px;padding:12px 16px}}</style></head><body>
<h1>افتح رُشد من موبايلات الصيدلية</h1>
<ol><li>وصّل الموبايل بنفس شبكة الواي فاي الخاصة بهذا الكمبيوتر.</li>
<li>افتح كاميرا الموبايل وامسح الرمز، أو اكتب العنوان في المتصفح (Chrome أو Safari).</li>
<li>من قائمة المتصفح اختر «إضافة إلى الشاشة الرئيسية» ليظهر رُشد كأيقونة تطبيق.</li>
<li>إذا كان <b>تطبيق رُشد للأندرويد</b> مثبتاً: افتحه واضغط «ابحث عن رُشد على الواي فاي» - سيجد هذا الكمبيوتر وحده.</li>
<li>إذا سألك ويندوز عن «جدار الحماية» عند التشغيل، اختر السماح للشبكات الخاصة (Private).</li></ol>
{"".join(cards) or '<p class="warn">لم يتم العثور على شبكة - تأكد أن الكمبيوتر متصل بالواي فاي أو الراوتر.</p>'}
<p class="warn">⚠ هذا الوضع للتشغيل داخل الصيدلية: يعمل ما دام هذا الكمبيوتر مفتوحاً والنافذة السوداء لرُشد مفتوحة،
والاتصال داخل الشبكة غير مشفر (HTTP)، فاستخدمه على واي فاي محمي بكلمة مرور فقط. لتشغيل كل الفروع من أي مكان
وبتشفير كامل استخدم خادماً بـ HTTPS (راجع README).</p></body></html>"""
    PHONES_PAGE.write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rushd desktop launcher")
    parser.add_argument("--lan", action="store_true", help="let phones on the same Wi-Fi use this PC")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    HOME.mkdir(parents=True, exist_ok=True)
    load_config()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    lan = lan_addresses() if args.lan else []
    os.environ.update(
        {
            "RUSHD_DATA_DIR": str(HOME / "data"),
            "RUSHD_SECRETS_DIR": str(HOME / "secrets"),
            "RUSHD_FRONTEND_DIR": str(APP_DIR / "frontend"),
            "RUSHD_COOKIE_SECURE": "false",  # plain HTTP on this PC / the pharmacy Wi-Fi
            # Only these names are accepted in the Host header: blocks DNS-rebinding from websites.
            "RUSHD_ALLOWED_HOSTS": json.dumps(["localhost", "127.0.0.1", *lan]),
        }
    )
    sys.path.insert(0, str(APP_DIR / "backend"))

    if rushd_running(args.port):
        say("رُشد يعمل بالفعل - تم فتح النافذة.", "Rushd is already running - opening it.")
        if not args.no_browser:
            open_app(f"http://localhost:{args.port}")
        return 0
    port = next((p for p in range(args.port, args.port + 20) if port_free(p, host)), None)
    if port is None:
        say("لا يوجد منفذ متاح لتشغيل رُشد.", "No free port found for Rushd.")
        return 1

    from rushd.cli import main as rushd_cli

    first_run = not (HOME / "secrets" / "master.key").exists()
    rushd_cli(["init", "--credentials-file", str(FIRST_RUN_NOTE)] if first_run else ["init"])
    if first_run and FIRST_RUN_NOTE.exists() and not args.no_browser and hasattr(os, "startfile"):
        os.startfile(FIRST_RUN_NOTE)  # Notepad: the admin's temporary password, in readable Arabic

    local_url = f"http://localhost:{port}"
    phone_urls = [f"http://{ip}:{port}" for ip in lan]
    if args.lan:
        write_phones_page(phone_urls)

    def when_ready() -> None:
        for _ in range(120):
            if rushd_running(port):
                break
            time.sleep(0.5)
        say("رُشد جاهز. لا تغلق هذه النافذة أثناء العمل.", f"Rushd is ready at {local_url} - keep this window open.")
        for url in phone_urls:
            say("عنوان الموبايلات على نفس الواي فاي:", f"Phones on the same Wi-Fi: {url}")
        if not args.no_browser:
            open_app(local_url)
            if args.lan:
                webbrowser.open(PHONES_PAGE.as_uri())

    threading.Thread(target=when_ready, daemon=True).start()
    import uvicorn

    uvicorn.run(
        "rushd.main:app_factory",
        factory=True,
        host=host,
        port=port,
        proxy_headers=False,
        server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:  # keep the window readable instead of vanishing
        say(f"حدث خطأ: {exc}", f"Error: {exc!r}")
        sys.exit(1)
