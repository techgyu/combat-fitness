"""Only HTTP transport and response checking; no exercise-plan generation."""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
if __package__:
    from .module1_core import CONTRACT_VERSION, DomainError, decode_json
else:
    from module1_core import CONTRACT_VERSION, DomainError, decode_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Module2Client:
    def __init__(self, base_url, timeout=600):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("MODULE2_BASE_URL must be an http(s) server URL without credentials/query.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, body=None, timeout=None):
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=encoded,
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout if timeout is None else timeout) as response:
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise DomainError("module2_invalid_response", "모듈 2 응답 크기가 허용 범위를 초과했습니다.")
                if response.headers.get_content_type() != "application/json":
                    raise DomainError("module2_invalid_response", "모듈 2가 JSON 응답을 반환하지 않았습니다.")
                result = decode_json(data.decode("utf-8"))
                if not isinstance(result, dict):
                    raise DomainError("module2_invalid_response", "모듈 2 응답은 JSON 객체여야 합니다.")
                return result
        except urllib.error.HTTPError as exc:
            try:
                error = decode_json(exc.read(1_000_000).decode("utf-8")).get("error", {})
            except (ValueError, UnicodeError, AttributeError):
                error = {}
            known = {"api_key_missing", "dependency_missing", "llm_auth_error", "llm_rate_limited",
                     "llm_timeout", "llm_unreachable", "llm_api_error", "input_error"}
            if error.get("code") in known:
                raise DomainError("module2_" + error["code"], str(error.get("message", "모듈 2 요청 실패")), error.get("details", [])) from None
            raise DomainError("module2_http_error", f"모듈 2가 HTTP {exc.code} 오류를 반환했습니다.") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise DomainError("module2_timeout", "모듈 2 응답 시간이 초과되었습니다.") from exc
        except urllib.error.URLError as exc:
            code = "module2_timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "module2_unavailable"
            raise DomainError(code, "모듈 2에 연결하지 못했습니다. 서버 주소와 실행 상태를 확인하세요.") from exc
        except (ValueError, UnicodeError) as exc:
            raise DomainError("module2_invalid_response", "모듈 2 응답 JSON을 읽을 수 없습니다.") from exc

    def health(self):
        result = self.request("/health", timeout=min(5, self.timeout))
        if result.get("status") != "ok" or result.get("contract_version") != CONTRACT_VERSION or result.get("mode") not in ("mock", "real"):
            raise DomainError("module2_invalid_response", "모듈 2 상태 또는 계약 버전이 일치하지 않습니다.")
        return result

    def submit(self, envelope):
        result = self.request("/api/v1/plans", envelope)
        if (result.get("contract_version") != CONTRACT_VERSION
                or result.get("request_id") != envelope["request_id"]
                or result.get("status") != "accepted"
                or result.get("mode") not in ("mock", "real")
                or not isinstance(result.get("receipt_id"), str) or not result["receipt_id"]):
            raise DomainError("module2_invalid_response", "모듈 2의 접수 응답이 통신 규격과 일치하지 않습니다.")
        if result["mode"] == "real":
            plan_result = result.get("result")
            if (not isinstance(plan_result, dict)
                    or plan_result.get("status") not in ("passed", "failed")
                    or not isinstance(plan_result.get("plan"), list)
                    or result.get("generation_status") != plan_result.get("status")
                    or result.get("resources_sha256") != envelope["module1_result"]["resources_sha256"]):
                raise DomainError("module2_invalid_response", "모듈 2의 계획 결과 형식이 일치하지 않습니다.")
            if plan_result["status"] == "passed" and (
                    not plan_result["plan"] or not isinstance(plan_result.get("validation"), dict)
                    or plan_result["validation"].get("passed") is not True):
                raise DomainError("module2_invalid_response", "계획과 검증 통과 상태가 일치하지 않습니다.")
        return result
