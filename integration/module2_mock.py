"""Contract receiver only. Does NOT produce an exercise plan."""
import argparse
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "module1"))
from http_support import JsonHandler, serve
from module1_core import CONTRACT_VERSION, DomainError, verify_envelope


def create_mock(port=8001):
    class Handler(JsonHandler):
        def route(self, method, url):
            if method == "GET" and url.path == "/health":
                return self.send_json(200, {"status": "ok", "service": "module2",
                                            "mode": "mock", "contract_version": CONTRACT_VERSION})
            if method == "POST" and url.path == "/api/v1/plans":
                body = verify_envelope(self.read_json())
                return self.send_json(202, {
                    "contract_version": CONTRACT_VERSION, "request_id": body["request_id"],
                    "receipt_id": "mock-" + str(uuid.uuid4()), "status": "accepted",
                    "mode": "mock", "plan": None,
                    "message": "통신 및 입력 계약 검증 완료. 모의 서버는 운동 계획을 생성하지 않습니다."})
            raise DomainError("not_found", "요청한 경로가 없습니다.")
    return serve(Handler, port=port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = create_mock(args.port)
    print(f"Module 2 MOCK: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
