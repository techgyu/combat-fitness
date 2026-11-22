"""Small loopback demo HTTP server helpers (standard library only)."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
try:
    from .module1_core import DomainError, decode_json
except ImportError:
    from module1_core import DomainError, decode_json


class JsonHandler(BaseHTTPRequestHandler):
    server_version = "FitnessDemo/1.0"
    max_body = 1_000_000

    def log_message(self, fmt, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def send_bytes(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def error(self, status, code, message, details=None):
        self.send_json(status, {"error": {"code": code, "message": message, "details": details or []}})

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise DomainError("content_type", "Content-Type: application/json이 필요합니다.")
        if self.headers.get("Transfer-Encoding"):
            raise DomainError("body_format", "Content-Length를 사용하는 JSON 요청이 필요합니다.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise DomainError("body_format", "올바른 Content-Length가 필요합니다.") from None
        if not 0 < size <= self.max_body:
            raise DomainError("body_size", "요청 본문이 비었거나 허용 크기를 초과했습니다.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise DomainError("body_format", "요청 본문이 완전히 전달되지 않았습니다.")
        try:
            body = decode_json(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise DomainError("invalid_json", "올바른 JSON이 필요합니다. 중복 키와 NaN은 허용하지 않습니다.") from None
        if not isinstance(body, dict):
            raise DomainError("invalid_json", "JSON 객체를 전달하세요.")
        return body

    def check_origin(self):
        port = self.server.server_port
        allowed = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if self.headers.get("Host", "") not in allowed:
            raise DomainError("forbidden_origin", "허용된 로컬 주소로 접속하세요.")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + h for h in allowed}:
            raise DomainError("forbidden_origin", "다른 웹사이트에서의 요청은 허용하지 않습니다.")

    def dispatch(self, method):
        try:
            self.check_origin()
            self.route(method, urlsplit(self.path))
        except DomainError as exc:
            statuses = {"not_found": 404, "duplicate_id": 409, "forbidden_origin": 403,
                        "content_type": 415, "body_size": 413, "invalid_json": 400,
                        "body_format": 400, "module2_timeout": 504}
            status = statuses.get(exc.code, 502 if exc.code.startswith("module2_") else 422)
            self.error(status, exc.code, str(exc), exc.details)
        except Exception:
            import traceback
            traceback.print_exc()
            self.error(500, "internal_error", "서버 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_OPTIONS(self):
        self.error(405, "method_not_allowed", "같은 출처의 웹 화면을 사용하세요.")


def serve(handler, host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), handler)
