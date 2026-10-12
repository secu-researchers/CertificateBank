from flask import Blueprint, current_app, render_template, request

from .. import render, schema, stats

bp = Blueprint("history", __name__, url_prefix="/history")

_REVIEW_LIMIT = 200
_MIN_SAMPLE = 3  # 이보다 적은 표본은 통계로 보기 어렵다


def _attempts_for(cert_param: str) -> tuple[list[dict], list[str], str]:
    """전체 응시와 자격증 목록, 유효한 필터 값을 돌려준다."""
    all_attempts = current_app.extensions["storage"].all_attempts()
    certs = sorted({a["cert"] for a in all_attempts})
    cert = cert_param if cert_param in certs else ""
    selected = [a for a in all_attempts if not cert or a["cert"] == cert]
    return selected, certs, cert


@bp.get("/", strict_slashes=False)
def index():
    attempts, certs, cert = _attempts_for(request.args.get("cert", ""))
    rows = stats.history_rows(attempts)
    return render_template("history.html", rows=rows, trend=stats.trend(rows), certs=certs, cert=cert)


@bp.get("/stats")
def statistics():
    attempts, certs, cert = _attempts_for(request.args.get("cert", ""))
    graded = stats.graded(attempts)
    return render_template(
        "stats.html",
        certs=certs,
        cert=cert,
        graded_count=len(graded),
        by_topic=stats.aggregate(attempts, "topic"),
        by_type=stats.aggregate(attempts, "type"),
        by_difficulty=stats.aggregate(attempts, "difficulty"),
        min_sample=_MIN_SAMPLE,
    )


@bp.get("/review")
def review():
    attempts, certs, cert = _attempts_for(request.args.get("cert", ""))
    items = stats.wrong_items(attempts)
    result_filter = request.args.get("result", "")
    if result_filter in ("부분정답", "오답"):
        items = [i for i in items if i["result"]["result"] == result_filter]
    else:
        result_filter = ""
    topics = sorted({i["question"]["topic"] for i in items})
    topic = request.args.get("topic", "")
    if topic in topics:
        items = [i for i in items if i["question"]["topic"] == topic]
    else:
        topic = ""
    total = len(items)
    return render_template(
        "review.html",
        items=items[:_REVIEW_LIMIT],
        total=total,
        limit=_REVIEW_LIMIT,
        certs=certs,
        cert=cert,
        topics=topics,
        topic=topic,
        result_filter=result_filter,
        results=("오답", "부분정답"),
        format_answer=render.format_answer,
    )
