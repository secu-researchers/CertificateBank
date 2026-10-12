import secrets
from pathlib import Path

from flask import Flask, abort, request, session

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    # 서버 메모리에만 존재하는 세션 키. 재시작하면 세션(API 키 포함)이 무효화된다.
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.config["SKILLS_DIR"] = BASE_DIR / "skills"
    app.config["DATA_DIR"] = BASE_DIR / "data"
    app.config.update(overrides or {})

    from .jobs import JobRegistry
    from .keyvault import KeyVault
    from .storage import Storage

    app.extensions["storage"] = Storage(app.config["DATA_DIR"])
    app.extensions["keyvault"] = KeyVault()
    app.extensions["jobs"] = JobRegistry()

    @app.before_request
    def _csrf_protect():
        if request.method == "POST":
            expected = session.get("csrf", "")
            given = request.form.get("csrf_token", "")
            if not expected or not secrets.compare_digest(expected, given):
                abort(400)

    @app.context_processor
    def _inject_csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return {"csrf_token": session["csrf"]}

    from . import render
    from .routes import exams, generate, grading, history, main, settings

    app.jinja_env.filters["question_html"] = render.format_question

    app.register_blueprint(main.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(generate.bp)
    app.register_blueprint(exams.bp)
    app.register_blueprint(exams.attempts_bp)
    app.register_blueprint(grading.bp)
    app.register_blueprint(history.bp)
    return app
