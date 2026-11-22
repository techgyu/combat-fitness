"""Local module-2 server; same service as the optional FastAPI entry point."""
import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module1.http_support import JsonHandler, serve
from module1.module1_core import DomainError
from module2.service import PlanService, ServiceError


def create_server(port=8001, service=None):
    service = service or PlanService()

    class Handler(JsonHandler):
        def route(self, method, url):
            try:
                if method == "GET" and url.path == "/health":
                    return self.send_json(200, service.health())
                if method == "POST" and url.path in ("/api/v1/plans", "/plan"):
                    body = self.read_json()
                    result = service.submit(body) if url.path == "/api/v1/plans" else service.generate(body)
                    return self.send_json(200, result)
                raise DomainError("not_found", "요청한 경로가 없습니다.")
            except ServiceError as exc:
                self.send_json(exc.http_status, exc.body())

    return serve(Handler, "127.0.0.1", port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = create_server(args.port)
    print(f"Module 2: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
