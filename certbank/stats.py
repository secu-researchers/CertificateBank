"""응시 기록 집계. 채점이 끝난 응시만 통계에 포함한다."""
from typing import Any

from . import schema


def graded(attempts: list[dict]) -> list[dict]:
    return [a for a in attempts if a.get("grading")]


def attempt_rate(attempt: dict) -> float | None:
    """정답률 0~1. 배점이 모두 있으면 득점/만점, 없으면 문항별 점수 합/문항 수."""
    g = attempt.get("grading")
    if not g or not attempt["questions"]:
        return None
    if g.get("max_score"):
        return g["total_score"] / g["max_score"]
    return sum(r["score"] for r in g["results"]) / len(attempt["questions"])


def _counts(attempt: dict) -> dict[str, int]:
    results = attempt["grading"]["results"] if attempt.get("grading") else []
    return {k: sum(1 for r in results if r["result"] == k) for k in schema.RESULTS}


def history_rows(attempts: list[dict]) -> list[dict]:
    """최신순 기록 행."""
    rows = []
    for a in sorted(attempts, key=lambda x: x["id"], reverse=True):
        g = a.get("grading")
        rate = attempt_rate(a)
        rows.append({
            "id": a["id"],
            "exam_id": a["exam_id"],
            "cert": a["cert"],
            "submitted_at": a["submitted_at"],
            "count": len(a["questions"]),
            "graded": bool(g),
            "total_score": g["total_score"] if g else None,
            "max_score": g["max_score"] if g else None,
            "rate": rate,
            "percent": round(rate * 100) if rate is not None else None,
            "counts": _counts(a),
            "elapsed_sec": a.get("elapsed_sec"),
        })
    return rows


def trend(rows: list[dict], limit: int = 20) -> list[dict]:
    """채점된 기록의 정답률 추이(오래된 순, 최근 limit개)."""
    done = [r for r in rows if r["graded"]]
    return list(reversed(done[:limit]))


def aggregate(attempts: list[dict], field: str) -> list[dict]:
    """field(topic/type/difficulty)별 누적 결과. 정답률이 낮은 순으로 정렬한다."""
    buckets: dict[str, dict[str, Any]] = {}
    for a in graded(attempts):
        by_no = {r["no"]: r for r in a["grading"]["results"]}
        for q in a["questions"]:
            b = buckets.setdefault(q[field], {"key": q[field], "total": 0, "correct": 0, "partial": 0, "wrong": 0})
            b["total"] += 1
            outcome = by_no[q["no"]]["result"]
            if outcome == "정답":
                b["correct"] += 1
            elif outcome == "부분정답":
                b["partial"] += 1
            else:
                b["wrong"] += 1
    rows = list(buckets.values())
    for b in rows:
        b["rate"] = b["correct"] / b["total"]
        b["percent"] = round(b["rate"] * 100)
    return sorted(rows, key=lambda b: (b["rate"], -b["total"], b["key"]))


def wrong_items(attempts: list[dict]) -> list[dict]:
    """같은 시험지의 같은 문항은 가장 최근 응시만 보고, 오답·부분정답인 문항을 최신순으로 반환한다."""
    latest: dict[tuple[str, int], dict] = {}
    for a in sorted(graded(attempts), key=lambda x: x["id"]):
        by_no = {r["no"]: r for r in a["grading"]["results"]}
        for q in a["questions"]:
            latest[(a["exam_id"], q["no"])] = {"attempt": a, "question": q, "result": by_no[q["no"]]}
    items = []
    for entry in latest.values():
        if entry["result"]["result"] == "정답":
            continue
        a = entry["attempt"]
        items.append({
            "attempt_id": a["id"],
            "cert": a["cert"],
            "submitted_at": a["submitted_at"],
            "question": entry["question"],
            "result": entry["result"],
        })
    return sorted(items, key=lambda i: (i["attempt_id"], i["question"]["no"]), reverse=True)
