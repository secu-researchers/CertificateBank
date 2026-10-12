"""백그라운드 작업 관리. 몇 분 걸리는 생성을 스레드에서 실행하고 진행 상황을 조회할 수 있게 한다."""
import logging
import secrets
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class JobRegistry:
    def __init__(self, keep: int = 20):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def start(self, target: Callable[[Callable[[str], None]], dict]) -> str:
        """target(progress)을 스레드에서 실행한다. target은 상태 필드 dict를 반환한다."""
        job_id = secrets.token_urlsafe(8)
        with self._lock:
            self._jobs[job_id] = {"id": job_id, "status": "running", "progress": []}
            for old in list(self._jobs)[: -self._keep]:
                self._jobs.pop(old, None)
        threading.Thread(target=self._run, args=(job_id, target), daemon=True).start()
        return job_id

    def _run(self, job_id: str, target: Callable[[Callable[[str], None]], dict]) -> None:
        def progress(msg: str) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job["progress"].append(msg)

        try:
            fields = target(progress)
        except Exception as exc:  # 화면에는 메시지만 보이고 상세는 서버 로그에 남긴다
            message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
            if not hasattr(exc, "message") and not exc.__class__.__module__.startswith("certbank"):
                log.exception("작업 %s 실패", job_id)
                message = f"예기치 않은 오류: {message}"
            fields = {"status": "error", "error": message}
        self.update(job_id, **fields)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(fields)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return {**job, "progress": list(job["progress"])} if job else None
