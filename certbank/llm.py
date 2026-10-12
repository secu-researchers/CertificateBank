"""Claude 호출 모듈. 구조화 출력(JSON 스키마)으로 응답을 받아 dict로 반환한다.

API 키는 호출자가 인자로 넘기며 이 모듈은 저장하거나 기록하지 않는다.
"""
import json
from dataclasses import dataclass, field
from typing import Any

import anthropic


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    supports_effort: bool = True


MODELS: tuple[ModelOption, ...] = (
    ModelOption("claude-sonnet-5-5", "Claude Sonnet 5.5 (기본)"),
    ModelOption("claude-opus-5-5", "Claude Opus 5.5 (고성능)"),
    ModelOption("claude-fable-5-1", "Claude Fable 5.1 (최고 성능, 고가)"),
    ModelOption("claude-haiku-4-5", "Claude Haiku 4.5 (최저가)", supports_effort=False),
)
MODEL_IDS = tuple(m.id for m in MODELS)
DEFAULT_MODEL = "claude-sonnet-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# 정책상 거절된 요청을 서버가 다른 모델로 다시 실행하게 한다. 보안 주제는 거절 분류기에 걸리기 쉽다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
KEY_CHECK_MODEL = "claude-haiku-4-5"


class LLMError(Exception):
    """사용자에게 보여 줄 한국어 메시지를 담는 오류. kind로 원인을 구분한다."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class LLMResult:
    data: Any
    model: str
    request_id: str | None
    usage: dict = field(default_factory=dict)


def _option(model: str) -> ModelOption:
    for m in MODELS:
        if m.id == model:
            return m
    raise LLMError("bad_model", f"지원하지 않는 모델입니다: {model}")


def _translate(exc: Exception) -> LLMError:
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("auth", "API 키가 올바르지 않습니다. 설정에서 다시 입력하세요.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMError("permission", "이 API 키에는 해당 모델 또는 기능에 대한 권한이 없습니다.")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("rate_limit", "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError("not_found", "모델 또는 엔드포인트를 찾을 수 없습니다.")
    if isinstance(exc, anthropic.BadRequestError):
        return LLMError("bad_request", f"요청이 거부되었습니다: {getattr(exc, 'message', exc)}")
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMError("timeout", "응답 시간이 초과되었습니다. 다시 시도하세요.")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("network", "네트워크 연결에 실패했습니다.")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return LLMError("server", f"서버 오류({exc.status_code})입니다. 잠시 후 다시 시도하세요.")
        return LLMError("api", f"API 오류({exc.status_code}): {getattr(exc, 'message', exc)}")
    return LLMError("unknown", f"알 수 없는 오류: {exc}")


def build_request(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict,
    max_tokens: int,
    effort: str,
    use_fallbacks: bool,
    cached_context: str | None = None,
) -> dict:
    """messages.stream에 넘길 인자를 만든다.

    cached_context는 호출 간에 바뀌지 않는 SKILL 본문이다. system의 첫 블록으로 두고 캐시 중단점을 걸어
    같은 컨텍스트를 쓰는 후속 호출(재생성, 검증, 다음 배치)이 캐시에서 읽게 한다. 호출마다 달라지는
    지침(system)은 그 뒤 블록에 두어 캐시 접두부를 깨지 않는다.
    """
    option = _option(model)
    if effort not in EFFORTS:
        raise LLMError("bad_effort", f"지원하지 않는 effort입니다: {effort}")
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if cached_context:
        request["system"] = [
            {"type": "text", "text": cached_context, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system},
        ]
    if option.supports_effort:
        output_config["effort"] = effort
        request["thinking"] = {"type": "adaptive"}
    request["output_config"] = output_config
    if use_fallbacks:
        request["betas"] = [FALLBACK_BETA]
        request["extra_body"] = {"fallbacks": "default"}
    return request


def _usage_dict(usage: Any) -> dict:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {k: getattr(usage, k, None) for k in keys if getattr(usage, k, None) is not None}


def call_json(
    api_key: str,
    *,
    model: str,
    system: str,
    user: str,
    schema: dict,
    max_tokens: int = 16000,
    effort: str = "high",
    use_fallbacks: bool = True,
    cached_context: str | None = None,
    client: Any = None,
) -> LLMResult:
    """구조화 출력으로 호출해 JSON을 파싱해 반환한다. 파싱 후 스키마 검증은 호출자가 한다."""
    request = build_request(
        model=model,
        system=system,
        user=user,
        schema=schema,
        max_tokens=max_tokens,
        effort=effort,
        use_fallbacks=use_fallbacks,
        cached_context=cached_context,
    )
    try:
        api = client or anthropic.Anthropic(api_key=api_key)
        with api.beta.messages.stream(**request) as stream:
            message = stream.get_final_message()
    except LLMError:
        raise
    except Exception as exc:  # SDK 예외를 한국어 LLMError로 변환한다
        raise _translate(exc) from None

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None)
        suffix = f" (분류: {category})" if category else ""
        raise LLMError("refusal", f"모델이 요청을 거절했습니다{suffix}. 주제나 표현을 바꿔 다시 시도하세요.")
    if stop_reason == "max_tokens":
        raise LLMError("max_tokens", "출력이 최대 길이에 도달해 잘렸습니다. 문항 수를 줄여 다시 시도하세요.")

    text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise LLMError("empty", "모델 응답에 텍스트가 없습니다.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise LLMError("invalid_json", "모델 응답이 올바른 JSON이 아닙니다.") from None
    return LLMResult(
        data=data,
        model=getattr(message, "model", model),
        request_id=getattr(message, "_request_id", None),
        usage=_usage_dict(getattr(message, "usage", None)),
    )


def check_key(api_key: str, *, client: Any = None) -> None:
    """토큰 수 계산 호출로 키를 검증한다. 생성 비용이 들지 않는다."""
    try:
        api = client or anthropic.Anthropic(api_key=api_key)
        api.messages.count_tokens(
            model=KEY_CHECK_MODEL, messages=[{"role": "user", "content": "ping"}]
        )
    except Exception as exc:
        raise _translate(exc) from None
