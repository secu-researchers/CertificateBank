from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import generator, llm, schema, skills
from ..qtypes import QUESTION_TYPES
from .settings import current_api_key, selected_models

bp = Blueprint("generate", __name__, url_prefix="/generate")

# 시험 모사 구성 프리셋(자격증 SKILL의 시험 구성과 같은 값)
PRESETS = {
    "정보보안기사실기": {
        "counts": {"단답형": 12, "서술형": 4, "서술형 실습": 1},
        "points": {"단답형": 3, "서술형": 12, "서술형 실습": 16},
    },
    "AZ900": {
        "counts": {"사지선다형": 6, "TrueFalse": 2, "빈칸 채우기형": 2},
        "points": {},
    },
}


def _parse_int(raw: str) -> int | None:
    raw = (raw or "").strip()
    if raw == "":
        return 0
    return int(raw) if raw.isdigit() else None


def _parse_request(form) -> tuple[generator.GenRequest | None, list[str]]:
    errors = []
    counts, points, mix = {}, {}, {}
    for i, t in enumerate(QUESTION_TYPES):
        n = _parse_int(form.get(f"count_{i}", ""))
        if n is None:
            errors.append(f"{t}: 문항 수는 숫자여야 합니다.")
        elif n:
            counts[t] = n
        p = _parse_int(form.get(f"points_{i}", ""))
        if p is None:
            errors.append(f"{t}: 배점은 숫자여야 합니다.")
        elif p:
            points[t] = p
    for i, d in enumerate(schema.DIFFICULTIES):
        n = _parse_int(form.get(f"mix_{i}", ""))
        if n is None:
            errors.append(f"난이도 비율({d})은 숫자여야 합니다.")
        elif n:
            mix[d] = n
    if errors:
        return None, errors
    req = generator.GenRequest(
        cert=form.get("cert", ""),
        counts=counts,
        difficulty_mix=mix,
        topic_scope=form.get("topic_scope", "").strip()[:500],
        points={t: p for t, p in points.items() if t in counts},
    )
    return req, []


@bp.get("/", strict_slashes=False)
def index():
    skills_dir = current_app.config["SKILLS_DIR"]
    return render_template(
        "generate.html",
        certs=skills.list_certs(skills_dir),
        core_ok=all(skills.core_status(skills_dir).values()),
        types=QUESTION_TYPES,
        difficulties=schema.DIFFICULTIES,
        models=llm.MODELS,
        selected=selected_models()["generate"],
        has_key=current_api_key() is not None,
        presets=PRESETS,
        max_batch=generator.MAX_BATCH,
        max_rounds=generator.MAX_ROUNDS,
    )


@bp.post("/start")
def start():
    api_key = current_api_key()
    if not api_key:
        flash("먼저 설정에서 API 키를 입력하세요.", "error")
        return redirect(url_for("generate.index"))
    skills_dir = current_app.config["SKILLS_DIR"]
    req, errors = _parse_request(request.form)
    if req:
        errors = generator.validate_request(req, skills.list_certs(skills_dir))
        if not all(skills.core_status(skills_dir).values()):
            errors.append("핵심 SKILL 파일(문제 유형.md, 생성 규칙.md)이 없습니다.")
    model = request.form.get("model", "")
    if model not in llm.MODEL_IDS:
        errors.append("지원하지 않는 모델입니다.")
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("generate.index"))

    store = current_app.extensions["storage"]

    def target(progress):
        gen = generator.Generator(
            skills_dir,
            lambda **kw: llm.call_json(api_key, **kw),
            progress=progress,
            model=model,
        )
        draft = gen.run(req)
        if draft.complete:
            exam = generator.save_draft(store, draft)
            return {"status": "done", "exam_id": exam["id"], "count": len(exam["questions"])}
        return {"status": "shortfall", "draft": draft, "shortfall": draft.shortfall,
                "count": len(draft.questions)}

    job_id = current_app.extensions["jobs"].start(target)
    return redirect(url_for("generate.job", job_id=job_id))


def _get_job_or_404(job_id: str) -> dict:
    job = current_app.extensions["jobs"].get(job_id)
    if job is None:
        from flask import abort

        abort(404)
    return job


@bp.get("/job/<job_id>")
def job(job_id: str):
    _get_job_or_404(job_id)
    return render_template("generate_job.html", job_id=job_id, max_rounds=generator.MAX_ROUNDS)


@bp.get("/job/<job_id>/status")
def job_status(job_id: str):
    j = _get_job_or_404(job_id)
    draft = j.get("draft")
    return jsonify(
        status=j["status"],
        progress=j["progress"],
        error=j.get("error"),
        exam_id=j.get("exam_id"),
        count=j.get("count"),
        shortfall=j.get("shortfall"),
        log=draft.log if draft and j["status"] == "shortfall" else None,
    )


@bp.post("/job/<job_id>/accept")
def job_accept(job_id: str):
    j = _get_job_or_404(job_id)
    if j["status"] != "shortfall" or not j.get("draft"):
        flash("수락할 수 있는 초안이 없습니다.", "error")
        return redirect(url_for("generate.job", job_id=job_id))
    try:
        exam = generator.save_draft(current_app.extensions["storage"], j["draft"], accept_shortfall=True)
    except generator.GenerationError as e:
        flash(str(e), "error")
        return redirect(url_for("generate.job", job_id=job_id))
    current_app.extensions["jobs"].update(
        job_id, status="done", exam_id=exam["id"], count=len(exam["questions"]), draft=None
    )
    return redirect(url_for("generate.job", job_id=job_id))


@bp.post("/job/<job_id>/discard")
def job_discard(job_id: str):
    j = _get_job_or_404(job_id)
    if j["status"] == "shortfall":
        current_app.extensions["jobs"].update(job_id, status="discarded", draft=None)
    return redirect(url_for("generate.job", job_id=job_id))
