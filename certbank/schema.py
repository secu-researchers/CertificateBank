"""문항·시험지·채점 결과 스키마와 검증. 서식은 `skills/문제 유형.md`를 따른다."""
from typing import Any

from .qtypes import OPT_FORBIDDEN, OPT_REQUIRED, QUESTION_TYPES, REGISTRY

DIFFICULTIES = ("상", "중", "하")
RESULTS = ("정답", "부분정답", "오답")

# 정답·채점 기준(answer, rubric 등)은 문항에 저장하지 않으므로 허용 필드에 없다.
_REQUIRED_FIELDS = {"no", "topic", "type", "difficulty", "question", "user_answer"}
_OPTIONAL_FIELDS = {"options", "points"}


class SchemaError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_answer(question: dict, answer: Any) -> str | None:
    """사용자 답안 형식 검증. None(무응답)은 허용한다. 오류 문장 또는 None을 반환."""
    if answer is None:
        return None
    spec = REGISTRY[question["type"]]
    if not spec.answer_ok(answer):
        return f"문항 {question['no']}: 답안 형식 오류(요구: {spec.answer_hint})"
    return None


def validate_question(q: Any, *, expect_blank_answer: bool) -> list[str]:
    """문항 검증. 출제 직후에는 expect_blank_answer=True(user_answer가 null이어야 함)."""
    if not isinstance(q, dict):
        return ["문항이 객체가 아님"]
    errors: list[str] = []
    label = f"문항 {q.get('no', '?')}"

    missing = _REQUIRED_FIELDS - q.keys()
    if missing:
        errors.append(f"{label}: 필수 필드 누락 {sorted(missing)}")
    unknown = q.keys() - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if unknown:
        errors.append(f"{label}: 허용되지 않는 필드 {sorted(unknown)}")
    if missing:
        return errors

    if not _is_int(q["no"]) or q["no"] < 1:
        errors.append(f"{label}: no는 1 이상의 정수")
    if not _nonempty_str(q["topic"]):
        errors.append(f"{label}: topic이 비어 있음")
    if q["type"] not in QUESTION_TYPES:
        errors.append(f"{label}: 알 수 없는 유형 {q['type']!r}")
        return errors
    if q["difficulty"] not in DIFFICULTIES:
        errors.append(f"{label}: difficulty는 {DIFFICULTIES} 중 하나")
    if not _nonempty_str(q["question"]):
        errors.append(f"{label}: question이 비어 있음")
    if "points" in q and (not _is_int(q["points"]) or q["points"] < 1):
        errors.append(f"{label}: points는 1 이상의 정수")

    spec = REGISTRY[q["type"]]
    has_options = "options" in q
    if spec.options == OPT_FORBIDDEN and has_options:
        errors.append(f"{label}: {spec.name}은 options를 두지 않음")
    if spec.options == OPT_REQUIRED and not has_options:
        errors.append(f"{label}: {spec.name}은 options 필수")
    if has_options and spec.options != OPT_FORBIDDEN:
        opts = q["options"]
        if not isinstance(opts, list) or not opts or not all(_nonempty_str(o) for o in opts):
            errors.append(f"{label}: options는 비어 있지 않은 문자열 목록")
        elif spec.option_count is not None and len(opts) != spec.option_count:
            errors.append(f"{label}: options는 정확히 {spec.option_count}개")

    if expect_blank_answer:
        if q["user_answer"] is not None:
            errors.append(f"{label}: 출제 시 user_answer는 null이어야 함")
    else:
        err = validate_answer(q, q["user_answer"])
        if err:
            errors.append(err)
    return errors


def validate_questions(questions: Any, *, expect_blank_answer: bool) -> list[str]:
    if not isinstance(questions, list) or not questions:
        return ["questions는 비어 있지 않은 목록이어야 함"]
    errors: list[str] = []
    for q in questions:
        errors.extend(validate_question(q, expect_blank_answer=expect_blank_answer))
    nos = [q.get("no") for q in questions if isinstance(q, dict)]
    if nos != list(range(1, len(questions) + 1)):
        errors.append("문항 번호는 1부터 순차여야 함")
    return errors


def validate_results(questions: list[dict], results: Any) -> list[str]:
    """채점 결과(문항별 출력) 검증. 문항 전체를 정확히 한 번씩 덮어야 한다."""
    if not isinstance(results, list):
        return ["results는 목록이어야 함"]
    errors: list[str] = []
    by_no = {q["no"]: q for q in questions}
    seen: set[int] = set()
    for r in results:
        if not isinstance(r, dict):
            errors.append("채점 결과 항목이 객체가 아님")
            continue
        no = r.get("no")
        label = f"채점 {no}"
        if no not in by_no:
            errors.append(f"{label}: 존재하지 않는 문항")
            continue
        if no in seen:
            errors.append(f"{label}: 중복")
        seen.add(no)
        q = by_no[no]
        if r.get("result") not in RESULTS:
            errors.append(f"{label}: result는 {RESULTS} 중 하나")
        elif r["result"] == "부분정답" and not REGISTRY[q["type"]].partial_allowed:
            errors.append(f"{label}: {q['type']}은 부분정답 불가")
        score = r.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score < 0:
            errors.append(f"{label}: score는 0 이상의 숫자")
        elif "points" in q and score > q["points"]:
            errors.append(f"{label}: score가 배점({q['points']})을 초과")
        ca = r.get("correct_answer")
        if ca is None or ca == [] or (isinstance(ca, str) and not ca.strip()):
            errors.append(f"{label}: correct_answer 누락")
        if not _nonempty_str(r.get("solution")):
            errors.append(f"{label}: solution(풀이과정) 누락")
    missing = set(by_no) - seen
    if missing:
        errors.append(f"채점되지 않은 문항 {sorted(missing)}")
    return errors


def compute_stats(questions: list[dict], results: list[dict]) -> dict:
    """주제별 정답률과 총점. 총점은 모든 문항에 배점이 있을 때만 계산한다."""
    res_by_no = {r["no"]: r for r in results}
    topics: dict[str, dict] = {}
    for q in questions:
        t = topics.setdefault(q["topic"], {"topic": q["topic"], "total": 0, "correct": 0, "partial": 0})
        t["total"] += 1
        outcome = res_by_no[q["no"]]["result"]
        if outcome == "정답":
            t["correct"] += 1
        elif outcome == "부분정답":
            t["partial"] += 1
    all_points = all("points" in q for q in questions)
    total_score = sum(res_by_no[q["no"]]["score"] for q in questions) if all_points else None
    max_score = sum(q["points"] for q in questions) if all_points else None
    return {"topic_stats": list(topics.values()), "total_score": total_score, "max_score": max_score}
