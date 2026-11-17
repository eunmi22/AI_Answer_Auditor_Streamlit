# RAGAS + 선택형 LLM 심사 고도화 요약

## 목표

질문·답변·검색 근거 및 검증된 기준답변을 입력받아 **RAGAS 메트릭**과 **선택한 GPT/Gemini LLM-as-a-Judge 심사**를 독립적으로 실행하는 금융 AI 평가 지원도구입니다.

## 소스 위치

- `auditor/ragas_engine.py`: **정식 RAGAS collections API 통합**. `ragas==0.4.4`가 없으면 명시적 미실시 처리.
- `auditor/evaluation.py`: GPT/Gemini 개별 심사 프롬프트, 근거 인용 검증, 100점 가중치.
- `app.py`: 엔진 사용/미사용과 모델별 독립 체크박스 및 결과 대시보드.
- `auditor/pro_reports.py`: 9시트 통합 전문 Excel에 `RAGAS 지표` 추가.
- `auditor/reports.py`: 단일 답변 보고서에 `RAGAS정량지표` 시트 추가.
- `tests/test_ragas_v3.py`: 4모드 설정, 누락 처리, 보고서, 모킹 테스트.

## 네 가지 모델 심사 방식

1. GPT만 체크: GPT LLM-as-a-Judge만 실행, Gemini 미호출.
2. Gemini만 체크: Gemini LLM-as-a-Judge만 실행, GPT 심사 미호출.
3. 둘 다 체크: 개별 심사 후 차이를 비교.
4. 둘 다 해제: LLM-as-a-Judge 미실시. RAGAS 엔진 설정에 따라 RAGAS만 수행하거나 지표별 미실시.

**중요:** RAGAS 평가용 OpenAI LLM의 사용 여부는 위 체크박스와 독립적입니다. GPT·Gemini 심사를 모두 꺼도 RAGAS Faithfulness를 수행하려면 OpenAI API를 호출할 수 있습니다. OpenAI API도 쓰지 않으려면 RAGAS LLM 스위치도 꺼야 합니다. 이때 `Exact Match`, `NonLLM String Similarity`는 **검증된 기준 답변이 있어야** 계산됩니다.

## 전문 평가체계 보존

- 안전성·신뢰성: 사용자 첨부 금융보안원 발표자료(2026-11-12, 24~29페이지) **10개 영역·28개 항목**. 증적 없이는 충족 판정 금지.
- 금융 AI 잔여위험: 사용자 첨부 워크북 4부문·16개 항목 참고 모델. 높은 점수일수록 위험. 미평가 항목이 있으면 위험 등급 보류.
- AI 답변의 정확도, 서비스 통제의 적합성과 금융잔여위험을 **같은 점수로 합산하지 않음**.

## 정량 평가지표 상세

| 지표 | 준비 정보 | 점수 형태 | 주의 |
|---|---|---|---|
| Faithfulness | 답변, 검색된 원본 단락, LLM | 0~1 | 검색된 단락에만 근거한 주장 지원 정도; 전체 자료에 대한 완전성 아님 |
| Factual Correctness | 답변, 검증된 정답, LLM | 0~1 | reference의 타당성을 외부에서 검증해야 함 |
| Answer Relevancy | 질문, 답변, LLM, 임베딩 | 통상 0~1 | 임베딩 기반 유사도, 정확도 평가 아님 |
| Context Precision | 질문, 근거, 검증된 정답, LLM | 0~1 | 검색 순위와 관련성에 의존 |
| Context Recall | 질문, 근거, 검증된 정답, LLM | 0~1 | 정답/검색 컨텍스트 품질에 의존 |
| Exact Match | 답변, 검증된 정답 | 0 또는 1 | 자연어 패러프레이징은 실패할 수 있음 |
| NonLLM String Similarity | 답변, 검증된 정답 | 0~1 | 비슷한 문장이라도 수치가 틀릴 수 있음 |

RAGAS retrieved_contexts는 **앱의 질문 기반 문서 검색 결과**입니다. 외부 AI 서비스가 실제 사용한 검색 문맥을 받아 재현한 것이 아니므로, Context Precision/Recall 값을 외부 AI의 RAG 검색기 성능으로 주장할 수 없습니다.

## 위험 통제 및 한계

1. 사용자가 제공하는 정답은 원본과 대조한 후 **확정 버튼**을 눌러야 사용합니다. 확정은 현재 질문·답변 조합에만 유효합니다.
2. 데이터셋 `reference_answer`를 사용하려면 별도의 원문 검증 체크가 필요합니다.
3. RAGAS 미실시 항목은 `0`이 아니라 `null`로 저장되어 보고서에 **미실시**로 표시됩니다.
4. LLM 심사 둘 다 미실시인 경우 보고서의 100점 점수와 품질기반 위험등급은 **판정 보류**로 표시됩니다.
5. API 사용량 집계는 GPT/Gemini 개별 심사와 RAGAS 내부 다중 호출이 다릅니다. RAGAS 내부 토큰/비용 추적은 추후 별도 계측이 필요합니다.
6. RAGAS 0.4.4 API는 2026-11-17 문서 기준 적용했으며, 이 환경에서는 패키지 설치 및 API 실연동이 불가능해 **통합 테스트 미실시**입니다. 연결 환경에서 SDK 설치/실제 API 스모크 테스트 후 배포하세요.

## 검사

`python -m pytest -q` 명령으로 32개 자동 테스트가 통과했습니다. 그중 RAGAS API 호출 테스트는 **모킹 방식**이며, 실 API 키로 모델을 호출한 결과가 아닙니다.
