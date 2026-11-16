# AI 답변 신뢰성 평가 시스템 (AI Answer Auditor)

Streamlit Community Cloud용 공개 AI 답변 검증 웹앱입니다. **2026-11-17 기준 데모 배포용 구현**으로, API 자격 증명 없이 실행 화면을 확인할 수 있지만 실제 생성·평가 호출은 API 키가 필요합니다.

## 지원 기능

- PDF / DOCX / XLSX / CSV / TXT / PPTX 다중 업로드. 문서별 페이지·시트·행·슬라이드 위치 표시.
- GPT와 Gemini 답변을 각각 생성하거나 외부 AI 답변을 붙여넣어 평가.
- 업로드 문서 기반 평가 또는 웹 검색을 추가한 평가 선택.
- GPT·Gemini가 **동일한 근거**로 각각 독립 평가. 점수 차이(15점 이상) 표시.
- 4개 기본 평가항목과 사용자 정의 배점(합계 100점), 환각/모순/근거 부족 사례 표시.
- 파일에서 실제로 발췌된 인용문과 AI가 제안한 인용문을 프로그램이 다시 문자열 비교.
- 접속 중 평가 이력만 관리하며 상세 XLSX 및 전체 CSV 다운로드.
- 비식별처리용 주민등록번호·전화번호·이메일·카드번호 패턴 탐지/자동 마스킹.
- 공개 운영을 위한 **BYOK(본인 API 키) 우선** 방식. 별도 설정 시 무료 체험 지원.

## 최소 실행

Python 3.12 권장:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

웹 브라우저에서 `http://localhost:8501`을 엽니다. 사이드바에서 개인 OpenAI·Gemini API 키를 입력합니다.

## GitHub → Streamlit Community Cloud 배포

1. GitHub에서 새 저장소를 만들고 이 폴더의 모든 파일을 올립니다. `.streamlit/secrets.toml`과 실제 API 키는 **절대 업로드하지 마세요**.
2. https://share.streamlit.io 에 GitHub로 로그인하고 **Create app** → **Yup, I have an app**을 선택합니다.
3. 저장소 / 브랜치 `main` / Main file path `app.py`를 지정합니다.
4. **Advanced settings**에서 Python 3.12를 선택합니다. 운영자 체험을 사용하지 않는다면 Secrets를 비워 두어도 됩니다.
5. **Deploy**를 눌러 공개 `*.streamlit.app` 주소를 생성합니다.
6. 사용자는 자기 API 키를 입력해 서비스에 접근할 수 있습니다. 개인 API 키는 브라우저 접속 세션 종료 후 재사용되지 않습니다.

## 운영자 무료 체험 설정 (선택)

공개 앱에 운영자 키를 단순히 넣고 세션당 N회 제한하는 것만으로는 비용을 통제할 수 없습니다. 방문자는 세션을 무한히 재시작할 수 있기 때문입니다. 따라서 본 앱은 **서버 공통의 Redis 일일 원자적 한도**가 없으면 운영자 무료 체험을 **보이지 않게** 합니다.

1. Upstash Redis(REST 지원) 인스턴스를 별도로 준비합니다.
2. Streamlit 앱 Settings → Secrets에 `.streamlit/secrets.example.toml`을 참고해 실제 값을 **GitHub가 아닌 Streamlit Secrets**에 설정합니다.
3. `DEMO_ENABLED = true`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `DEMO_DAILY_REQUESTS = 24`를 입력합니다.
4. 체험은 본인 입력 답변 **1건**, 파일 기준 **GPT + Gemini 각 1회 평가**만 허용합니다. 생성·웹 검색은 체험에서 불가합니다.
5. Redis는 무료 체험 API 호출 횟수를 자정 KST 날짜별로 전체 사용자에 대해 합산합니다. 초과 시 자동 차단합니다. Redis 연결 실패 시 체험 호출이 거절됩니다(페일 클로즈).
6. **중요:** 위 원자적 호출 한도는 비용 사용을 제한하지만, AI 공급자 측의 과금 한도와 결제 제한을 대신하지 않습니다. 양쪽 공급자의 지출 한도도 설정하세요. 로그 및 보안 검토 없이 무제한으로 키를 노출하지 마세요.

## 보안 / 개인정보

- 내부 전용 버전 주의: **사내 내부자료, 고객 개인(신용)정보, 승인되지 않은 금융자료는 업로드하지 마세요.** 공개 접속 가능 여부와 업로드 허용 여부는 별개입니다.
- 파일 업로드는 메모리에서만 파싱됩니다. 앱은 보고서·파일을 DB나 공유 디스크에 영구 저장하지 않습니다. 평가 이력은 `st.session_state`로만 보존합니다.
- 업로드 원문을 외부 업체(API)로 발췌 전송합니다. 메모리 저장 여부와 **AI 제공업체의 데이터 처리 정책**은 서로 다른 문제입니다. 서비스 공개 전 해당 정책을 별도로 확인해야 합니다.
- 일부 유형의 개인정보를 정규식으로 마스킹하지만 100% 탐지하는 DLP는 아닙니다. 사용자가 공개·전송 승인 여부를 확인해야 호출할 수 있습니다.
- 공개 서비스의 개인 API 키 입력은 사용자의 신뢰를 전제로 하므로 키 입력 화면에 운영 주체·개인정보처리방침·API 이용 안내를 공개한 후 운영하시기 바랍니다.
- ZIP, DOC, XLS(구형 바이너리), 암호화 파일, 스캔 PDF OCR은 지원하지 않습니다. 사용자가 PDF 글자 이미지를 올린 경우 추출 텍스트가 없다는 경고를 제공합니다.
- 각 파일은 최대 8MB, 최대 6개, 합계 16MB, 최대 500단락이며, Excel/CSV는 각 시트당 600행까지만 처리합니다. 누락이 있을 수 있습니다.

## 평가 방법의 한계

- **RAGAS 공식 라이브러리/metric을 호출하지 않습니다.** RAGAS Faithfulness 등 개념을 참고한 LLM-as-a-judge **가중 평가 예시**입니다. 표준화된 정량 벤치마크가 아니며, 100점은 정답률이나 법적 적합률이 아닙니다.
- 근거 발췌는 문자 n-gram 유사도로 검색한 상위 단락들만 사용합니다. 문서 전체를 전수 감사하는 시스템이 아닙니다.
- 출처 자동 검증은 **짧은 인용문의 문자열 포함 여부**만 검증합니다. 의미상 사실 오류·문맥 왜곡을 보장하지 않습니다.
- 웹 모드는 OpenAI 검색 도구의 검색 요약과 반환 URL을 두 평가자에게 동일하게 제공합니다. 링크를 독립적으로 다운로드하거나 웹페이지 문장과 직접 대조하지 않습니다. 웹 검색 요약은 공식 출처 검증과 다릅니다.
- GPT와 Gemini가 의견이 같아도 두 모델 모두 틀릴 수 있습니다. 중요 의사결정은 사람이 재확인하세요.
- 평가마다 최대 10개 문서 발췌(합계 최대 13,000자)를 전달합니다. 장문과 스캔파일에서 중요한 근거가 누락될 수 있습니다.
- 모델 및 공급자 요금은 달라질 수 있습니다. 측정 토큰은 출력하지만 현재 코드에서 확정된 단가의 GPT 텍스트 모델만 추정 비용에 반영하며, Gemini/웹 검색 비용은 포함하지 않습니다.

## 소스 구조

```
app.py                 Streamlit 5개 탭 화면
requirements.txt       배포 의존성
auditor/documents.py   문서 텍스트 추출 및 위치 추적
auditor/retrieval.py   로컬 문서 근거 검색
auditor/providers.py   GPT/Gemini 및 OpenAI 웹 검색 어댑터
auditor/evaluation.py 평가 및 인용문 검증
auditor/security.py   기본 개인정보 탐지와 마스킹
auditor/quota.py      Upstash Redis 일일 호출 제한
auditor/reports.py    XLSX/CSV 다운로드
tests/                 테스트
.streamlit/config.toml 화면 테마 및 제한
```

## 테스트

```bash
pip install pytest
python -m pytest -q
```

## 참고 공식 문서

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://aistudio.google.com/docs/models
- https://aistudio.google.com/docs/google-search
