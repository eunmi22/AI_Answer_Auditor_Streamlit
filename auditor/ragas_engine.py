"""Real RAGAS 0.4.4 integration. No simulated scores or silent substitutions.

- deterministic/non-LLM comparisons can run without an API key IF reference is present
- RAGAS LLM metrics require an independently selected RAGAS evaluator key
- GPT / Gemini rubric judges are orchestrated separately from this module

Docs: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

RAGAS_NON_LLM = ("Exact Match", "NonLLM String Similarity")
RAGAS_LLM = ("Faithfulness", "Factual Correctness", "Answer Relevancy", "Context Precision", "Context Recall")


class RagasDependencyError(RuntimeError):
    """RAGAS library not installed or incompatible."""


def selected_judges(gpt: bool, gemini: bool) -> List[str]:
    """Independent switches: [], ['GPT'], ['Gemini'], or both."""
    return [name for name, enabled in (("GPT", gpt), ("Gemini", gemini)) if enabled]


def ragas_metric_requirements(name: str) -> str:
    if name in RAGAS_NON_LLM:
        return "정답(reference_answer) 필요; LLM 호출 없음"
    if name == "Faithfulness":
        return "검색 근거 + RAGAS 평가 LLM 필요"
    if name == "Answer Relevancy":
        return "RAGAS 평가 LLM + 임베딩 API 필요"
    if name in {"Context Precision", "Context Recall"}:
        return "정답 + 검색 근거 + RAGAS 평가 LLM 필요"
    if name == "Factual Correctness":
        return "정답 + RAGAS 평가 LLM 필요"
    return "알 수 없는 지표"


def _row(metric: str, value: Optional[float] = None, *, reason: str = "", engine: str = "RAGAS") -> Dict[str, Any]:
    if value is not None:
        try:
            value = float(value)
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError
        except (ValueError, TypeError):
            return {"metric": metric, "status": "실패", "score": None, "reason": "유효하지 않은 수치가 반환됨", "engine": engine}
        value = round(value, 4)
        return {"metric": metric, "status": "완료", "score": value, "reason": reason, "engine": engine}
    return {"metric": metric, "status": "미실시", "score": None, "reason": reason, "engine": engine}


def _metric_value(result: Any) -> float:
    value = getattr(result, "value", None)
    if value is None:
        raise ValueError("RAGAS가 결과값을 반환하지 않았습니다")
    return float(value)


def _call_score(metric: Any, **kwargs: Any) -> float:
    # Current collections-based API. Do not use deprecated SingleTurnSample route.
    return _metric_value(metric.score(**kwargs))


def run_ragas(
    question: str, response: str, retrieved_contexts: List[str],
    *, reference: str = "", use_llm: bool = False, api_key: str = "",
    model: str = "gpt-4o-mini", embedding_model: str = "text-embedding-3-small",
    enabled_metrics: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Evaluate chosen metrics. Missing prerequisites => explicit 미실시, not 0 points.

    RAGAS LLM evaluation (when selected) uses OpenAI as *its own* evaluator, entirely
    independent of GPT/Gemini LLM-as-Judge selection. This API may incur charges.
    """
    chosen = list(enabled_metrics) if enabled_metrics is not None else list(RAGAS_NON_LLM + RAGAS_LLM)
    invalid = set(chosen) - set(RAGAS_NON_LLM + RAGAS_LLM)
    if invalid:
        raise ValueError(f"지원하지 않는 RAGAS 지표: {', '.join(sorted(invalid))}")
    if not response.strip():
        raise ValueError("평가대상 답변이 비어 있습니다")
    if not question.strip():
        raise ValueError("질문이 비어 있습니다")
    reference = reference.strip()
    contexts = [str(s).strip()[:1800] for s in retrieved_contexts if s is not None and str(s).strip()][:8]
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        import ragas
        from ragas.metrics import collections as metrics
        version = getattr(ragas, "__version__", "알 수 없음")
    except ImportError as e:
        return {
            "version": "설치되지 않음", "llm_enabled": use_llm, "llm_model": model if use_llm else "",
            "metrics": [_row(m, reason="ragas==0.4.4 패키지 설치 필요") for m in chosen],
            "warnings": [f"정식 RAGAS를 불러오지 못했습니다: {type(e).__name__}. pip install -r requirements.txt"],
        }

    for name in chosen:
        if name not in RAGAS_NON_LLM:
            continue
        if not reference:
            rows.append(_row(name, reason="검증된 정답(reference_answer)이 제공되지 않아 계산하지 않음"))
            continue
        try:
            if name == "Exact Match":
                value = _call_score(metrics.ExactMatch(), reference=reference, response=response)
            elif name == "NonLLM String Similarity":
                value = _call_score(metrics.NonLLMStringSimilarity(distance_measure=metrics.DistanceMeasure.LEVENSHTEIN), reference=reference, response=response)
            rows.append(_row(name, value, reason="문자열 유사도이며 사실의 진위를 증명하지 않음"))
        except Exception as e:
            rows.append({**_row(name, reason=f"{type(e).__name__}: 지표 계산 실패"), "status": "실패"})

    llm_requested = [m for m in chosen if m in RAGAS_LLM]
    if llm_requested and not use_llm:
        rows.extend(_row(m, reason="RAGAS LLM 지표 사용 안 함으로 설정됨") for m in llm_requested)
    elif llm_requested and not api_key:
        rows.extend(_row(m, reason="별도 RAGAS 평가용 OpenAI API 키가 없어 미실시") for m in llm_requested)
    elif llm_requested:
        try:
            from openai import AsyncOpenAI
            from ragas.llms import llm_factory
            client = AsyncOpenAI(api_key=api_key, timeout=50.0, max_retries=1)
            eval_llm = llm_factory(model, client=client)
        except Exception as e:
            warnings.append(f"RAGAS 평가 모델 초기화 실패: {type(e).__name__} (키/접근권한/SDK 호환성 확인)")
            rows.extend({**_row(m, reason="RAGAS 평가 모델을 초기화하지 못함"), "status": "실패"} for m in llm_requested)
        else:
            for name in llm_requested:
                if name in ("Factual Correctness", "Context Precision", "Context Recall") and not reference:
                    rows.append(_row(name, reason="정답(reference_answer)이 없어 미실시"))
                    continue
                if name in ("Faithfulness", "Context Precision", "Context Recall") and not contexts:
                    rows.append(_row(name, reason="검색된 근거 문서가 없어 미실시"))
                    continue
                try:
                    if name == "Faithfulness":
                        scorer = metrics.Faithfulness(llm=eval_llm)
                        value = _call_score(scorer, user_input=question, response=response, retrieved_contexts=contexts)
                    elif name == "Factual Correctness":
                        scorer = metrics.FactualCorrectness(llm=eval_llm)
                        value = _call_score(scorer, response=response, reference=reference)
                    elif name == "Answer Relevancy":
                        from ragas.embeddings.base import embedding_factory
                        embeddings = embedding_factory("openai", model=embedding_model, client=client)
                        scorer = metrics.AnswerRelevancy(llm=eval_llm, embeddings=embeddings)
                        value = _call_score(scorer, user_input=question, response=response)
                    elif name == "Context Precision":
                        scorer = metrics.ContextPrecision(llm=eval_llm)
                        value = _call_score(scorer, user_input=question, reference=reference, retrieved_contexts=contexts)
                    elif name == "Context Recall":
                        scorer = metrics.ContextRecall(llm=eval_llm)
                        value = _call_score(scorer, user_input=question, reference=reference, retrieved_contexts=contexts)
                    rows.append(_row(name, value, reason="정식 RAGAS LLM 지표; LLM 판단에 따라 변동 가능"))
                except Exception as e:
                    warnings.append(f"{name} 평가 중 오류: {type(e).__name__} (상세 정보 및 API 키는 화면에 표시하지 않음)")
                    rows.append({**_row(name, reason=f"{type(e).__name__}: 지표 계산 실패"), "status": "실패"})

    return {
        "version": version, "llm_enabled": bool(use_llm),
        "llm_model": model if use_llm else "", "metrics": rows, "warnings": warnings,
    }


def merge_assessment_status(ragas_result: Dict, judges: Dict) -> str:
    """Avoid fabricating an overall score when no metric has been computed."""
    good_ragas = sum(1 for x in ragas_result.get("metrics", []) if x.get("status") == "완료")
    good_judges = len(judges)
    if good_ragas and good_judges:
        return "RAGAS + LLM 평가 완료(일부 지표는 미실시일 수 있음)"
    if good_ragas:
        return "RAGAS 단독 평가(정량 항목만)"
    if good_judges:
        return "LLM-as-a-Judge 단독 평가"
    return "평가 보류: 실행 가능한 지표/심사모델 없음"
