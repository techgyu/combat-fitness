"""Shared application service for the standard-library and FastAPI servers."""
import uuid

from module1.module1_core import CONTRACT_VERSION, DomainError, Module1
from .bridge import planner_payload
from .catalog import load_catalog
from .contract import ContractError, validate_contract
from .llm import ClaudePlanLLM, MissingAPIKey, api_key_configured, DEFAULT_MODEL
from .planner import run_planner


class ServiceError(Exception):
    def __init__(self, http_status, code, message, details=None):
        super().__init__(message)
        self.http_status, self.code, self.details = http_status, code, details or []

    def body(self):
        return {"status": self.code, "error": {"code": self.code, "message": str(self), "details": self.details}}


class PlanService:
    def __init__(self, llm_factory=None, catalog=None):
        self.engine = Module1()
        self.catalog = catalog or load_catalog()
        self.llm_factory = llm_factory or ClaudePlanLLM

    def health(self):
        import os
        ready = api_key_configured()
        return {"status": "ok", "service": "module2", "mode": "real",
                "contract_version": CONTRACT_VERSION, "versions": self.catalog.versions,
                "generation_ready": ready, "model": os.environ.get("MODULE2_MODEL", DEFAULT_MODEL),
                "message": "계획 생성 준비 완료" if ready else "Claude API 키 설정이 필요합니다."}

    def generate(self, raw, llm=None):
        # Reject invalid inputs before constructing an external API client.
        try:
            validate_contract(raw, self.catalog)
        except ContractError as exc:
            raise ServiceError(422, "input_error", "계획 입력값을 확인하세요.",
                               [{"field": "input", "message": e} for e in exc.issues]) from None
        try:
            return run_planner(raw, llm or self.llm_factory(), self.catalog)
        except MissingAPIKey as exc:
            raise ServiceError(503, "api_key_missing", str(exc)) from None
        except ImportError:
            raise ServiceError(503, "dependency_missing", "Claude 호출 패키지가 없습니다. setup.ps1을 실행하세요.") from None
        except Exception as exc:
            # Never forward provider exception bodies or credentials to the browser.
            try:
                import anthropic
            except ImportError:
                raise exc
            if isinstance(exc, anthropic.AuthenticationError):
                raise ServiceError(502, "llm_auth_error", "Claude API 키가 유효하지 않습니다. 설정된 API 키를 확인하세요.") from None
            if isinstance(exc, anthropic.RateLimitError):
                raise ServiceError(503, "llm_rate_limited", "Claude API 호출 한도에 도달했습니다. 잠시 후 다시 요청하세요.") from None
            if isinstance(exc, anthropic.APITimeoutError):
                raise ServiceError(504, "llm_timeout", "Claude 응답 시간이 초과되었습니다. 자동으로 재요청하지 않습니다.") from None
            if isinstance(exc, anthropic.APIConnectionError):
                raise ServiceError(503, "llm_unreachable", "Claude API에 연결하지 못했습니다.") from None
            if isinstance(exc, anthropic.APIStatusError):
                raise ServiceError(502, "llm_api_error", f"Claude API 오류 ({exc.status_code}). 키의 결제·크레딧 상태와 모델 설정을 확인하세요.") from None
            raise

    def submit(self, envelope, llm=None):
        try:
            raw = planner_payload(envelope, self.engine)
        except DomainError as exc:
            raise ServiceError(422, "input_error", str(exc)) from None
        result = self.generate(raw, llm)
        return {"contract_version": CONTRACT_VERSION, "request_id": envelope["request_id"],
                "receipt_id": str(uuid.uuid4()), "status": "accepted", "mode": "real",
                "generation_status": result["status"], "plan": result["plan"], "result": result,
                "assumptions": ["보병 소총수의 합성 사례입니다.",
                                "개인 장비·제한사항은 수집되지 않았으며, 운동표의 시연용 조건을 사용합니다."],
                "resources_sha256": envelope["module1_result"]["resources_sha256"]}
