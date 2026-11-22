"""Web -> Module 1 -> Module 2 demo API. Run python server.py."""
import argparse
import os
import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote
from http_support import JsonHandler, serve
from module1_core import ROOT, CONTRACT_VERSION, DomainError, Module1
from module2_client import Module2Client
from storage import SoldierStore

REPO = ROOT.parent.parent


def create_server(db_path=None, seed_path=None, module2_url="http://127.0.0.1:8001",
                  host="127.0.0.1", port=8000, timeout=600):
    engine = Module1()
    store = SoldierStore(db_path or ROOT / "data" / "soldiers.sqlite3")
    store.seed_once(seed_path or ROOT / "data" / "synthetic_soldiers.json")
    client = Module2Client(module2_url, timeout)

    class Handler(JsonHandler):
        def route(self, method, url):
            path = url.path
            if method == "GET":
                static = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                          "/styles.css": ("styles.css", "text/css; charset=utf-8")}
                if path in static:
                    name, kind = static[path]
                    return self.send_bytes(200, (REPO / "frontend" / name).read_bytes(), kind)
                if path == "/api/openapi.json":
                    return self.send_bytes(200, (REPO / "docs" / "openapi.json").read_bytes(), "application/json; charset=utf-8")
                if path == "/api/v1/health":
                    return self.send_json(200, {"status": "ok", "service": "module1",
                                                "contract_version": CONTRACT_VERSION,
                                                "module2_base_url": client.base_url})
                if path == "/api/v1/resources":
                    return self.send_json(200, engine.resources)
                if path == "/api/v1/module2/health":
                    return self.send_json(200, client.health())
                if path == "/api/v1/soldiers":
                    params = parse_qs(url.query)
                    try:
                        page = int(params.get("page", ["1"])[0])
                        size = int(params.get("page_size", ["20"])[0])
                        if not (1 <= page <= 100000 and 1 <= size <= 100):
                            raise ValueError()
                    except ValueError:
                        raise DomainError("pagination", "page는 1 이상, page_size는 1~100 정수여야 합니다.") from None
                    source = params.get("source", [""])[0]
                    if source not in ("", "synthetic", "web"):
                        raise DomainError("source", "source는 synthetic 또는 web이어야 합니다.")
                    return self.send_json(200, store.list(page, size, params.get("q", [""])[0], source))
                match = re.fullmatch(r"/api/v1/soldiers/([0-9]{2}-[0-9]{8})", unquote(path))
                if match:
                    row = store.get(match[1])
                    result, report = engine.evaluate(row)
                    return self.send_json(200, {"record": row, "result": result, "warnings": report["warnings"],
                                                "latest_plan": store.latest_plan(row["soldier_id"])})
            if method == "POST":
                body = self.read_json()
                if path in ("/api/v1/soldiers", "/api/v1/evaluate"):
                    raw = dict(body)
                    if not isinstance(raw.get("soldier_id"), str) or not re.fullmatch(r"[0-9]{2}-[0-9]{8}", raw["soldier_id"]):
                        raise DomainError("soldier_id", "군번은 26-00000001처럼 연도 2자리-숫자 8자리여야 합니다.")
                    result, report = engine.evaluate(raw)
                    row = report["records"][0]
                    if path == "/api/v1/soldiers":
                        row = store.add(row)
                    return self.send_json(201 if path.endswith("/soldiers") else 200,
                                          {"record": row, "result": result, "warnings": report["warnings"]})
                match = re.fullmatch(r"/api/v1/soldiers/([0-9]{2}-[0-9]{8})/module2", unquote(path))
                if match:
                    if body:
                        raise DomainError("unexpected_fields", "전송 요청 본문은 {}로 지정하세요. DB의 검증된 데이터를 사용합니다.")
                    row = store.get(match[1])
                    payload, _ = engine.evaluate(row)
                    request_id = str(uuid.uuid4())
                    envelope = engine.envelope(payload, request_id)
                    try:
                        response = client.submit(envelope)
                    except DomainError as exc:
                        store.log_delivery(request_id, row["soldier_id"], "failed",
                                           {"code": exc.code, "message": str(exc)})
                        raise
                    store.log_delivery(request_id, row["soldier_id"], "accepted", response)
                    return self.send_json(200, {"transport_status": "accepted", "module2_response": response})
            raise DomainError("not_found", "요청한 경로가 없습니다.")

    server = serve(Handler, host, port)
    server.store, server.engine = store, engine
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "soldiers.sqlite3")
    parser.add_argument("--seed-file", type=Path, default=ROOT / "data" / "synthetic_soldiers.json")
    parser.add_argument("--module2-url", default=os.environ.get("MODULE2_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--module2-timeout", type=float, default=600)
    args = parser.parse_args()
    server = create_server(args.db, args.seed_file, args.module2_url, port=args.port, timeout=args.module2_timeout)
    print(f"Web + Module 1: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Module 2 target: {args.module2_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
