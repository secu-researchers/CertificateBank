"""SKILL 로더. 호출마다 디스크에서 읽으며 캐시하지 않는다."""
from pathlib import Path

CORE_TYPES = "문제 유형"
CORE_RULES = "생성 규칙"
CORE_NAMES = (CORE_TYPES, CORE_RULES)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def core_status(skills_dir: Path) -> dict[str, bool]:
    """핵심 두 파일의 존재 여부."""
    return {name: (skills_dir / f"{name}.md").is_file() for name in CORE_NAMES}


def list_certs(skills_dir: Path) -> list[str]:
    """핵심 파일을 제외한 `.md` 파일명(확장자 제외) 목록."""
    if not skills_dir.is_dir():
        return []
    return sorted(
        p.stem
        for p in skills_dir.glob("*.md")
        if p.is_file() and p.stem not in CORE_NAMES
    )


def load_core(skills_dir: Path) -> dict[str, str]:
    """핵심 두 파일 본문. 하나라도 없으면 FileNotFoundError."""
    return {name: _read(skills_dir / f"{name}.md") for name in CORE_NAMES}


def load_cert(skills_dir: Path, cert: str) -> str:
    """자격증 SKILL 본문. 목록에 없는 이름은 거부한다(경로 조작 방지)."""
    if cert not in list_certs(skills_dir):
        raise ValueError(f"알 수 없는 자격증 SKILL: {cert}")
    return _read(skills_dir / f"{cert}.md")


def build_generation_context(skills_dir: Path, cert: str) -> str:
    """생성 프롬프트용 SKILL 본문: 생성 규칙 + 문제 유형 + 자격증 SKILL."""
    core = load_core(skills_dir)
    return "\n\n---\n\n".join(
        [core[CORE_RULES], core[CORE_TYPES], load_cert(skills_dir, cert)]
    )


def build_grading_context(skills_dir: Path, cert: str) -> str:
    """채점 프롬프트용 SKILL 본문: 문제 유형(채점 규칙 포함) + 자격증 SKILL."""
    core = load_core(skills_dir)
    return "\n\n---\n\n".join([core[CORE_TYPES], load_cert(skills_dir, cert)])
