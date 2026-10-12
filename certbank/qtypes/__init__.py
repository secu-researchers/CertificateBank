"""문항 유형 레지스트리. 유형 목록의 단일 출처이며 `skills/문제 유형.md`의 8종과 일치해야 한다.

유형을 추가하려면 REGISTRY에 TypeSpec 하나를 더하고 `문제 유형.md` 표를 함께 갱신한다.
"""
from dataclasses import dataclass
from typing import Any, Callable

OPT_FORBIDDEN = "forbidden"  # options 필드를 두지 않는다
OPT_REQUIRED = "required"  # options 필드가 필수다
OPT_OPTIONAL = "optional"  # 있으면 보기형, 없으면 무보기형


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_choice(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, str) for x in v)


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


@dataclass(frozen=True)
class TypeSpec:
    name: str
    options: str
    answer_ok: Callable[[Any], bool]
    answer_hint: str
    option_count: int | None = None
    partial_allowed: bool = False


REGISTRY: dict[str, TypeSpec] = {
    spec.name: spec
    for spec in (
        TypeSpec("TrueFalse", OPT_FORBIDDEN, _is_bool, "true 또는 false"),
        TypeSpec("사지선다형", OPT_REQUIRED, _is_choice, "보기 번호(1~4)", option_count=4),
        TypeSpec("빈칸 채우기형", OPT_OPTIONAL, _is_str_list, "빈칸별 답 문자열 목록", partial_allowed=True),
        TypeSpec("단답형", OPT_OPTIONAL, _is_str, "짧은 문자열"),
        TypeSpec("서술형", OPT_OPTIONAL, _is_str, "문장", partial_allowed=True),
        TypeSpec("논술형", OPT_OPTIONAL, _is_str, "여러 문단", partial_allowed=True),
        TypeSpec("단답형 실습", OPT_OPTIONAL, _is_str, "짧은 문자열"),
        TypeSpec("서술형 실습", OPT_OPTIONAL, _is_str, "문장", partial_allowed=True),
    )
}

QUESTION_TYPES = tuple(REGISTRY)
