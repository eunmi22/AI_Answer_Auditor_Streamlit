# Streamlit Community Cloud 배포 안내

1. `AI_Answer_Auditor_Streamlit.zip` 압축을 풉니다.
2. [GitHub](https://github.com/new)에서 `ai-answer-auditor` 저장소를 생성합니다.
3. **Add file → Upload files**로 압축 해제한 파일을 모두 업로드합니다. **폴더 구조를 유지**해야 합니다. `app.py`는 저장소 최상위에 둡니다. 숨김 `.streamlit` 폴더가 업로드되었는지도 확인합니다.
4. [Streamlit Community Cloud](https://share.streamlit.io/)에 GitHub 계정으로 로그인합니다.
5. **Create app → Yup, I have an app** 선택 후 GitHub 저장소, 브랜치 `main`, Main file path `app.py`를 입력합니다.
6. Advanced settings에서 Python 3.12를 선택합니다. Secrets는 개인 API 모드에서는 없어도 됩니다.
7. Deploy를 누르고 생성된 `https://...streamlit.app` URL로 접속합니다.
8. 본인 API 키로 문서 업로드, 질문 입력, 답변 생성, 두 평가자 평가, Excel 다운로드를 테스트합니다.
9. 운영자 무료 체험을 운영하려면 별도 Upstash Redis를 연결하고 Streamlit **Secrets**에 값을 설정합니다(README 참조). 키를 GitHub에 올리지 마세요.

**배포 후 꼭 확인할 사항**

- 두 모델 API 권한과 과금 설정은 각각 별도로 필요합니다.
- 무료 체험 기능은 초기 설정에서 꺼져 있습니다. 운영자 키, Redis 일일 한도를 모두 준비하면 활성화할 수 있습니다.
- 개인 API 키 입력 서비스의 개인정보 안내문, 이용약관, 연락처, 데이터 처리 정책을 공개 서비스 운영 전에 마련하세요.
- 내부 전용 버전 주의: 실제 회사 내부자료 대신 공개 샘플 문서로 시험하세요.
- 파일+웹 검색 평가는 OpenAI API 웹 검색 도구를 사용하여 추가 비용이 발생할 수 있습니다.
