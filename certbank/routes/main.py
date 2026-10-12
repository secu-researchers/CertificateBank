from flask import Blueprint, current_app, render_template

from .. import skills

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    skills_dir = current_app.config["SKILLS_DIR"]
    core = skills.core_status(skills_dir)
    return render_template(
        "index.html",
        core=core,
        core_ok=all(core.values()),
        certs=skills.list_certs(skills_dir),
    )
