"""The image engine backend (CoverMorph) as an internal process. The user never launches it.

Discovery order: bundled ``backend/CoverMorphStudio/CoverMorphStudio.exe`` next to this app (the shipped package always
uses its own engine) → ``IMAGE_PROGRAM_EXE`` (developer override) → the program chosen in 설정 (shared with the Image
Bridge) → CoverMorph's own record of its EXE. Every job is one short-lived backend process, so engines unload when it exits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXIT_DONE, EXIT_FAILED, EXIT_WAITING = 0, 2, 3


def app_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_backend() -> Path | None:
    for candidate in (app_folder() / "backend" / "CoverMorphStudio" / "CoverMorphStudio.exe",
                      app_folder().parent / "backend" / "CoverMorphStudio" / "CoverMorphStudio.exe"):
        if candidate.is_file():
            return candidate
    return None


def find_backend() -> tuple[str, str]:
    """(path, source): env | bundled | saved | covermorph | none."""
    from image_program import resolve_program
    bundled = bundled_backend()
    if bundled is not None:
        return str(bundled), "bundled"
    return resolve_program()


def _child_env() -> dict[str, str]:
    """Backend runs with the app's settings; stray developer variables must not redirect it."""
    env = dict(os.environ)
    env.pop("COVERMORPH_MODELS_DIR", None)
    return env


@dataclass
class JobOutcome:
    status: str                      # done | failed | waiting | cancelled
    result: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    error: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None


class Backend:
    def __init__(self, exe: str | None = None):
        self.exe = exe or find_backend()[0]
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.exe) and Path(self.exe).is_file()

    # -------------------------------------------------------------- status
    def status(self, models_dir: str = "", timeout: float = 45) -> dict[str, Any]:
        if not self.available:
            return {"connected": False, "ready": False, "message": "AI 엔진을 찾지 못했습니다"}
        with tempfile.TemporaryDirectory(prefix="ydts_status_") as tmp:
            out = Path(tmp) / "status.json"
            args = [self.exe, "--backend-status", "--result", str(out)] + (["--models-dir", models_dir] if models_dir else [])
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
                                       env=_child_env(), stdin=subprocess.DEVNULL)
            try:
                process.wait(timeout=timeout)
                data = json.loads(out.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                # An engine older than v1.1 does not know --backend-status and would just sit there: stop it.
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, creationflags=NO_WINDOW)
                return {"connected": True, "ready": False, "outdated": True,
                        "message": "AI 엔진이 응답하지 않습니다 (v1.1 이상 필요). 설정에서 '연결 설정…'을 확인하세요."}
            except (OSError, ValueError) as exc:
                return {"connected": True, "ready": False, "message": f"AI 엔진 상태를 읽지 못했습니다: {exc}"}
        return {"connected": True, **data}

    # -------------------------------------------------------------- jobs
    def run_job(self, payload: dict[str, Any], work_dir: Path, progress: Callable[[dict], None] | None = None,
                timeout: float = 1800) -> JobOutcome:
        if not self.available:
            return JobOutcome("failed", error={"code": "BACKEND_MISSING", "message": "AI 엔진을 찾지 못했습니다.",
                                               "action": "설정 → AI 엔진에서 '연결 설정'을 눌러 주세요."})
        work_dir.mkdir(parents=True, exist_ok=True)
        payload_path, result_path = work_dir / "payload.json", work_dir / "result.json"
        result_path.unlink(missing_ok=True)
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with self._lock:
            self._process = subprocess.Popen([self.exe, "--studio-job", str(payload_path), "--result", str(result_path)],
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                             text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                                             env=_child_env())
        process = self._process
        deadline = time.time() + timeout
        assert process.stdout is not None
        for line in process.stdout:
            if progress:
                try:
                    progress(json.loads(line))
                except ValueError:
                    pass
            if time.time() > deadline:
                self.cancel()
                break
        code = process.wait()
        with self._lock:
            cancelled = self._cancelled
            self._process, self._cancelled = None, False
        if cancelled:
            return JobOutcome("cancelled", exit_code=code)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return JobOutcome("failed", exit_code=code, error={
                "code": "BACKEND_CRASH", "message": "AI 엔진이 결과를 남기지 못하고 종료되었습니다.",
                "action": "'실패 재시도'를 눌러 주세요. 반복되면 '빠른 미리보기'로 시도하세요."})
        if code == EXIT_WAITING or data.get("status") == "waiting":
            return JobOutcome("waiting", data, reasons=list(data.get("reasons") or []), exit_code=code)
        if code == EXIT_DONE and data.get("status") == "done":
            if not data.get("candidates"):
                return JobOutcome("failed", data, exit_code=code, error={
                    "code": "NO_OUTPUT", "message": "생성된 이미지가 없습니다.", "action": "'실패 재시도'를 눌러 주세요."})
            return JobOutcome("done", data, exit_code=code)
        return JobOutcome("failed", data, error=dict(data.get("error") or {"code": "UNKNOWN",
                          "message": "AI 엔진 작업이 실패했습니다.", "action": "'실패 재시도'를 눌러 주세요."}), exit_code=code)

    def cancel(self) -> None:
        """Stop the running job and every engine process it started (process tree)."""
        with self._lock:
            process = self._process
            self._cancelled = process is not None
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, creationflags=NO_WINDOW)

    @property
    def busy(self) -> bool:
        return self._process is not None

    # -------------------------------------------------------------- editor hand-off
    def make_editor_project(self, image: str | Path, out_dir: str | Path, meta: dict[str, Any],
                            timeout: float = 180) -> bool:
        if not self.available:
            return False
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_path = out_dir / ".studio_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        try:
            done = subprocess.run([self.exe, "--editor-project", str(image), "--out", str(out_dir), "--meta", str(meta_path)],
                                  capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=_child_env(),
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return False
        return done.returncode == 0 and (out_dir / "canvas_clean.png").is_file()
