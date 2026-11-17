# AI Answer Auditor PRO v4

**업로드 → 파일별 업무 도메인 자동 분류 → 평가 데이터셋 초안 자동 생성 → 검토·확정 → GPT/Gemini 선택 평가 + RAGAS → 보고서**

이 프로젝트는 이전 `AI Answer Auditor PRO v3` 소스를 유지하면서, 업로드 문서 기반 평가 데이터셋 자동 생성 기능을 추가한 Streamlit Community Cloud 배포용 프로젝트입니다.

## 1. v4 신규 기능

| 기능 | 설명 |
|---|---|
| 업로드 즉시 자동 분류 | PDF·DOCX·XLSX·CSV·TXT·PPTX 문서를 파일별로 분류. `학술논문 분석` 정식 지원 |
| 무료 자동 초안 | API 키 없이 문서에서 근거를 검색하고 도메인별 평가 질문과 **원문 그대로 발췌한 기준답변 초안**을 작성 |
| GPT/Gemini AI 정교화 | 사용자가 명시적으로 선택하고 API 키·외부전송 동의를 입력한 경우 질문·기준답변을 AI가 제안. 인용구·출처 ID가 실제 문서에 있는지 확인 |
| 사용자 검토 | 자동 생성 답변은 처음부터 모두 `검토 필요`. 출처를 보고 편집·확정한 사례만 기준답변으로 사용 |
| 평가대상 답변 | 직접 붙여넣거나 선택한 GPT 또는 Gemini로 생성하여 데이터셋에 저장. 자동 생성된 **기준답변**과 구분 |
| 데이터셋 내보내기 | 원문 근거 ID·페이지·인용구와 검토 상태를 포함한 CSV/XLSX |
| 기존 기능 유지 | GPT만/Gemini만/두 모델/둘 다 끄고 RAGAS만, RAGAS 정량지표, 통제 28개, 잔여위험 16개, 결과보고서 |

### 꼭 알아야 할 차이

- **도메인 자동 분류는 규칙 기반**입니다. 화면의 `추정 신뢰도`는 통계적으로 검증된 분류 확률이 아닙니다.
- **무료 자동 초안**은 원문 단락을 발췌합니다. 사람이 쓴 완성된 모범답안이 아닙니다.
- **AI 자동 초안**은 선택한 GPT 또는 Gemini API를 호출합니다. 한 개 이상의 API 호출에 비용이 발생할 수 있으며, 인용구의 존재 확인이 사실의 참됨까지 보증하지는 않습니다.
- **RAGAS**는 별도 `ragas==0.4.4` 패키지를 사용하며, 일부 지표에서 OpenAI LLM 및 임베딩 API가 필요합니다. GPT·Gemini 심사 체크박스와 독립적입니다.
- **검토 확정** 전의 `reference_answer`는 RAGAS 정답 기반 지표에 사용하지 않습니다. 잘못된 기준답변으로 채점하는 문제를 방지하기 위해서입니다.
- **재업로드** 시에도 확정 상태가 자동 복원되지 않습니다. 내보낸 CSV/XLSX의 `확정` 문자열은 재업로드 시 `검토 필요`로 초기화합니다.
- 이미지 기반 PDF는 OCR이 포함되지 않아 텍스트를 추출할 수 없습니다.

## 2. 설치와 실행

권장: Python 3.11 또는 3.12

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

브라우저: `http://localhost:8501`

### Streamlit Community Cloud

1. 이 프로젝트의 내용물을 GitHub 저장소 루트에 업로드합니다. (`app.py`가 루트에 있어야 합니다.)
2. https://share.streamlit.io/ 에서 저장소/브랜치/실행파일 `app.py`를 선택합니다.
3. `Advanced settings → Secrets`에 필요한 API 설정을 입력합니다. 키를 GitHub 코드에 넣지 마세요.
4. 앱의 ① 탭에서 공개·가상 문서를 업로드합니다.
5. ② 탭에서 자동 생성 사례를 검토 후 확정합니다.

`secrets.toml` 예시는 `.streamlit/secrets.example.toml`을 참고하세요.

## 3. Amazon RDS 논문 실습

첨부했던 논문 `Amazon RDS 데이터베이스.pdf`를 **사용자 본인이** ① 근거파일에 업로드합니다. 이 파일은 저작권이 있는 원문이므로 소스 ZIP/공개 GitHub 저장소에는 넣지 않았습니다.

- 자동 분류 결과: `학술논문 분석` (규칙 기반)
- 기본 10문항 / 설정상 최대 12문항
- 자동 질문 유형: 연구목적, 연구 대상, 연구방법, 선행연구, 실험 환경, 핵심 절차, 증거·자료, 주요 결과, 기여도, 연구 한계 등
- ② 탭에서 각 행의 원문 위치와 인용문을 확인하고 질문/기준답변을 필요에 따라 수정합니다.
- 완성된 답변만 `이 사례의 기준답변 확정` 버튼으로 확정합니다.
- 후보답변은 별도 입력/생성 후 ④ 탭에서 RAGAS 및 원하는 심사자를 골라 평가합니다.

**무료 초안 예시** (일부만): `이 논문의 연구 목적과 해결하려는 문제는 무엇인가요?` → 관련 PDF 원문 발췌 → `검토 필요`. 실제 RAGAS 평가 점수를 임의로 채워 넣지 않습니다.

## 4. 입력 제한 및 안전

- 원본 문서: 최대 6개, 파일당 8MB, 합계 16MB
- 자동 생성: 4~12건/요청
- AI 자동생성: 개인 API 키 방식만 허용, 최대 12건을 4건씩 분할 호출
- 시스템은 입력한 모델 키를 디스크에 저장하지 않으며 `st.session_state`에서만 사용합니다.
- 민감정보 정규식 탐지는 보조 수단이며 완전한 DLP가 아닙니다.
- **내부 전용 버전 주의:** 금융회사 내부 문서, 개인정보, 고객정보는 승인 없는 공개 Streamlit 앱에 올리거나 외부 LLM API로 전송하지 마세요.
- 파일 내용의 프롬프트 지시문은 신뢰하지 않도록 시스템 설계했으나, 완전한 프롬프트 인젝션 차단을 보장하지 않습니다.
- 금융보안원 평가체계를 참조하지만 **공식 인증/적합성 판정 시스템이 아닙니다**.

## 5. 주요 파일

```text
app.py                        # Streamlit UI 통합
requirements.txt              # Streamlit, RAGAS, GPT/Gemini, 문서처리 라이브러리
sample_public_data.txt        # 공개용 가상규정 시험 문서
auditor/
  autodataset.py              # [NEW] 도메인 분류 + 로컬/AI 평가셋 생성 + 출처 검증
  datasets.py                 # [UPDATED] CSV/XLSX 파싱 + 재검토 상태 초기화
  documents.py                # 문서별 텍스트·페이지·시트 추출
  retrieval.py                # 로컬 n-gram 근거 검색
  providers.py                # GPT·Gemini API 호출
  ragas_engine.py             # RAGAS 실제 SDK 연동 시도, 미실시·실패 명시
  evaluation.py               # LLM-as-a-Judge 점수 및 근거 판정
  frameworks.py               # 금융 AI 28개 점검·16개 잔여위험 항목
  reports.py,pro_reports.py   # 결과 보고서
  security.py,quota.py        # 개인정보 패턴 검출 및 체험 제한
tests/test_autodataset_v4.py  # 자동분류·생성·출처 검증·내보내기 회귀 테스트
```

## 6. 검증 범위

- 기존 테스트 32개와 신규 테스트 7개, 합계 39개 **통과**.
- 첨부된 Amazon RDS 논문 PDF를 실제 텍스트 파서로 읽어 원본 49개 단락 추출, 학술논문 분류 및 10건 평가 데이터셋 자동 생성 확인.
- UI 컨트롤 흐름을 Streamlit **모의 환경**으로 검증. 이것은 실제 브라우저/Streamlit Server 렌더링 시험을 대체하지 않습니다.
- 실제 Streamlit 패키지 구동, RAGAS 패키지 실행 및 GPT·Gemini 네트워크 호출은 **아직 검증하지 못했습니다.** 따라서 실서비스 배포 전 필수 테스트가 남았습니다.

## 참고 자료

- Streamlit: https://docs.streamlit.io/
- RAGAS: https://docs.ragas.io/
- OpenAI: https://platform.openai.com/docs/
- Gemini: https://ai.google.dev/gemini-api/docs/

## v4.1 수정: 평가 데이터셋 기준답변 자동 연결

- ②에서 선택한 케이스의 `question`, `reference_answer`, `candidate_answer`를 ③ 입력란에 자동 동기화합니다.
- 업로드 직후에는 첫 번째 자동생성 사례가 ③에 표시되고, ② 케이스 선택 변경에도 즉시 반영됩니다.
- 자동생성된 기준답변은 **초안/미확정**으로 표시합니다. ②의 원문 검토·확정 시 검증 상태가 ③에 이어집니다.
- 사용자가 ③의 질문 또는 기준답변을 수정하면 기존 확정은 무효화됩니다.
- `auditor/qa_flow.py`에서 상태 연동 및 정답 검증 서명을 분리해 관리합니다.
- 상세 절차: `기준답변_자동연결_사용안내.md`.
