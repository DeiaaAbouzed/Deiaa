"""Runs local-model training in a separate process and tracks it in the database."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading

from sqlalchemy import select

from ..db import utcnow
from ..models import TrainingJob

log = logging.getLogger("rushd.training")

_PROBE = r"""
import json, importlib.util
out = {"packages": {m: importlib.util.find_spec(m) is not None for m in ("torch", "transformers", "peft", "accelerate", "safetensors")}}
out["cuda"] = False
out["gpu"] = None
out["gpu_memory_gb"] = None
if out["packages"]["torch"]:
    import torch
    out["torch"] = torch.__version__
    if torch.cuda.is_available():
        out["cuda"] = True
        props = torch.cuda.get_device_properties(0)
        out["gpu"] = props.name
        out["gpu_memory_gb"] = round(props.total_memory / 1024**3, 1)
    out["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
if out["packages"]["transformers"]:
    import transformers
    out["transformers"] = transformers.__version__
print(json.dumps(out))
"""


class TrainingRunner:
    def __init__(self, ctx):
        self.ctx = ctx
        self._proc: subprocess.Popen | None = None
        self._job_id: int | None = None
        self._lock = threading.Lock()

    def readiness(self) -> dict:
        """Probe the ML stack in a throw-away process so the web server never imports torch."""
        try:
            done = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, timeout=120)
            info = json.loads(done.stdout.strip().splitlines()[-1])
        except (subprocess.SubprocessError, ValueError, IndexError):
            info = {"packages": {}, "cuda": False, "gpu": None}
        info["ready"] = all(info.get("packages", {}).get(m) for m in ("torch", "transformers", "peft"))
        return info

    def running_job(self) -> int | None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self._job_id
            return None

    def start(self, job_id: int) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("busy")
            log_path = self.ctx.settings.data_dir / f"training-{job_id}.log"
            log_file = open(log_path, "ab")  # noqa: SIM115 - handed to the child process
            os.chmod(log_path, 0o600)
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "rushd.training.train", "--job-id", str(job_id)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
            self._job_id = job_id
            log_file.close()
        threading.Thread(target=self._watch, args=(self._proc, job_id), daemon=True).start()
        with self.ctx.sf() as db:
            job = db.get(TrainingJob, job_id)
            job.pid = self._proc.pid
            db.commit()

    def cancel(self, job_id: int) -> None:
        with self.ctx.sf() as db:
            job = db.get(TrainingJob, job_id)
            if job and job.status in ("queued", "running"):
                job.status = "cancelling"
                job.message = "جاري الإيقاف..."
                db.commit()
        with self._lock:
            proc = self._proc if self._job_id == job_id else None
        if proc is not None and proc.poll() is None:
            threading.Timer(90, self._kill_if_alive, args=(proc,)).start()

    def recover(self) -> None:
        """After a restart no training process survives: close stale jobs."""
        with self.ctx.sf() as db:
            for job in db.execute(
                select(TrainingJob).where(TrainingJob.status.in_(("queued", "running", "cancelling")))
            ).scalars():
                job.status = "failed"
                job.message = "توقف التدريب بسبب إعادة تشغيل الخادم"
                job.finished_at = utcnow()
            db.commit()

    @staticmethod
    def _kill_if_alive(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    def _watch(self, proc: subprocess.Popen, job_id: int) -> None:
        code = proc.wait()
        with self.ctx.sf() as db:
            job = db.get(TrainingJob, job_id)
            if job is not None and job.status in ("queued", "running", "cancelling"):
                cancelled = job.status == "cancelling"
                job.status = "cancelled" if cancelled else "failed"
                job.message = "تم إيقاف التدريب" if cancelled else f"انتهت عملية التدريب بشكل غير متوقع (رمز {code})"
                job.finished_at = utcnow()
            if job is not None:
                log_path = self.ctx.settings.data_dir / f"training-{job_id}.log"
                try:
                    job.log_tail = log_path.read_text(errors="replace")[-4000:]
                except OSError:
                    pass
            db.commit()
        if self.ctx.local is not None:
            self.ctx.local.refresh()
