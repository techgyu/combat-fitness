"""실제 Claude API로 모듈 2 루프 전체를 한 번 실행.

사용법: .venv/bin/python -m module2.run_example [output.json]   (backend/에서 실행하거나 PYTHONPATH=backend 지정)
입력은 PROJECT_SPEC 1.5 예시 장병을 사용.
"""
from __future__ import annotations

import json
import sys

from .catalog import load_catalog
from .llm import ClaudePlanLLM
from .planner import run_planner
from .tests.fixtures import SPEC_PAYLOAD


def main() -> None:
    catalog = load_catalog()
    llm = ClaudePlanLLM()
    result = run_planner(SPEC_PAYLOAD, llm, catalog)

    print(f"model={llm.model} effort={llm.effort}")
    print(f"status={result['status']} stop_reason={result.get('stop_reason')} "
          f"revisions_used={result.get('revisions_used')}")
    for h in result.get("history", []):
        print(f"  attempt {h['attempt']} ({h['kind']}): passed={h['passed']} "
              f"violations={h.get('violation_count')} error={h.get('error')} usage={h.get('usage')}")
        for v in h.get("violations", [])[:10]:
            print(f"    - [{v['check']}] week={v.get('week')} {v.get('exercise_id')} {v.get('field')}: "
                  f"{v['reason']} (allowed={v.get('allowed')}, actual={v.get('actual')})")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"saved: {sys.argv[1]}")


if __name__ == "__main__":
    main()
