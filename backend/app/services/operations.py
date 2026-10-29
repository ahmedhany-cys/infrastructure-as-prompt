"""Background operations with cancellation, one active operation per project,
and recovery of operations interrupted by a server restart."""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.db import SessionLocal
from app.models import Operation
from app.services.terraform.runner import Cancelled

log = logging.getLogger("iap.ops")
MAX_LOG = 60_000


class Busy(RuntimeError):
    pass


class OpContext:
    def __init__(self, op_id: str, project_id: str, cancel: threading.Event) -> None:
        self.op_id = op_id
        self.project_id = project_id
        self.cancel = cancel
        self._buf: list[str] = []

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled("operation cancelled")

    def log(self, line: str) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        self._buf.append(f"[{stamp}] {line}")
        self._flush(progress=line[:200])

    def _flush(self, progress: str | None = None) -> None:
        with SessionLocal() as db:
            op = db.get(Operation, self.op_id)
            if op:
                text = "\n".join(self._buf)
                op.log = text[-MAX_LOG:]
                if progress:
                    op.progress = progress
                db.commit()


class OperationManager:
    def __init__(self, workers: int = 2) -> None:
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="iap-op")
        self.cancels: dict[str, threading.Event] = {}
        self.active: dict[str, str] = {}  # project_id -> op_id
        self.lock = threading.Lock()

    def recover_interrupted(self) -> int:
        with SessionLocal() as db:
            ops = db.query(Operation).filter(Operation.status.in_(["queued", "running"])).all()
            for op in ops:
                op.status = "interrupted"
                op.error = "The server stopped while this operation was running. No result was recorded; re-run it."
                op.finished_at = datetime.now(UTC)
            db.commit()
            return len(ops)

    def submit(self, project_id: str, kind: str, fn: Callable[[OpContext], dict[str, Any] | None]) -> str:
        with self.lock:
            if project_id in self.active:
                raise Busy(f"Another operation ({self.active[project_id]}) is already running for this project.")
            with SessionLocal() as db:
                op = Operation(project_id=project_id, kind=kind, status="queued")
                db.add(op)
                db.commit()
                op_id = op.id
            ev = threading.Event()
            self.cancels[op_id] = ev
            self.active[project_id] = op_id
        self.executor.submit(self._run, op_id, project_id, fn, ev)
        return op_id

    def cancel(self, op_id: str) -> bool:
        ev = self.cancels.get(op_id)
        if ev:
            ev.set()
            return True
        return False

    def _finish(self, op_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with SessionLocal() as db:
            op = db.get(Operation, op_id)
            if op:
                op.status = status
                op.result = result
                op.error = error
                op.finished_at = datetime.now(UTC)
                db.commit()

    def _run(self, op_id: str, project_id: str, fn: Callable[[OpContext], dict[str, Any] | None], ev: threading.Event) -> None:
        ctx = OpContext(op_id, project_id, ev)
        with SessionLocal() as db:
            op = db.get(Operation, op_id)
            if op:
                op.status = "running"
                db.commit()
        try:
            result = fn(ctx)
            self._finish(op_id, "succeeded", result)
        except Cancelled:
            ctx.log("Operation cancelled by user.")
            self._finish(op_id, "cancelled", None, "Cancelled by user.")
        except Exception as exc:  # noqa: BLE001 - recorded on the operation
            log.error("operation %s failed: %s", op_id, traceback.format_exc())
            ctx.log(f"Failed: {type(exc).__name__}: {exc}")
            self._finish(op_id, "failed", None, f"{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                self.active.pop(project_id, None)
                self.cancels.pop(op_id, None)


manager = OperationManager()
