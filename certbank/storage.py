"""로컬 JSON 저장소. 시험지는 불변 원본, 응시(attempt)는 문항 사본 + 답안 + 채점 결과."""
import copy
import json
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import schema

_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


class StorageError(Exception):
    pass


class NotFound(StorageError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class Storage:
    def __init__(self, data_dir: Path):
        self.exams_dir = Path(data_dir) / "exams"
        self.attempts_dir = Path(data_dir) / "attempts"
        self.exams_dir.mkdir(parents=True, exist_ok=True)
        self.attempts_dir.mkdir(parents=True, exist_ok=True)

    # --- 파일 입출력 ---------------------------------------------------
    @staticmethod
    def _path(directory: Path, item_id: str) -> Path:
        if not isinstance(item_id, str) or not _ID_RE.match(item_id):
            raise NotFound(f"잘못된 ID: {item_id!r}")
        return directory / f"{item_id}.json"

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        """임시 파일에 쓴 뒤 교체해 쓰기 중단 시 기존 파일이 깨지지 않게 한다."""
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    @staticmethod
    def _read(path: Path) -> dict:
        if not path.is_file():
            raise NotFound(path.stem)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise StorageError(f"손상된 파일 {path.name}: {e}") from e

    def _unique_id(self, directory: Path) -> str:
        for _ in range(10):
            item_id = _new_id()
            if not (directory / f"{item_id}.json").exists():
                return item_id
        raise StorageError("ID 생성 실패")

    # --- 시험지 ----------------------------------------------------------
    def create_exam(
        self,
        cert: str,
        questions: list[dict],
        *,
        model: str | None = None,
        settings: dict | None = None,
        verification_log: list | None = None,
    ) -> dict:
        errors = schema.validate_questions(questions, expect_blank_answer=True)
        if not isinstance(cert, str) or not cert.strip():
            errors.append("cert가 비어 있음")
        if errors:
            raise schema.SchemaError(errors)
        exam = {
            "id": self._unique_id(self.exams_dir),
            "cert": cert,
            "created_at": _now(),
            "model": model,
            "settings": settings or {},
            "questions": copy.deepcopy(questions),
            "verification_log": verification_log or [],
        }
        self._write(self._path(self.exams_dir, exam["id"]), exam)
        return exam

    def load_exam(self, exam_id: str) -> dict:
        return self._read(self._path(self.exams_dir, exam_id))

    def list_exams(self) -> list[dict]:
        return self._summaries(self.exams_dir, self._exam_summary)

    # --- 응시·채점 -------------------------------------------------------
    def create_attempt(
        self, exam_id: str, answers: dict[int, Any], *, elapsed_sec: int | None = None
    ) -> dict:
        """시험지를 복사해 사용자 답안을 채운 응시 기록을 만든다. 원본 시험지는 변경하지 않는다."""
        exam = self.load_exam(exam_id)
        questions = copy.deepcopy(exam["questions"])
        by_no = {q["no"]: q for q in questions}
        errors = [f"존재하지 않는 문항 번호 {no}" for no in answers if no not in by_no]
        for no, ans in answers.items():
            if no in by_no:
                by_no[no]["user_answer"] = ans
        errors.extend(schema.validate_questions(questions, expect_blank_answer=False))
        if errors:
            raise schema.SchemaError(errors)
        attempt = {
            "id": self._unique_id(self.attempts_dir),
            "exam_id": exam_id,
            "cert": exam["cert"],
            "created_at": exam["created_at"],
            "submitted_at": _now(),
            "elapsed_sec": elapsed_sec,
            "model": None,
            "questions": questions,
            "grading": None,
        }
        self._write(self._path(self.attempts_dir, attempt["id"]), attempt)
        return attempt

    def load_attempt(self, attempt_id: str) -> dict:
        return self._read(self._path(self.attempts_dir, attempt_id))

    def save_grading(
        self,
        attempt_id: str,
        results: list[dict],
        overall_feedback: str,
        *,
        model: str | None = None,
        usage: dict | None = None,
    ) -> dict:
        """채점 결과를 검증·저장한다. 주제별 통계와 총점은 코드로 계산한다."""
        attempt = self.load_attempt(attempt_id)
        errors = schema.validate_results(attempt["questions"], results)
        if not isinstance(overall_feedback, str) or not overall_feedback.strip():
            errors.append("총평(overall_feedback)이 비어 있음")
        if errors:
            raise schema.SchemaError(errors)
        ordered = sorted(copy.deepcopy(results), key=lambda r: r["no"])
        attempt["grading"] = {
            "graded_at": _now(),
            "results": ordered,
            "overall_feedback": overall_feedback,
            "usage": usage or {},
            **schema.compute_stats(attempt["questions"], ordered),
        }
        attempt["model"] = model
        self._write(self._path(self.attempts_dir, attempt_id), attempt)
        return attempt

    def all_attempts(self) -> list[dict]:
        """모든 응시 기록(전체 내용)을 오래된 순으로 읽는다. 손상된 파일은 건너뛴다."""
        out = []
        for p in sorted(self.attempts_dir.glob("*.json")):
            try:
                out.append(self._read(p))
            except StorageError:
                continue
        return out

    def list_attempts(self, exam_id: str | None = None) -> list[dict]:
        rows = self._summaries(self.attempts_dir, self._attempt_summary)
        return [r for r in rows if exam_id is None or r["exam_id"] == exam_id]

    # --- 목록 요약 -------------------------------------------------------
    def _summaries(self, directory: Path, summarize) -> list[dict]:
        rows = []
        for p in directory.glob("*.json"):
            try:
                rows.append(summarize(self._read(p)))
            except StorageError:
                continue  # 손상된 파일은 목록에서 제외한다
        return sorted(rows, key=lambda r: r["id"], reverse=True)

    @staticmethod
    def _exam_summary(exam: dict) -> dict:
        types: dict[str, int] = {}
        for q in exam["questions"]:
            types[q["type"]] = types.get(q["type"], 0) + 1
        return {
            "id": exam["id"],
            "cert": exam["cert"],
            "created_at": exam["created_at"],
            "count": len(exam["questions"]),
            "types": types,
        }

    @staticmethod
    def _attempt_summary(attempt: dict) -> dict:
        grading = attempt.get("grading")
        return {
            "id": attempt["id"],
            "exam_id": attempt["exam_id"],
            "cert": attempt["cert"],
            "submitted_at": attempt["submitted_at"],
            "graded": grading is not None,
            "total_score": grading["total_score"] if grading else None,
            "max_score": grading["max_score"] if grading else None,
        }
