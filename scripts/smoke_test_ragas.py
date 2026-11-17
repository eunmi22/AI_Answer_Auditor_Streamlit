"""Run after installing requirements on a real network-connected environment.
This test consumes NO API quota. Run from project root:
    python scripts/smoke_test_ragas.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auditor.ragas_engine import run_ragas

result = run_ragas(
    question="운영 로그는 몇 년 보관하나요?",
    response="운영 로그는 3년 보관합니다.",
    retrieved_contexts=["운영 로그 보관기간은 3년이다."],
    reference="운영 로그는 3년 보관합니다.",
    use_llm=False,
    enabled_metrics=["Exact Match", "NonLLM String Similarity"],
)
for metric in result["metrics"]:
    print(f"{metric['metric']}: {metric['status']} / {metric['score']} / {metric['reason']}")
if any(m['status'] != '완료' for m in result['metrics']):
    raise SystemExit("RAGAS smoke test failed. Verify install and API compatibility.")
print("RAGAS library smoke test passed (no API calls).")
