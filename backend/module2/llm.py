"""모듈 2에서 모델을 호출하는 유일한 장소 (CLAUDE.md 규칙 9).

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
        import anthropic
        from dotenv import load_dotenv

        # 실행 명령어에 넣은 환경변수가 .env보다 우선함 (override=False).
        load_dotenv(ENV_FILE, override=False)
        self.model = model or os.environ.get("MODULE2_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("MODULE2_EFFORT", DEFAULT_EFFORT)
        self.client = client or anthropic.Anthropic()

    def complete(self, system: str, messages: list[dict[str, Any]]) -> LLMResult:
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
