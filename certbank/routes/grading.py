from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import grader, llm
from ..storage import NotFound
from .settings import current_api_key, selected_models

bp = Blueprint("grading", __name__, url_prefix="/attempts")


def _attempt_or_404(attempt_id: str) -> dict:
    try:
        return current_app.extensions["storage"].load_attempt(attempt_id)
    except NotFound:
        abort(404)


def _job_or_404(job_id: str) -> dict:
    job = current_app.extensions["jobs"].get(job_id)
    if job is None:
        abort(404)
    return job


@bp.post("/<attempt_id>/grade")
def start(attempt_id: str):
    attempt = _attempt_or_404(attempt_id)
    back = redirect(url_for("attempts.view", attempt_id=attempt_id))
    api_key = current_api_key()
    if not api_key:
        flash("먼저 설정에서 API 키를 입력하세요.", "error")
        return back
    if attempt.get("grading") and request.form.get("regrade") != "1":
        flash("이미 채점된 응시입니다. 다시 채점하려면 확인이 필요합니다.", "error")
        return back
    model = request.form.get("model") or selected_models()["grade"]
    if model not in llm.MODEL_IDS:
        flash("지원하지 않는 모델입니다.", "error")
        return back

    store = current_app.extensions["storage"]
    skills_dir = current_app.config["SKILLS_DIR"]

    def target(progress):
        g = grader.Grader(
            skills_dir,
            lambda **kw: llm.call_json(api_key, **kw),
            model=model,
            progress=progress,
        )
        out = g.run(attempt)
        store.save_grading(attempt_id, out.results, out.overall_feedback, model=model, usage=out.usage)
        return {"status": "done"}

    job_id = current_app.extensions["jobs"].start(target)
    return redirect(url_for("grading.job", attempt_id=attempt_id, job_id=job_id))


@bp.get("/<attempt_id>/grade/<job_id>")
def job(attempt_id: str, job_id: str):
    _attempt_or_404(attempt_id)
    _job_or_404(job_id)
    return render_template("grade_job.html", attempt_id=attempt_id, job_id=job_id)


@bp.get("/<attempt_id>/grade/<job_id>/status")
def job_status(attempt_id: str, job_id: str):
    _attempt_or_404(attempt_id)
    j = _job_or_404(job_id)
    return jsonify(status=j["status"], progress=j["progress"], error=j.get("error"))
