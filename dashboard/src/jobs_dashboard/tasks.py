"""Background task runner for long-lived actions (ingest, tailoring).

These shell out to the existing scripts (scripts/ingest.sh, scripts/tailor-job.sh)
and can run for minutes, so we launch them as detached asyncio subprocesses,
stream their output to a log file under data/reports/, and keep a small in-memory
registry the UI polls. Only one task of each *kind* runs at a time.

Every command is wrapped in `flock -n data/.pipeline.lock` so a dashboard-triggered
ingest/tailor never races a run-pipeline.sh run (which holds the same lock) — except
commands started with use_flock=False, which take that lock themselves.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import db


@dataclass
class Task:
    kind: str
    label: str
    log_path: Path
    status: str = "running"  # running | done | failed
    started: float = field(default_factory=time.time)
    finished: float | None = None
    returncode: int | None = None


# kind -> most recent Task (a new run of the same kind replaces the record)
_tasks: dict[str, Task] = {}
_lock = asyncio.Lock()


def _lockfile() -> Path:
    return db.data_dir() / ".pipeline.lock"


def is_running(kind: str) -> bool:
    t = _tasks.get(kind)
    return t is not None and t.status == "running"


def snapshot() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind, t in _tasks.items():
        out[kind] = {
            "kind": t.kind,
            "label": t.label,
            "status": t.status,
            "started": t.started,
            "finished": t.finished,
            "returncode": t.returncode,
            "log": t.log_path.name,
        }
    return out


def tail_log(name: str, max_bytes: int = 16_384) -> str | None:
    """Return the tail of a log file in data/reports/ (path-validated)."""
    reports = (db.data_dir() / "reports").resolve()
    target = (reports / name).resolve()
    if reports not in target.parents or not target.is_file():
        return None
    data = target.read_bytes()
    return data[-max_bytes:].decode("utf-8", errors="replace")


async def start(
    kind: str,
    argv: list[str],
    label: str,
    log_name: str,
    use_flock: bool = True,
) -> tuple[bool, str]:
    """Launch `argv` under flock as a background task of the given kind.

    Returns (started, message). started is False if one of this kind is already
    running.

    use_flock=False is for commands that take data/.pipeline.lock themselves
    (run-pipeline.sh): wrapping those would make the inner flock lose to our
    outer one and the script would no-op with exit 0, reported as "done".
    """
    async with _lock:
        if is_running(kind):
            return False, f"a {kind} task is already running"
        reports = db.data_dir() / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        log_path = reports / log_name
        task = Task(kind=kind, label=label, log_path=log_path)
        _tasks[kind] = task

    cmd = ["flock", "-n", str(_lockfile()), *argv] if use_flock else list(argv)
    asyncio.create_task(_run(task, cmd))
    return True, f"started {label}"


async def _run(task: Task, cmd: list[str]) -> None:
    with task.log_path.open("wb") as log:
        log.write(f"$ {' '.join(cmd)}\n".encode())
        log.flush()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(db.repo_root()),
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            rc = await proc.wait()
        except Exception as exc:  # spawn failure (e.g. flock missing)
            log.write(f"\n[dashboard] failed to launch: {exc}\n".encode())
            task.status = "failed"
            task.finished = time.time()
            task.returncode = -1
            return
    task.returncode = rc
    task.finished = time.time()
    # flock returns 1 when it can't take the lock (another run holds it).
    task.status = "done" if rc == 0 else "failed"
