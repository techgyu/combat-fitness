"""Windows desktop launcher, also used as the frozen application entry point."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.request

ROOT = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
if not FROZEN:
    sys.path.insert(0, str(ROOT / "backend"))


def user_data_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CombatFitness"



class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect_key(value: bytes, decrypt=False) -> bytes:
    """Windows DPAPI binds the saved credential to the current user account."""
    if os.name != "nt":
        raise OSError("API key storage requires Windows.")
    buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    name = "CryptUnprotectData" if decrypt else "CryptProtectData"
    function = getattr(crypt, name)
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def save_key(directory: Path, key: str):
    directory.mkdir(parents=True, exist_ok=True)
    encrypted = protect_key(key.encode("utf-8"))
    temporary = directory / "api-key.tmp"
    temporary.write_bytes(encrypted)
    temporary.replace(directory / "api-key.bin")


def restore_key(directory: Path):
    saved = directory / "api-key.bin"
    if saved.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = protect_key(saved.read_bytes(), decrypt=True).decode("utf-8")


class ServerPair:
    def __init__(self, directory: Path, web_port=8000, module2_port=8001):
        self.directory = Path(directory)
        self.web_port, self.module2_port = web_port, module2_port
        self.servers = []
        self.threads = []
        self.url = ""

    @staticmethod
    def bind(factory, preferred):
        try:
            return factory(preferred)
        except OSError as exc:
            # Only occupied ports get a fallback; all other startup errors remain visible.
            if preferred and (getattr(exc, "winerror", None) == 10048 or exc.errno in (48, 98, 10048)):
                return factory(0)
            raise

    def start(self):
        from module1 import server as module1
        from module2 import server as module2
        from module2 import llm

        # Frozen package resources are read-only; writable state stays in LocalAppData.
        if FROZEN:
            module1.REPO = Path(sys._MEIPASS)
        llm.ENV_FILE = self.directory / ".env"
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            second = self.bind(lambda port: module2.create_server(port=port), self.module2_port)
            self.servers.append(second)
            self.module2_port = second.server_port
            first = self.bind(lambda port: module1.create_server(
                db_path=self.directory / "soldiers.sqlite3", port=port,
                module2_url=f"http://127.0.0.1:{second.server_port}"), self.web_port)
            self.servers.append(first)
            self.web_port = first.server_port
            for server in self.servers:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.threads.append(thread)
            self.url = f"http://127.0.0.1:{first.server_port}"
            return self.url
        except Exception:
            self.stop()
            raise

    def stop(self):
        for server, thread in zip(self.servers, self.threads):
            if thread.is_alive():
                server.shutdown()
        for server in self.servers:
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.servers.clear()
        self.threads.clear()


def offline_self_test(report: Path):
    """Exercise the shipped executable without a Python installation or paid API calls."""
    import ssl
    import anthropic
    import certifi
    from desktop_ui import LauncherWindow

    os.environ.pop("ANTHROPIC_API_KEY", None)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(name, None)
    # Ensure the bundled TLS roots and SDK can be initialized.
    ssl.create_default_context(cafile=certifi.where())
    client = anthropic.Anthropic(api_key="portable-self-test-placeholder")
    client.close()
    with tempfile.TemporaryDirectory(prefix="combat-fitness-check-") as folder:
        directory = Path(folder)
        window = LauncherWindow(directory, ServerPair(directory, 0, 0), lambda key: "",
                                "", start_servers=False)
        assert window.handle
        window.close()
        key_storage = "passed"
        try:
            save_key(directory, "test-key-not-a-credential")
            restore_key(directory)
            assert os.environ.pop("ANTHROPIC_API_KEY") == "test-key-not-a-credential"
        except OSError as exc:
            # Sandboxed/service accounts can lack a loaded Windows profile.
            if getattr(exc, "winerror", None) not in (2, 1312):
                raise
            key_storage = "unavailable_windows_profile"
        servers = ServerPair(directory, web_port=0, module2_port=0)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(servers.url + path, timeout=10) as response:
                return response.read()

        try:
            servers.start()
            assert b"<html" in get("/").lower()
            assert len(get("/app.js")) > 100
            assert len(get("/styles.css")) > 100
            assert json.loads(get("/api/openapi.json"))["openapi"]
            health = json.loads(get("/api/v1/module2/health"))
            assert health["service"] == "module2" and not health["generation_ready"]
            listing = json.loads(get("/api/v1/soldiers"))
            assert listing["total"] == 1000
            soldier = json.loads(get("/api/v1/soldiers/26-00000001"))
            assert len(soldier["result"]["difference_matrix"][0]) == 4
            record = {"soldier_id": "22-88888888", "age": 22, "height_cm": 178,
                      "weight_kg": 75, "pushups_2min": 40, "situps_2min": 50,
                      "run_3km_time": "16:00", "sex": "male", "role": "infantry_rifleman",
                      "is_synthetic": True, "combat_load_kg": 15}
            request = urllib.request.Request(servers.url + "/api/v1/soldiers",
                data=json.dumps(record).encode(), headers={"Content-Type": "application/json"})
            with opener.open(request, timeout=10) as response:
                created = json.load(response)
            assert created["result"]["difference_matrix"] == [[24, 28, -148, 0]]
            assert json.loads(get("/api/v1/soldiers"))["total"] == 1001
        finally:
            servers.stop()
        # Reopening must preserve records instead of replacing the database with the seed.
        try:
            servers.start()
            assert json.loads(get("/api/v1/soldiers"))["total"] == 1001
        finally:
            servers.stop()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"status": "passed", "frozen": FROZEN,
        "checks": ["native_windows_ui", "tls_certificates", "anthropic_sdk",
                   "web_assets", "module1_api", "module2_health", "seed_1000",
                   "registration_and_calculation", "database_persistence"],
        "encrypted_key_storage": key_storage,
        "external_api_called": False}, indent=2), encoding="utf-8")


def run_gui():
    from desktop_ui import LauncherWindow
    directory = user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=directory / "launcher.log", level=logging.ERROR,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    log_stream = None
    if sys.stderr is None:
        log_stream = (directory / "server.log").open("a", encoding="utf-8", buffering=1)
        sys.stderr = log_stream
    notice = "API 키를 저장하면 운동 계획을 생성할 수 있습니다."
    try:
        restore_key(directory)
        if os.environ.get("ANTHROPIC_API_KEY"):
            notice = "API 키가 설정되어 있습니다. 변경할 때만 새 키를 입력하세요."
    except (OSError, UnicodeError):
        notice = "저장된 키를 읽지 못했습니다. API 키를 다시 입력하세요."

    def store(key):
        try:
            save_key(directory, key)
            result = "키를 저장했습니다. 웹 화면에서 계획 생성을 요청하세요."
        except OSError:
            result = "암호화 저장을 사용할 수 없어 이번 실행에서만 키를 사용합니다."
        os.environ["ANTHROPIC_API_KEY"] = key
        return result

    window = LauncherWindow(directory, ServerPair(directory), store, notice)
    try:
        window.run()
    finally:
        window.close()
        if log_stream:
            log_stream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    if args.self_test:
        try:
            offline_self_test(args.self_test)
        except Exception:
            import traceback
            args.self_test.parent.mkdir(parents=True, exist_ok=True)
            args.self_test.write_text(json.dumps({"status": "failed", "traceback": traceback.format_exc()},
                                                indent=2), encoding="utf-8")
            return 1
        return 0
    try:
        run_gui()
    except Exception as exc:
        logging.exception("Desktop launcher failed")
        ctypes.windll.user32.MessageBoxW(None, str(exc), "프로그램 실행 오류", 0x10)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
