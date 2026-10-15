"""Command-line administration: python -m rushd <command>."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from .config import Settings
from .security.crypto import CryptoError, generate_master_key_file


def _context(settings: Settings | None = None):
    from .context import build_context

    try:
        return build_context(settings or Settings())
    except CryptoError as exc:
        sys.exit(f"error: {exc}")


def _password(prompt: str, confirm: bool = False, env: str | None = None) -> str:
    if env and os.environ.get(env):
        return os.environ[env]
    value = getpass.getpass(prompt)
    if confirm and getpass.getpass("أعد الإدخال للتأكيد: ") != value:
        sys.exit("error: كلمتا المرور غير متطابقتين")
    return value


def cmd_init(args) -> None:
    settings = Settings()
    if settings.master_key is None and not settings.key_file.exists():
        generate_master_key_file(settings.key_file)
        print(f"✓ تم إنشاء مفتاح التشفير الرئيسي: {settings.key_file}")
        print("  ⚠ احتفظ بنسخة منه في مكان آمن خارج الخادم. بدونه لا يمكن استرجاع أي بيانات.")
    ctx = _context(settings)
    print(f"✓ قاعدة البيانات جاهزة. بصمة المفتاح: {ctx.keyring.fingerprint}")
    from .models import User

    with ctx.sf() as db:
        if db.execute(select(User.id).limit(1)).first():
            print("✓ يوجد مستخدمون بالفعل - لم يتم إنشاء مدير جديد.")
            return
    _create_user(ctx, args.admin_username or "admin", "admin", "مدير النظام", print_password=True)


def _create_user(ctx, username: str, role: str, full_name: str, print_password: bool) -> None:
    from .models import User
    from .security.passwords import generate_temporary_password, hash_password

    username = username.strip().lower()
    with ctx.sf() as db:
        if db.execute(select(User.id).where(User.username == username)).first():
            sys.exit(f"error: المستخدم {username} موجود بالفعل")
        temporary = generate_temporary_password()
        db.add(
            User(
                username=username,
                full_name=full_name,
                role=role,
                password_hash=hash_password(temporary),
                must_change_password=True,
            )
        )
        db.commit()
    ctx.audit.record("user_created", username="cli", target=username, details={"role": role})
    if print_password:
        print(f"✓ تم إنشاء المستخدم «{username}» بدور {role}")
        print(f"  كلمة المرور المؤقتة (تظهر مرة واحدة فقط): {temporary}")
        print("  سيُطلب تغييرها عند أول دخول" + (" ثم تفعيل التحقق بخطوتين." if role == "admin" else "."))


def cmd_create_user(args) -> None:
    _create_user(_context(), args.username, args.role, args.full_name or "", print_password=True)


def cmd_reset_password(args) -> None:
    from .models import User
    from .security.passwords import generate_temporary_password, hash_password
    from .security.sessions import revoke_user_sessions

    ctx = _context()
    with ctx.sf() as db:
        user = db.execute(select(User).where(User.username == args.username.lower())).scalar_one_or_none()
        if user is None:
            sys.exit("error: المستخدم غير موجود")
        temporary = generate_temporary_password()
        user.password_hash = hash_password(temporary)
        user.must_change_password = True
        user.locked_until = None
        user.failed_logins = 0
        if args.reset_2fa:
            user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
        revoke_user_sessions(db, user.id)
        db.commit()
    ctx.audit.record("password_reset", username="cli", target=args.username, details={"reset_2fa": args.reset_2fa})
    print(f"✓ كلمة المرور المؤقتة الجديدة: {temporary}")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run(
        "rushd.main:app_factory",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
        server_header=False,
        log_level="info",
    )


def cmd_import_drugs(args) -> None:
    from .services import drugs

    ctx = _context()
    with ctx.sf() as db:
        result = drugs.import_csv(db, Path(args.csv).read_text(encoding="utf-8-sig"))
        db.commit()
    print(json.dumps(result, ensure_ascii=False))


def cmd_verify_audit(_args) -> None:
    ctx = _context()
    with ctx.sf() as db:
        result = ctx.audit.verify(db)
    print(
        (
            "✓ سجل التدقيق سليم"
            if result.ok
            else f"✗ سجل التدقيق تم العبث به عند السطر {result.broken_at}: {result.reason}"
        )
        + f" ({result.checked} سطر)"
    )
    sys.exit(0 if result.ok else 2)


def cmd_decrypt_export(args) -> None:
    from .training.export import ExportError, decrypt_stream

    password = _password("كلمة مرور الملف: ", env="RUSHD_EXPORT_PASSWORD")
    try:
        with open(args.input, "rb") as src, open(args.output, "wb") as dst:
            decrypt_stream(src, dst, password)
    except ExportError as exc:
        Path(args.output).unlink(missing_ok=True)
        sys.exit(f"error: {exc}")
    print(f"✓ تم فك التشفير إلى {args.output}")


def cmd_backup(args) -> None:
    from .training.export import EncryptingWriter

    settings = Settings()
    ctx = _context(settings)
    password = _password("كلمة مرور النسخة الاحتياطية (12 حرف على الأقل): ", confirm=True, env="RUSHD_BACKUP_PASSWORD")
    if len(password) < 12:
        sys.exit("error: كلمة المرور قصيرة")
    db_path = Path(ctx.engine.url.database)
    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_dir) as work:
        snapshot = Path(work) / "rushd.db"
        src, dst = sqlite3.connect(db_path), sqlite3.connect(snapshot)
        with dst:
            src.backup(dst)  # consistent copy even while the server is running
        src.close()
        dst.close()
        with open(args.output, "wb") as fh:
            writer = EncryptingWriter(fh, password)
            with tarfile.open(fileobj=writer, mode="w|") as tar:
                tar.add(snapshot, arcname="rushd.db")
                if settings.blobs_dir.exists():
                    tar.add(settings.blobs_dir, arcname="blobs")
                head = settings.data_dir / "audit.head"
                if head.exists():
                    tar.add(head, arcname="audit.head")
            writer.close()
    os.chmod(args.output, 0o600)
    print(f"✓ تم إنشاء نسخة احتياطية مشفرة: {args.output}")
    print(f"  بصمة المفتاح المطلوب للاستعادة: {ctx.keyring.fingerprint} (المفتاح نفسه غير موجود في النسخة)")


def cmd_restore(args) -> None:
    from .training.export import ExportError, decrypt_stream

    target = Path(args.data_dir)
    if target.exists() and any(target.iterdir()):
        sys.exit("error: مجلد الاستعادة يجب أن يكون فارغاً")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    password = _password("كلمة مرور النسخة الاحتياطية: ", env="RUSHD_BACKUP_PASSWORD")
    plain = target / ".restore.tar"
    try:
        with open(args.input, "rb") as src, open(plain, "wb") as dst:
            decrypt_stream(src, dst, password)
        with tarfile.open(plain, "r:") as tar:
            tar.extractall(target, filter="data")  # refuses absolute paths, links and traversal
    except ExportError as exc:
        sys.exit(f"error: {exc}")
    finally:
        plain.unlink(missing_ok=True)
    print(f"✓ تمت الاستعادة إلى {target}. شغّل الخادم بنفس مفتاح التشفير الرئيسي.")


def cmd_rotate_key(args) -> None:
    """Re-encrypt everything under a brand-new master key (server must be stopped)."""
    from . import models
    from .db import make_engine, make_session_factory
    from .security.audit import GENESIS, _payload
    from .security.crypto import KeyRing, load_master_key

    settings = Settings()
    if settings.master_key is not None:
        sys.exit("error: تدوير المفتاح يتطلب مفتاحاً محفوظاً في ملف (RUSHD_MASTER_KEY_FILE)")
    old = KeyRing(load_master_key(settings.key_file))
    if not args.yes:
        answer = input("أوقف الخادم أولاً. سيتم إعادة تشفير كل البيانات بمفتاح جديد. اكتب نعم للمتابعة: ")
        if answer.strip() not in ("نعم", "yes"):
            sys.exit("تم الإلغاء")

    new_key = os.urandom(32)
    new = KeyRing(new_key)
    staging_key = settings.key_file.with_name(settings.key_file.name + ".new")
    if staging_key.exists():
        sys.exit(f"error: يوجد مفتاح مرحلي غير مكتمل {staging_key} - راجع دليل الأمان")
    from .security.crypto import _b64e

    fd = os.open(staging_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(_b64e(new_key) + "\n")

    if not settings.db_url.startswith("sqlite:///"):
        staging_key.unlink()
        sys.exit("error: تدوير المفتاح بهذا الأمر مدعوم مع SQLite فقط")
    db_path = Path(settings.db_url.removeprefix("sqlite:///"))
    stage = settings.data_dir / ".rotate"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(mode=0o700)
    staged_db = stage / "rushd.db"
    src, dst = sqlite3.connect(db_path), sqlite3.connect(staged_db)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    staged_engine = make_engine(f"sqlite:///{staged_db}")
    sf = make_session_factory(staged_engine)
    staged_blobs = stage / "blobs"
    with sf() as db:
        for blob in db.execute(select(models.Blob)).scalars():
            path = settings.blobs_dir / blob.id[:2] / blob.id
            data = old.decrypt_blob(path.read_bytes(), f"{blob.kind}:{blob.id}")
            out = staged_blobs / blob.id[:2] / blob.id
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(new.encrypt_blob(data, f"{blob.kind}:{blob.id}"))
            if blob.kind == "image":
                for rx in db.execute(
                    select(models.Prescription).where(models.Prescription.image_blob == blob.id)
                ).scalars():
                    rx.image_mac = new.content_mac(data)
        for user in db.execute(select(models.User).where(models.User.totp_secret_enc.is_not(None))).scalars():
            aad = f"totp:{user.id}"
            user.totp_secret_enc = new.encrypt_field(old.decrypt_field(user.totp_secret_enc, aad), aad)
        for rx in db.execute(select(models.Prescription)).scalars():
            for column, prefix in (
                ("ai_result_enc", "ai"),
                ("verified_result_enc", "verified"),
                ("shadow_result_enc", "shadow"),
            ):
                token = getattr(rx, column)
                if token is not None:
                    aad = f"{prefix}:{rx.uid}"
                    setattr(rx, column, new.encrypt_field(old.decrypt_field(token, aad), aad))
        prev = GENESIS
        last = None
        for entry in db.execute(select(models.AuditLog).order_by(models.AuditLog.id)).scalars():
            if old.audit_mac(_payload(entry)) != entry.hash:
                sys.exit(f"error: سجل التدقيق تالف عند السطر {entry.id} - تم إلغاء التدوير")
            entry.prev_hash = prev
            entry.hash = new.audit_mac(_payload(entry))
            prev, last = entry.hash, entry
        db.commit()
    staged_engine.dispose()
    if last is not None:
        tag = new.audit_mac(f"head:{last.id}:{last.hash}".encode())
        (stage / "audit.head").write_text(json.dumps({"id": last.id, "hash": last.hash, "tag": tag}))

    # Swap staged data in; keep the old files until the administrator removes them.
    suffix = f".before-rotation-{datetime.now(UTC):%Y%m%d%H%M%S}"
    for name in ("rushd.db", "rushd.db-wal", "rushd.db-shm", "blobs", "audit.head"):
        current = settings.data_dir / name
        if current.exists():
            current.rename(settings.data_dir / (name + suffix))
    staged_db.rename(settings.data_dir / "rushd.db")
    if staged_blobs.exists():
        staged_blobs.rename(settings.blobs_dir)
    if (stage / "audit.head").exists():
        (stage / "audit.head").rename(settings.data_dir / "audit.head")
    settings.key_file.rename(settings.key_file.with_name(settings.key_file.name + suffix))
    staging_key.rename(settings.key_file)
    shutil.rmtree(stage, ignore_errors=True)
    print(f"✓ تم تدوير المفتاح. البصمة الجديدة: {new.fingerprint}")
    print(f"  الملفات القديمة محفوظة بالامتداد {suffix} - احذفها بعد التأكد من عمل النظام.")
    print("  ⚠ النسخ الاحتياطية القديمة تحتاج المفتاح القديم - احتفظ به في مكان آمن غير متصل.")


def cmd_read(args) -> None:
    """Quick test: read one image with the cloud engine and print the result (nothing is stored)."""
    from .ai.engines import EngineError, ReadContext
    from .ai.postprocess import build_result
    from .imaging import ImageRejected, sanitize

    ctx = _context()
    s = ctx.settings
    try:
        clean = sanitize(
            Path(args.image).read_bytes(),
            max_bytes=s.max_upload_mb * 1024 * 1024,
            max_pixels=s.max_image_pixels,
            max_edge=s.ai_max_edge_px,
        )
        with ctx.sf() as db:
            cfg = ctx.store.all(db)
        out = ctx.claude.read(
            clean.jpeg, ReadContext(), model=cfg["ai_model"], effort=cfg["ai_effort"], fallbacks=s.ai_fallbacks
        )
    except (ImageRejected, EngineError) as exc:
        sys.exit(f"error: {exc}")
    result = build_result(
        out.reading, ctx.lexicon.get(), ctx.class_map(), doctor_counts={}, corrections={}, doctor_id=None
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n# تكلفة تقديرية: ${out.cost_usd:.4f}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rushd", description="رُشد - إدارة النظام")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="إنشاء مفتاح التشفير وقاعدة البيانات وأول مدير")
    p.add_argument("--admin-username", default="admin")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("serve", help="تشغيل الخادم")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("create-user", help="إنشاء مستخدم")
    p.add_argument("username")
    p.add_argument("--role", choices=["admin", "trainer", "pharmacist", "trainee"], default="pharmacist")
    p.add_argument("--full-name", default="")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("reset-password", help="إعادة تعيين كلمة مرور (طوارئ)")
    p.add_argument("username")
    p.add_argument("--reset-2fa", action="store_true")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("import-drugs", help="استيراد قائمة أدوية CSV")
    p.add_argument("csv")
    p.set_defaults(func=cmd_import_drugs)

    p = sub.add_parser("verify-audit", help="التحقق من سلامة سجل التدقيق")
    p.set_defaults(func=cmd_verify_audit)

    p = sub.add_parser("decrypt-export", help="فك تشفير ملف بيانات التدريب المصدّر")
    p.add_argument("input")
    p.add_argument("output")
    p.set_defaults(func=cmd_decrypt_export)

    p = sub.add_parser("backup", help="نسخة احتياطية مشفرة")
    p.add_argument("output")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="استعادة نسخة احتياطية إلى مجلد فارغ")
    p.add_argument("input")
    p.add_argument("data_dir")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("rotate-key", help="تدوير مفتاح التشفير الرئيسي")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_rotate_key)

    p = sub.add_parser("read", help="تجربة قراءة صورة روشتة (لا يتم حفظ شيء)")
    p.add_argument("image")
    p.set_defaults(func=cmd_read)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
