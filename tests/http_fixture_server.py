"""Browser test process only: real HTTP service with scripted, unpaid LLM output."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from test_system import neutral_plan
from module2.tests.test_planner import ScriptedLLM
from module2.service import PlanService
from module2.server import create_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--failed", action="store_true")
    args = parser.parse_args()
    def factory():
        plan = neutral_plan()
        if args.failed:
            plan["rows"][0]["exercise_id"] = "EX99"
        return ScriptedLLM([plan, plan, plan])
    server = create_server(args.port, PlanService(factory))
    print("TEST FIXTURE: Claude responses are substituted", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
