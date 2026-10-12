from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import llm

bp = Blueprint("settings", __name__, url_prefix="/settings")

_KEY_PREFIX = "sk-ant-"


def _vault():
    return current_app.extensions["keyvault"]


def current_api_key() -> str | None:
    """세션 토큰으로 서버 메모리의 API 키를 조회한다."""
    return _vault().get(session.get("kv"))


def selected_models() -> dict[str, str]:
    return {
        "generate": session.get("model_generate", llm.DEFAULT_MODEL),
        "grade": session.get("model_grade", llm.DEFAULT_MODEL),
    }


@bp.get("/")
def index():
    return render_template(
        "settings.html",
        has_key=current_api_key() is not None,
        models=llm.MODELS,
        selected=selected_models(),
    )


@bp.post("/key")
def save_key():
    api_key = request.form.get("api_key", "").strip()
    if not api_key.startswith(_KEY_PREFIX) or len(api_key) < 20 or any(c.isspace() for c in api_key):
        flash("API 키 형식이 올바르지 않습니다.", "error")
        return redirect(url_for("settings.index"))
    session["kv"] = _vault().put(api_key, session.get("kv"))
    flash("API 키를 저장했습니다. 서버 메모리에만 보관되며 서버를 재시작하면 사라집니다.", "ok")
    return redirect(url_for("settings.index"))


@bp.post("/clear")
def clear_key():
    _vault().drop(session.pop("kv", None))
    flash("API 키를 삭제했습니다.", "ok")
    return redirect(url_for("settings.index"))


@bp.post("/test")
def test_key():
    api_key = current_api_key()
    if not api_key:
        flash("저장된 API 키가 없습니다.", "error")
    else:
        try:
            llm.check_key(api_key)
            flash("API 키가 유효합니다.", "ok")
        except llm.LLMError as e:
            flash(e.message, "error")
    return redirect(url_for("settings.index"))


@bp.post("/models")
def save_models():
    generate = request.form.get("generate", "")
    grade = request.form.get("grade", "")
    if generate not in llm.MODEL_IDS or grade not in llm.MODEL_IDS:
        flash("지원하지 않는 모델입니다.", "error")
    else:
        session["model_generate"] = generate
        session["model_grade"] = grade
        flash("모델 선택을 저장했습니다.", "ok")
    return redirect(url_for("settings.index"))
