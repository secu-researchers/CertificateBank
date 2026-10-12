"""시험지 생성기: 배치 생성 → 별도 호출 자가검증(최대 3회) → 조립. 절차는 skills/생성 규칙.md를 따른다."""
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import render, schema, skills
from .qtypes import QUESTION_TYPES, REGISTRY

MAX_BATCH = 10  # 생성 규칙: 한 배치는 최대 10문항
MAX_ROUNDS = 2  # 생성→검증 회차 한도. 한 문항은 최대 2번 검증받는다
MAX_TOTAL = 50

DEFECT_ITEMS = ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3")

_QUESTION_PROPS = {
    "topic": {"type": "string"},
    "type": {"type": "string", "enum": list(QUESTION_TYPES)},
    "difficulty": {"type": "string", "enum": list(schema.DIFFICULTIES)},
    "question": {"type": "string"},
    "options": {"type": "array", "items": {"type": "string"}},
}
GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": _QUESTION_PROPS,
                "required": list(_QUESTION_PROPS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "independent_answer": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "defects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string", "enum": list(DEFECT_ITEMS)},
                                "reason": {"type": "string"},
                            },
                            "required": ["item", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["no", "independent_answer", "passed", "defects"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

_GEN_INSTRUCTIONS = """# 실행 지침
위 SKILL 규칙에 따라 문항을 생성하는 출제자로서 JSON 스키마에 맞게만 출력한다.
- 정답, 해설, 채점 기준은 출력에 포함하지 않는다.
- no, user_answer, points는 쓰지 않는다. 시스템이 부여한다.
- options: 사지선다형은 보기 4개, 보기형 빈칸 채우기형은 필요한 만큼, 그 외 유형은 빈 배열.
- 요청한 유형별 문항 수를 정확히 맞춘다.
- 이미 출제된 문항과 주제·내용이 겹치지 않게 한다.
- 이전 시도의 결함이 주어지면 같은 결함을 반복하지 않는다."""

_VERIFY_INSTRUCTIONS = """# 검증 지침
위 SKILL 규칙의 자가검증 항목으로 후보 문항을 엄격하게 검증하는 검증자로서 JSON 스키마에 맞게만 출력한다.
- 후보 문항마다 먼저 직접 풀어 independent_answer에 적는다. 정답이 하나로 도출되지 않으면 결함이다.
- 결함 항목 코드: A1 서식, A2 정답 도출성, A3 사실·논리 오류, A4 핵심 요소, A5 난이도, B1 SKILL 범위·카테고리 부합, B2 요청 분포(유형·난이도·주제 범위), B3 문항 간 중복·사소한 세부.
- 사실 여부에 확신이 없거나 SKILL의 법규 기준표에 없는 조문·수치·기한을 단정하면 A3 결함이다.
- passed는 결함이 하나도 없을 때만 true다. 결함이 있으면 passed=false이고 defects에 항목 코드와 구체적 사유를 적는다.
- 모든 후보 문항 번호(no)에 대해 결과를 하나씩 반환한다."""


class GenerationError(Exception):
    pass


@dataclass
class GenRequest:
    cert: str
    counts: dict[str, int]  # 유형 → 문항 수(요청 순서가 시험지 순서)
    difficulty_mix: dict[str, int] = field(default_factory=dict)  # 상/중/하 비율, 비어 있으면 지정 없음
    topic_scope: str = ""
    points: dict[str, int] = field(default_factory=dict)  # 유형 → 문항당 배점

    def total(self) -> int:
        return sum(self.counts.values())

    def to_settings(self) -> dict:
        return {
            "counts": self.counts,
            "difficulty_mix": self.difficulty_mix,
            "topic_scope": self.topic_scope,
            "points": self.points,
        }


@dataclass
class Draft:
    cert: str
    model: str
    questions: list[dict]
    shortfall: dict[str, int]
    log: list[dict]
    settings: dict
    usage: dict

    @property
    def complete(self) -> bool:
        return not self.shortfall and bool(self.questions)


def validate_request(req: GenRequest, certs: list[str]) -> list[str]:
    errors = []
    if req.cert not in certs:
        errors.append("자격증 SKILL을 선택하세요.")
    for t, n in req.counts.items():
        if t not in REGISTRY:
            errors.append(f"알 수 없는 유형: {t}")
        elif not isinstance(n, int) or n < 0:
            errors.append(f"{t}: 문항 수는 0 이상의 정수여야 합니다.")
    if req.total() < 1:
        errors.append("문항을 1개 이상 지정하세요.")
    if req.total() > MAX_TOTAL:
        errors.append(f"문항은 최대 {MAX_TOTAL}개까지 지정할 수 있습니다.")
    for t, p in req.points.items():
        if t not in REGISTRY or not isinstance(p, int) or p < 1:
            errors.append(f"{t}: 배점은 1 이상의 정수여야 합니다.")
    for d, n in req.difficulty_mix.items():
        if d not in schema.DIFFICULTIES or not isinstance(n, int) or n < 0:
            errors.append(f"난이도 비율 오류: {d}")
    return errors


def plan_batches(counts: dict[str, int]) -> list[dict[str, int]]:
    """유형 순서대로 문항 슬롯을 펼쳐 MAX_BATCH개씩 묶는다."""
    slots = [t for t, n in counts.items() for _ in range(n)]
    batches = []
    for i in range(0, len(slots), MAX_BATCH):
        batch: dict[str, int] = {}
        for t in slots[i : i + MAX_BATCH]:
            batch[t] = batch.get(t, 0) + 1
        batches.append(batch)
    return batches


def _add_usage(total: dict, usage: dict) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int):
            total[k] = total.get(k, 0) + v


class Generator:
    def __init__(
        self,
        skills_dir: Path,
        llm_call: Callable[..., Any],
        *,
        effort: str = "high",
        progress: Callable[[str], None] | None = None,
        model: str = "",
    ):
        self.skills_dir = Path(skills_dir)
        self.llm_call = llm_call
        self.effort = effort
        self.progress = progress or (lambda msg: None)
        self.model = model
        self.usage: dict = {}
        self.log: list[dict] = []

    # --- LLM 호출 ----------------------------------------------------------
    def _call(self, context: str, system: str, user: str, json_schema: dict, max_tokens: int) -> Any:
        """context(SKILL 본문)는 생성·검증 호출이 같은 값을 공유해 프롬프트 캐시에서 읽힌다."""
        result = self.llm_call(
            model=self.model,
            system=system,
            cached_context=context,
            user=user,
            schema=json_schema,
            max_tokens=max_tokens,
            effort=self.effort,
        )
        _add_usage(self.usage, result.usage)
        return result.data

    def _generate(self, context: str, pending: dict[str, int], feedback: dict[str, list[str]],
                  req: GenRequest, prior: list[str]) -> list[dict]:
        lines = [f"자격증: {req.cert}", "이번 요청 문항 수(유형별): " + ", ".join(f"{t} {n}" for t, n in pending.items() if n)]
        if req.difficulty_mix:
            mix = ":".join(str(req.difficulty_mix.get(d, 0)) for d in schema.DIFFICULTIES)
            lines.append(f"난이도 비율(상:중:하): {mix}")
        else:
            lines.append("난이도: 지정 없음. SKILL의 난이도 기준에 맞춰 균형 있게 구성한다.")
        if req.topic_scope.strip():
            lines.append(f"주제 범위: {req.topic_scope.strip()}")
        if prior:
            lines.append("이미 출제된 문항(중복 금지):\n" + "\n".join(f"- {p}" for p in prior))
        fb = [f"- {t}: {r}" for t, reasons in feedback.items() if pending.get(t) for r in reasons[-5:]]
        if fb:
            lines.append("이전 시도의 결함(반복하지 말 것):\n" + "\n".join(fb))
        data = self._call(context, _GEN_INSTRUCTIONS, "\n".join(lines), GEN_SCHEMA, 32000)
        raw = data.get("questions") if isinstance(data, dict) else None
        return raw if isinstance(raw, list) else []

    def _verify(self, context: str, cands: list[dict], req: GenRequest, prior: list[str]) -> dict[int, dict]:
        payload = [
            {k: c[k] for k in ("no", "topic", "type", "difficulty", "question", "options") if k in c}
            for c in cands
        ]
        lines = [
            f"자격증: {req.cert}",
            "요청 조건: " + json.dumps(req.to_settings(), ensure_ascii=False),
            "후보 문항:\n" + json.dumps(payload, ensure_ascii=False, indent=1),
        ]
        if prior:
            lines.append("이미 통과한 문항(중복 판단용):\n" + "\n".join(f"- {p}" for p in prior))
        data = self._call(context, _VERIFY_INSTRUCTIONS, "\n\n".join(lines), VERIFY_SCHEMA, 16000)
        results = data.get("results") if isinstance(data, dict) else None
        return {r["no"]: r for r in results or [] if isinstance(r, dict) and isinstance(r.get("no"), int)}

    # --- 배치 처리 ---------------------------------------------------------
    def _run_batch(self, bi: int, batch: dict[str, int], req: GenRequest, context: str,
                   prior: list[str]) -> tuple[list[dict], dict[str, int]]:
        pending = dict(batch)
        accepted: list[dict] = []
        feedback: dict[str, list[str]] = {}
        for rnd in range(1, MAX_ROUNDS + 1):
            if not any(pending.values()):
                break
            self.progress(f"배치 {bi} · {rnd}회차: 생성 중 ({sum(pending.values())}문항)")
            raw = self._generate(context, pending, feedback, req, prior + [_stem(q) for q in accepted])
            cands = self._select(raw, pending)
            if not cands:
                self.log.append({"batch": bi, "round": rnd, "topic": None, "type": None, "passed": False,
                                 "defects": [{"item": "B2", "reason": "요청한 유형의 문항이 생성되지 않음"}]})
                self.progress(f"배치 {bi} · {rnd}회차: 사용할 수 있는 문항이 생성되지 않음")
                continue
            defects = self._local_defects(cands, accepted, prior)
            to_verify = [c for c in cands if not defects[c["no"]]]
            if to_verify:
                self.progress(f"배치 {bi} · {rnd}회차: 자가검증 중 ({len(to_verify)}문항)")
                verdicts = self._verify(context, to_verify, req, prior + [_stem(q) for q in accepted])
                for c in to_verify:
                    defects[c["no"]] = _verdict_defects(verdicts.get(c["no"]))
            passed = 0
            for c in cands:
                d = defects[c["no"]]
                self.log.append({"batch": bi, "round": rnd, "topic": c["topic"], "type": c["type"],
                                 "passed": not d, "defects": d})
                if d:
                    feedback.setdefault(c["type"], []).extend(f"[{x['item']}] {x['reason']}" for x in d)
                else:
                    accepted.append({k: v for k, v in c.items() if k != "no"})
                    pending[c["type"]] -= 1
                    passed += 1
            self.progress(f"배치 {bi} · {rnd}회차: {passed}/{len(cands)}문항 통과")
        return accepted, {t: n for t, n in pending.items() if n > 0}

    @staticmethod
    def _select(raw: list[dict], pending: dict[str, int]) -> list[dict]:
        """요청 유형·개수를 넘는 문항은 버리고 후보에 임시 번호를 붙인다."""
        left = dict(pending)
        cands = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if left.get(t, 0) <= 0:
                continue
            left[t] -= 1
            c = {k: item[k] for k in ("topic", "type", "difficulty", "question", "options") if k in item}
            for k in ("topic", "question"):
                if isinstance(c.get(k), str):
                    c[k] = c[k].strip()
            if not c.get("options"):
                c.pop("options", None)
            c["no"] = len(cands) + 1
            c["user_answer"] = None
            cands.append(c)
        return cands

    @staticmethod
    def _local_defects(cands: list[dict], accepted: list[dict], prior: list[str]) -> dict[int, list[dict]]:
        """코드로 확인하는 항목: 서식(A1)과 완전 동일 문항 중복(B3)."""
        seen = {_norm(q["question"]) for q in accepted}
        out: dict[int, list[dict]] = {}
        for c in cands:
            d = [{"item": "A1", "reason": e} for e in schema.validate_question(c, expect_blank_answer=True)]
            key = _norm(c.get("question", ""))
            if key in seen:
                d.append({"item": "B3", "reason": "이미 통과한 문항과 질문이 동일함"})
            seen.add(key)
            out[c["no"]] = d
        return out

    # --- 전체 실행 ---------------------------------------------------------
    def run(self, req: GenRequest) -> Draft:
        context = skills.build_generation_context(self.skills_dir, req.cert)
        batches = plan_batches(req.counts)
        self.progress(f"총 {req.total()}문항을 {len(batches)}개 배치로 나누어 생성합니다.")
        accepted_all: list[dict] = []
        shortfall: dict[str, int] = {}
        for bi, batch in enumerate(batches, 1):
            prior = [_stem(q) for q in accepted_all]
            accepted, short = self._run_batch(bi, batch, req, context, prior)
            accepted_all.extend(accepted)
            for t, n in short.items():
                shortfall[t] = shortfall.get(t, 0) + n
        self.progress("토큰 사용: " + render.format_usage(self.usage))
        order = {t: i for i, t in enumerate(req.counts)}
        accepted_all.sort(key=lambda q: order[q["type"]])
        questions = []
        for no, q in enumerate(accepted_all, 1):
            q = dict(q, no=no, user_answer=None)
            if q["type"] == "빈칸 채우기형" and q.get("options"):
                q["options"] = random.sample(q["options"], len(q["options"]))  # 보기 순서로 정답을 유추하지 못하게 섞는다
            if q["type"] in req.points:
                q["points"] = req.points[q["type"]]
            questions.append(q)
        if questions:
            errors = schema.validate_questions(questions, expect_blank_answer=True)
            if errors:
                raise GenerationError("조립된 시험지가 스키마를 통과하지 못했습니다: " + "; ".join(errors))
        return Draft(req.cert, self.model, questions, shortfall, self.log, req.to_settings(), self.usage)


def save_draft(store, draft: Draft, *, accept_shortfall: bool = False) -> dict:
    """초안을 시험지로 저장한다. 문항이 모자라면 사용자가 명시적으로 수락해야 한다."""
    if not draft.questions:
        raise GenerationError("검증을 통과한 문항이 없어 저장할 수 없습니다.")
    if draft.shortfall and not accept_shortfall:
        raise GenerationError("문항이 모자랍니다. 부족한 채로 저장하려면 명시적으로 수락해야 합니다.")
    settings = dict(draft.settings, shortfall=draft.shortfall, usage=draft.usage)
    return store.create_exam(draft.cert, draft.questions, model=draft.model, settings=settings,
                             verification_log=draft.log)


def _stem(q: dict) -> str:
    return f"{q.get('topic', '')}: {q.get('question', '')[:40]}"


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def _verdict_defects(verdict: dict | None) -> list[dict]:
    """검증자 응답을 결함 목록으로 정리한다. 누락·모순된 응답은 통과로 취급하지 않는다."""
    if verdict is None:
        return [{"item": "A2", "reason": "검증자가 이 문항에 응답하지 않음"}]
    defects = [
        {"item": d["item"], "reason": str(d.get("reason", "")).strip() or "사유 없음"}
        for d in verdict.get("defects", [])
        if isinstance(d, dict) and d.get("item") in DEFECT_ITEMS
    ]
    if verdict.get("passed") is not True and not defects:
        defects = [{"item": "A2", "reason": "검증자가 사유 없이 불통과로 판정함"}]
    return defects
