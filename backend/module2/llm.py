"""모듈 2에서 모델을 호출하는 유일한 장소.

`PlanLLM`은 planner가 의존하는 인터페이스.
`ClaudePlanLLM`은 Claude API를 호출하고, 테스트는 같은 인터페이스를 구현한 가짜 LLM을 사용.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .prompts import PLAN_JSON_SCHEMA

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "medium"  # "low" | "medium" | "high" | "xhigh" | "max"
MAX_TOKENS = 64000
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class MissingAPIKey(ValueError):
    pass


def load_environment():
    """Read simple KEY=value settings without logging secrets or overriding the shell."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key not in {"ANTHROPIC_API_KEY", "MODULE2_MODEL", "MODULE2_EFFORT"}:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ.setdefault(key, value)


def api_key_configured():
    load_environment()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return bool(key and key not in {"sk-ant-...", "YOUR_API_KEY", "your_api_key_here"})


@dataclass
class LLMResult:
    plan: dict[str, Any] | None          # 파싱한 계획 JSON, 쓸 수 없으면 None
    assistant_content: Any               # 대화에 assistant 턴으로 추가되는 내용
    error: str | None = None             # "refusal" | "max_tokens" | "invalid_json" | None
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class PlanLLM(Protocol):
    def complete(self, system: str, messages: list[dict[str, Any]]) -> LLMResult: ...


class ClaudePlanLLM:
    """Claude API client. Model/effort configurable via MODULE2_MODEL / MODULE2_EFFORT."""

    def __init__(self, model: str | None = None, effort: str | None = None, client: Any = None):
        load_environment()
        self.model = model or os.environ.get("MODULE2_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("MODULE2_EFFORT", DEFAULT_EFFORT)
        self.client = client

    def complete(self, system: str, messages: list[dict[str, Any]]) -> LLMResult:
        if self.client is None:
            if not api_key_configured():
                raise MissingAPIKey("repository/.env의 ANTHROPIC_API_KEY를 설정한 뒤 다시 요청하세요.")
            import anthropic
            self.client = anthropic.Anthropic(timeout=180.0, max_retries=0)
        with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": PLAN_JSON_SCHEMA},
            },
        ) as stream:
            response = stream.get_final_message()

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", None),
        }
        base = {"assistant_content": response.content, "model": response.model, "usage": usage}

        if response.stop_reason == "refusal":
            return LLMResult(plan=None, error="refusal", **base)
        if response.stop_reason == "max_tokens":
            return LLMResult(plan=None, error="max_tokens", **base)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            plan = json.loads(text)
        except json.JSONDecodeError:
            return LLMResult(plan=None, error="invalid_json", **base)
        return LLMResult(plan=plan, **base)
