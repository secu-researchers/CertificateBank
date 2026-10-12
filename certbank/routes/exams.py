from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import llm, render, schema
from ..storage import NotFound
from .settings import current_api_key, selected_models

bp = Blueprint("exams", __name__, url_prefix="/exams")
attempts_bp = Blueprint("attempts", __name__, url_prefix="/attempts")

_MAX_TEXT = 20000


def _store():
    return current_app.extensions["storage"]


def parse_answers(questions: list[dict], form) -> dict[int, object]:
    """폼 값을 유형별 답안 형식으로 변환한다. 비었거나 형식이 맞지 않으면 무응답으로 둔다."""
    answers: dict[int, object] = {}
    for q in questions:
        raw = form.get(f"q{q['no']}")
        if raw is None:
            continue
        raw = raw[:_MAX_TEXT]
        t = q["type"]
        if t == "TrueFalse":
            if raw in ("true", "false"):
                answers[q["no"]] = raw == "true"
        elif t == "사지선다형":
            if raw in ("1", "2", "3", "4"):
                answers[q["no"]] = int(raw)
        elif t == "빈칸 채우기형":
            lines = [ln.strip() for ln in raw.replace("\r\n", "\n").split("\n")]
            while lines and not lines[-1]:
                lines.pop()
            if lines:
                answers[q["no"]] = lines
        else:
            text = raw.strip()
            if text:
                answers[q["no"]] = text
    return answers


def _load_or_404(loader, item_id: str) -> dict:
    try:
        return loader(item_id)
    except NotFound:
        abort(404)


@bp.get("/")
def index():
    store = _store()
    attempt_counts: dict[str, int] = {}
    for a in store.list_attempts():
        attempt_counts[a["exam_id"]] = attempt_counts.get(a["exam_id"], 0) + 1
    return render_template("exams.html", exams=store.list_exams(), attempt_counts=attempt_counts)


@bp.get("/<exam_id>")
def solve(exam_id: str):
    exam = _load_or_404(_store().load_exam, exam_id)
    return render_template(
        "exam_solve.html",
        exam=exam,
        suggested=render.suggested_minutes(exam["questions"]),
    )


@bp.post("/<exam_id>/submit")
def submit(exam_id: str):
    store = _store()
    exam = _load_or_404(store.load_exam, exam_id)
    answers = parse_answers(exam["questions"], request.form)
    elapsed = request.form.get("elapsed_sec", "")
    elapsed_sec = int(elapsed) if elapsed.isdigit() and int(elapsed) < 7 * 24 * 3600 else None
    try:
        attempt = store.create_attempt(exam_id, answers, elapsed_sec=elapsed_sec)
    except schema.SchemaError as e:
        for msg in e.errors:
            flash(msg, "error")
        return redirect(url_for("exams.solve", exam_id=exam_id))
    return redirect(url_for("attempts.view", attempt_id=attempt["id"]))


@attempts_bp.get("/<attempt_id>")
def view(attempt_id: str):
    attempt = _load_or_404(_store().load_attempt, attempt_id)
    grading = attempt.get("grading")
    results = {r["no"]: r for r in grading["results"]} if grading else {}
    counts = {k: sum(1 for r in results.values() if r["result"] == k) for k in schema.RESULTS}
    return render_template(
        "attempt.html",
        attempt=attempt,
        grading=grading,
        results=results,
        counts=counts,
        format_answer=render.format_answer,
        models=llm.MODELS,
        selected=selected_models()["grade"],
        has_key=current_api_key() is not None,
    )
