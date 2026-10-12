"""문항·답안 표시용 렌더러. 모든 텍스트를 이스케이프하고 코드블록·인라인 코드만 태그로 변환한다."""
import re
from typing import Any

from markupsafe import Markup, escape

_FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n(.*?)```", re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")

TIME_MINUTES = {"상": 20, "중": 5, "하": 1}  # 난이도별 표준 풀이 시간


def _text(segment: str) -> Markup:
    html = str(escape(segment))
    html = _INLINE.sub(r"<code>\1</code>", html)
    return Markup(html.replace("\r\n", "\n").replace("\n", "<br>"))


def format_question(text: str) -> Markup:
    out, pos = [], 0
    for m in _FENCE.finditer(text or ""):
        out.append(_text(text[pos : m.start()]))
        lang = escape(m.group(1))
        code = escape(m.group(2).rstrip("\n"))
        out.append(Markup(f'<pre class="code" data-lang="{lang}"><code>{code}</code></pre>'))
        pos = m.end()
    out.append(_text((text or "")[pos:]))
    return Markup("").join(out)


def format_answer(question: dict, answer: Any) -> str:
    """답안을 사람이 읽는 문자열로 바꾼다."""
    if answer is None or answer == "" or answer == []:
        return "(무응답)"
    if isinstance(answer, bool):
        return "참 (true)" if answer else "거짓 (false)"
    if question["type"] == "사지선다형":
        opts = question.get("options") or []
        text = opts[answer - 1] if isinstance(answer, int) and 1 <= answer <= len(opts) else ""
        return f"{answer}번 {text}".strip()
    if isinstance(answer, list):
        return " / ".join(a if a else "(빈칸)" for a in answer)
    return str(answer)


def format_usage(usage: dict) -> str:
    """토큰 사용량 요약. 전체 입력 = 캐시 밖 입력 + 캐시 쓰기 + 캐시 읽기."""
    fresh = usage.get("input_tokens", 0)
    written = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    total_in = fresh + written + read
    hit = f" · 캐시 적중 {round(read / total_in * 100)}%" if total_in else ""
    return (f"입력 {total_in:,} (캐시 읽기 {read:,}, 캐시 쓰기 {written:,}, 일반 {fresh:,}) · "
            f"출력 {usage.get('output_tokens', 0):,}{hit}")


def suggested_minutes(questions: list[dict]) -> int:
    return sum(TIME_MINUTES.get(q["difficulty"], 0) for q in questions)
