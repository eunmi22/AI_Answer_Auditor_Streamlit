"""AI Answer Auditor: deploy with `streamlit run app.py`."""
from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from auditor.documents import parse_uploads
from auditor.evaluation import DEFAULT_RUBRIC, evaluate, judges_disagree, normalize_rubric, risk_level
from auditor.providers import generated_answer, web_evidence
from auditor.quota import take_demo_credit
from auditor.reports import csv_history, excel_report
from auditor.retrieval import find_evidence, format_evidence
from auditor.security import detect_sensitive, redact_pii, redact_records

st.set_page_config(page_title="AI 답변 신뢰성 평가 시스템", page_icon="🔎", layout="wide")
st.markdown("""
<style>
.block-container { max-width: 1360px; padding-top: 2rem; }
h1 { letter-spacing: -.045em; }
h2,h3 { letter-spacing: -.025em; }
.smalllabel { color:#456479; font-size:0.88rem; margin-top:-.4rem; }
.stMetric { border: 1px solid #DFE8F0; border-radius:12px; padding: 14px 18px; background:white; }
</style>
""", unsafe_allow_html=True)


def get_secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def initial_state():
    for key, value in {
        "records": [], "notices": [], "file_fingerprint": "", "answers": {},
        "reports": [], "usage_log": [], "demo_calls": 0,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def log_usage(info):
    st.session_state.usage_log.append(info)


def demo_enabled():
    return bool(get_secret("DEMO_ENABLED", False)) and bool(get_secret("UPSTASH_REDIS_REST_URL")) and bool(get_secret("UPSTASH_REDIS_REST_TOKEN")) and bool(get_secret("OPENAI_API_KEY")) and bool(get_secret("GEMINI_API_KEY"))


def obtain_key(vendor):
    if access_type == "운영자 무료 체험":
        return get_secret("OPENAI_API_KEY" if vendor == "GPT" else "GEMINI_API_KEY", "")
    return (st.session_state.get("openai_personal_key") if vendor == "GPT" else st.session_state.get("gemini_personal_key")) or ""


def preflight(vendor):
    key = obtain_key(vendor)
    if not key:
        raise ValueError(f"{vendor} API 키를 입력해야 합니다.")
    if not st.session_state.get("approval") or not st.session_state.get("consent"):
        raise ValueError("공개·승인 자료 확인 및 외부 AI 전송 동의가 필요합니다.")
    if access_type == "운영자 무료 체험":
        if st.session_state.demo_calls >= 2:
            raise ValueError("무료 체험은 접속당 최대 2회 AI 호출이 가능합니다. 개인 API 키를 이용해 주세요.")
        take_demo_credit(get_secret("UPSTASH_REDIS_REST_URL"),
                         get_secret("UPSTASH_REDIS_REST_TOKEN"),
                         int(get_secret("DEMO_DAILY_REQUESTS", 24)))
        st.session_state.demo_calls += 1
    return key


def safe_error(e):
    # Do not display raw prompts or API credentials in error messages.
    if isinstance(e, (ValueError, RuntimeError)):
        st.error(str(e)[:260])
    else:
        st.error(f"요청 실패: {type(e).__name__}. 모델 접근권한·요금제·API 키를 확인해 주세요.")


initial_state()
st.title("AI 답변 신뢰성 평가 시스템")
st.markdown('<p class="smalllabel">AI Answer Auditor · 문서 기반 근거 검증 · GPT × Gemini 독립 평가</p>', unsafe_allow_html=True)
st.info("평가 점수는 AI 심사 모델의 판단입니다. 문서 근거 인용은 별도로 기계 검증하며, 문서에 없는 내용과 명백한 오류를 구분합니다. 실제 RAGAS 지표를 직접 실행한 결과는 아닙니다.")

with st.sidebar:
    st.subheader("설정")
    modes = ["내 API 키 사용"] + (["운영자 무료 체험"] if demo_enabled() else [])
    access_type = st.radio("API 이용 방식", modes, help="운영자 체험은 Redis 기반 일일 호출 한도를 설정한 경우에만 나타납니다.")
    if access_type == "내 API 키 사용":
        st.text_input("OpenAI API 키", type="password", key="openai_personal_key", placeholder="sk-...")
        st.text_input("Gemini API 키", type="password", key="gemini_personal_key", placeholder="AIza...")
    else:
        st.caption("무료 체험은 입력된 답변에 대한 파일 기준 교차 평가에 한하며, 세션당 총 2회 모델 호출까지만 허용됩니다.")
    st.divider()
    gpt_model = st.selectbox("GPT 모델", ["gpt-6-luna", "gpt-6.1-terra"], index=0 if access_type == "운영자 무료 체험" else 1,
                             disabled=access_type == "운영자 무료 체험")
    gemini_model = st.selectbox("Gemini 모델", ["gemini-3.5-flash-lite", "gemini-3.8-flash"], index=0 if access_type == "운영자 무료 체험" else 1,
                                disabled=access_type == "운영자 무료 체험")
    st.divider()
    st.checkbox("업로드 자료는 공개 가능하거나 외부 전송이 승인된 자료입니다.", key="approval")
    st.checkbox("자료·질문·답변이 선택한 AI 제공업체 API로 전송되는 데 동의합니다.", key="consent")
    st.caption("원문 파일과 평가 결과를 앱 데이터베이스에 저장하지 않습니다. 개인 API 키는 현재 접속 세션에서만 사용합니다.")
    st.divider()
    st.caption("API 비용 모니터링")
    st.metric("이번 세션 AI 호출", len(st.session_state.usage_log))
    if st.session_state.usage_log:
        known = [v["estimated_usd"] for v in st.session_state.usage_log if v["estimated_usd"] is not None]
        st.caption(f"GPT 텍스트 토큰 추정 비용: ${sum(known):.5f} (웹 검색·Gemini 요금 별도, 참고용)")
        st.caption("토큰 수는 모델이 제공한 사용량 정보를 기반으로 합니다. 실제 청구액은 공급자 계정에서 확인하세요.")
    if st.button("이 세션의 API 키 초기화"):
        for field in ("openai_personal_key", "gemini_personal_key"):
            st.session_state.pop(field, None)
        st.rerun()

files_tab, qa_tab, eval_tab, dashboard_tab, report_tab = st.tabs([
    "① 파일 관리", "② 질문·답변", "③ 평가 실행", "④ 결과 대시보드", "⑤ 평가 보고서"
])

with files_tab:
    st.subheader("원본 근거 파일 등록")
    st.write("PDF, Word(docx), Excel(xlsx), CSV, TXT, PowerPoint(pptx). 최대 6개, 파일당 8MB, 전체 16MB입니다.")
    uploads = st.file_uploader("자료를 업로드하세요", type=["pdf", "docx", "xlsx", "csv", "txt", "pptx"], accept_multiple_files=True)
    if uploads:
        blob = [(x.name, x.getvalue()) for x in uploads]
        signature = hashlib.sha256(b"".join(x[0].encode()+b"\0"+hashlib.sha256(x[1]).digest() for x in blob)).hexdigest()
        if signature != st.session_state.file_fingerprint:
            try:
                docs, notices = parse_uploads(blob)
                st.session_state.records = docs
                st.session_state.notices = notices
                st.session_state.file_fingerprint = signature
                st.session_state.answers = {}
                st.session_state.reports = []
            except Exception as e:
                st.session_state.records = []
                safe_error(e)
    elif st.session_state.file_fingerprint:
        st.session_state.file_fingerprint = ""
        st.session_state.records = []
        st.session_state.answers = {}
        st.session_state.reports = []
    records = st.session_state.records
    if records:
        names = sorted(set(r["file"] for r in records))
        c1,c2,c3 = st.columns(3)
        c1.metric("등록된 파일", len(names))
        c2.metric("근거 단락", len(records))
        c3.metric("추출 문자", f"{sum(len(r['text']) for r in records):,}")
        for m in st.session_state.notices:
            st.warning(m)
        found = sorted(set(label for r in records for label in detect_sensitive(r["text"])))
        if found:
            st.error("개인정보/내부자료 표시 탐지: " + ", ".join(found))
            st.caption("개인정보 패턴은 AI로 보내기 전에 자동 마스킹됩니다. 내부자료 여부는 사용자 확인이 반드시 필요합니다. 탐지 기능은 완전하지 않습니다.")
            if "내부 전용 표시" in found:
                st.warning("내부 전용 버전 주의: 허가 없는 내부 자료는 사용하지 마세요.")
        st.dataframe(pd.DataFrame([{"파일": n, "단락 수": sum(r["file"]==n for r in records)} for n in names]), hide_index=True, use_container_width=True)
        sample = st.selectbox("원본 발췌 확인", [r["id"] for r in records[:100]])
        target = next(r for r in records if r["id"]==sample)
        st.caption(f"{target['file']} / {target['location']}")
        st.code(target["text"][:1200], language=None)
    else:
        st.caption("파일을 등록하면 문서별 페이지·시트·슬라이드 근거를 추적할 수 있습니다.")

with qa_tab:
    st.subheader("질문과 AI 답변")
    question = st.text_area("평가할 질문", key="question", placeholder="예: 업로드한 문서에서 로그 보관기간은 얼마로 정하고 있나요?", height=100, max_chars=2800)
    external = st.text_area("외부 AI 답변 붙여넣기", key="external_response", placeholder="ChatGPT, Gemini 또는 다른 AI에서 받은 답변을 입력할 수 있습니다.", height=170, max_chars=8500)
    if question and detect_sensitive(question):
        st.warning("질문에서 개인정보가 탐지되었습니다. API 전송 시 자동 마스킹됩니다.")
    if access_type == "운영자 무료 체험":
        st.info("운영자 무료 체험은 위에 외부 AI 답변을 붙여넣고 ③ 평가 실행에서 이용할 수 있습니다.")
    cols = st.columns(3)
    actions = ["GPT 답변 생성", "Gemini 답변 생성", "둘 다 답변 생성"]
    pressed = [c.button(label, use_container_width=True, disabled=access_type == "운영자 무료 체험") for c,label in zip(cols, actions)]
    if any(pressed):
        try:
            if not st.session_state.records or not question.strip():
                raise ValueError("먼저 원본 파일과 질문을 입력해야 합니다.")
            docs = redact_records(find_evidence(st.session_state.records, redact_pii(question)))
            evidence = format_evidence(docs)
            chosen = ["GPT"] if pressed[0] else (["Gemini"] if pressed[1] else ["GPT", "Gemini"])
            for vendor in chosen:
                with st.spinner(f"{vendor}가 문서를 참조하여 답변 생성 중..."):
                    key = preflight(vendor)
                    text, u = generated_answer(vendor, key, gpt_model if vendor == "GPT" else gemini_model,
                                               redact_pii(question), evidence)
                    st.session_state.answers[vendor] = text
                    log_usage(u)
            st.success("답변 생성이 완료되었습니다. ③ 평가 실행에서 검증할 수 있습니다.")
        except Exception as e:
            safe_error(e)
    for label in ("GPT", "Gemini"):
        if label in st.session_state.answers:
            with st.expander(f"{label} 생성 답변", expanded=True):
                st.write(st.session_state.answers[label])

with eval_tab:
    st.subheader("평가 기준과 실행")
    scope = st.radio("검증 근거", ["업로드 파일만", "업로드 파일 + 웹 검색"], horizontal=True,
                     disabled=access_type == "운영자 무료 체험")
    st.caption("웹 검색은 OpenAI 검색 도구로 동일한 자료를 수집한 다음 두 심사 모델에 제공합니다. 검색 요약은 웹 원문을 전수 확인한 결과가 아닙니다.")
    st.write("평가항목과 배점을 자유롭게 조정하세요. 합계가 정확히 100점이어야 합니다.")
    edited = st.data_editor(pd.DataFrame(DEFAULT_RUBRIC), hide_index=True, num_rows="dynamic",
                            use_container_width=True, key="rubric_editor",
                            column_config={"항목": st.column_config.TextColumn("평가 항목", required=True),
                                           "배점": st.column_config.NumberColumn("배점", min_value=0, max_value=100, step=1, required=True)})
    rubric_valid = None
    try:
        rubric_valid = normalize_rubric(edited.to_dict("records"))
        st.caption("현재 총 배점: 100점")
    except ValueError as e:
        st.warning(str(e))
    candidates = {f"{k} 생성 답변": v for k,v in st.session_state.answers.items() if v.strip()}
    if st.session_state.get("external_response", "").strip():
        candidates["외부 입력 답변"] = st.session_state.external_response
    selected = st.multiselect("평가할 AI 답변", list(candidates), default=list(candidates)[:2],
                              help="답변을 여러 개 선택하면 각각 GPT·Gemini의 독립 평가 결과가 생성됩니다.")
    if access_type == "운영자 무료 체험":
        selected = [x for x in selected if x == "외부 입력 답변"]
        st.caption("무료 체험은 외부 입력 답변 1건만 평가할 수 있습니다.")
    if st.button("GPT × Gemini 통합 평가 실행", type="primary", use_container_width=True):
        try:
            if not rubric_valid:
                raise ValueError("평가항목 배점 합계를 100점으로 맞춰 주세요.")
            if not st.session_state.records or not st.session_state.get("question", "").strip():
                raise ValueError("원본 파일과 질문을 먼저 등록해 주세요.")
            if not selected:
                raise ValueError("평가할 AI 답변을 선택하세요.")
            if access_type == "운영자 무료 체험" and (len(selected) != 1 or len(st.session_state.reports) >= 1):
                raise ValueError("무료 체험은 접속 세션에서 답변 1건만 평가할 수 있습니다.")
            if scope == "업로드 파일 + 웹 검색" and not obtain_key("GPT"):
                raise ValueError("웹 검색에는 OpenAI API 키가 필요합니다.")
            if not obtain_key("Gemini"):
                raise ValueError("교차 평가에는 Gemini API 키가 필요합니다.")
            if not obtain_key("GPT"):
                raise ValueError("교차 평가에는 OpenAI API 키가 필요합니다.")
            question_clean = redact_pii(st.session_state.question)
            web_summary, web_urls = "", []
            if scope == "업로드 파일 + 웹 검색":
                with st.spinner("공통 웹 검색 근거 수집 중..."):
                    web_key = preflight("GPT")
                    web_summary, web_urls, usage = web_evidence(web_key, gpt_model, question_clean)
                    log_usage(usage)
            for chosen_name in selected:
                answer = candidates[chosen_name]
                evidence_docs = redact_records(find_evidence(st.session_state.records,
                                                    question_clean + " " + redact_pii(answer[:500]), limit=10))
                material = format_evidence(evidence_docs)
                report = {
                    "timestamp": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
                    "question": question_clean, "answer": redact_pii(answer),
                    "target": chosen_name, "mode": scope, "sources": evidence_docs, "web_urls": web_urls,
                    "judges": {}, "disagreements": [],
                }
                for judge in ("GPT", "Gemini"):
                    with st.spinner(f"{chosen_name} / {judge} 독립 검증 중..."):
                        try:
                            key = preflight(judge)
                            ev, usage = evaluate(judge, key, gpt_model if judge == "GPT" else gemini_model,
                                                  question_clean, redact_pii(answer), material, evidence_docs,
                                                  web_summary, web_urls, rubric_valid)
                            report["judges"][judge] = ev
                            log_usage(usage)
                        except Exception as e:
                            safe_error(e)
                if len(report["judges"]) == 2:
                    report["disagreements"] = judges_disagree(report["judges"]["GPT"], report["judges"]["Gemini"])
                if report["judges"]:
                    st.session_state.reports.insert(0, report)
            st.success("평가 결과가 등록되었습니다. ④ 결과 대시보드에서 확인하세요.")
        except Exception as e:
            safe_error(e)

with dashboard_tab:
    st.subheader("독립 평가 대시보드")
    if not st.session_state.reports:
        st.info("③ 평가 실행에서 평가를 완료하면 결과를 확인할 수 있습니다.")
    else:
        labels = [f"{i+1}. {r['target']} · {r['timestamp']}" for i,r in enumerate(st.session_state.reports)]
        chosen_i = st.selectbox("평가 이력", range(len(labels)), format_func=lambda x: labels[x])
        report = st.session_state.reports[chosen_i]
        judges = report["judges"]
        score_values = [v["total"] for v in judges.values()]
        mean_score = round(sum(score_values)/len(score_values),1)
        cols = st.columns(4)
        cols[0].metric("평균 종합점수", f"{mean_score}/100")
        cols[1].metric("GPT 평가", f"{judges['GPT']['total']}" if "GPT" in judges else "미완료")
        cols[2].metric("Gemini 평가", f"{judges['Gemini']['total']}" if "Gemini" in judges else "미완료")
        cols[3].metric("잠정 위험등급", risk_level(mean_score))
        if len(judges) < 2:
            st.warning("한쪽 평가가 실패하여 교차 평가가 완료되지 않았습니다.")
        if report["disagreements"]:
            st.warning("재검토 필요: 100점 기준 15점 이상 차이가 난 항목 = " + ", ".join(report["disagreements"]))
        score_rows = []
        for judge, ev in judges.items():
            for item in ev["scores"]:
                score_rows.append({"평가항목": item["name"], "평가모델": judge, "품질점수": item["quality"], "배점": item["weight"], "가중점수": item["weighted"]})
        if score_rows:
            frame = pd.DataFrame(score_rows)
            st.bar_chart(frame.pivot(index="평가항목", columns="평가모델", values="품질점수"))
            st.dataframe(frame, hide_index=True, use_container_width=True)
        for judge, ev in judges.items():
            with st.expander(f"{judge} 평가 세부 내용", expanded=True):
                st.write(ev["summary"])
                st.markdown("**주장별 근거 검증**")
                if ev["findings"]:
                    df = pd.DataFrame([{
                        "AI 주장": f["claim"], "판정": f["status"], "근거ID": ", ".join(f["source_ids"]),
                        "원문인용 확인": "확인" if f["quote_verified"] else "미확인",
                        "판정사유": f["explanation"], "개선 권고": f["recommendation"]
                    } for f in ev["findings"]])
                    st.dataframe(df, hide_index=True, use_container_width=True)
                    for i,f in enumerate(ev["findings"]):
                        with st.expander(f"증거 {i+1}: {f['claim'][:75]}"):
                            st.write(f"판정: {f['status']}")
                            st.write(f"근거 ID: {', '.join(f['source_ids']) or '없음'}")
                            st.write(f"근거 인용: {f['evidence_quote'] or '없음'}")
                            st.write("문서 원문 인용 자동대조: " + ("일치" if f["quote_verified"] else "불일치/미확인"))
                            if f["web_citation_only"]:
                                st.caption("웹 출처는 검색 도구가 반환한 링크만 확인했습니다. 웹 원문 문장 대조는 수행하지 않았습니다.")
                st.markdown("**개선 답변**")
                st.write(ev["improved_answer"])
                if ev["checklist"]:
                    st.markdown("**점검 체크리스트**")
                    st.dataframe(pd.DataFrame(ev["checklist"]), hide_index=True, use_container_width=True)
                if ev["limitations"]:
                    st.markdown("**검증 한계**")
                    for limitation in ev["limitations"]:
                        st.write("• " + limitation)
        st.markdown("**참조한 원본 문서 단락**")
        for source in report["sources"]:
            with st.expander(f"[{source['id']}] {source['file']} / {source['location']}"):
                st.code(source["text"], language=None)
        if report["web_urls"]:
            st.markdown("**검색 도구가 반환한 웹 출처**")
            for w in report["web_urls"]:
                st.write(f"[{w['id']}] {w['title']} : {w['url']}")
        st.caption("위 평가는 모델 기반 잠정 판단이며, 검색된 근거 단락 외의 문서 내용과 스캔 이미지·표 구조는 누락될 수 있습니다.")

with report_tab:
    st.subheader("평가 보고서 다운로드")
    if not st.session_state.reports:
        st.info("먼저 AI 답변을 평가해 주세요.")
    else:
        st.dataframe(pd.DataFrame([{
            "일시": r["timestamp"], "질문": r["question"][:70], "답변": r["target"],
            "GPT": r["judges"].get("GPT",{}).get("total","-"),
            "Gemini": r["judges"].get("Gemini",{}).get("total","-"),
            "재검토 항목": ", ".join(r["disagreements"]) or "없음"
        } for r in st.session_state.reports]), hide_index=True, use_container_width=True)
        idx = st.selectbox("Excel로 저장할 보고서", range(len(st.session_state.reports)),
                           format_func=lambda x: f"{x+1}. {st.session_state.reports[x]['target']}")
        report = st.session_state.reports[idx]
        st.download_button("선택한 상세 평가보고서 Excel 다운로드", data=excel_report(report),
                           file_name=f"AI_답변_평가보고서_{idx+1}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
        st.download_button("전체 평가 이력 CSV 다운로드", data=csv_history(st.session_state.reports),
                           file_name="AI_평가이력.csv", mime="text/csv", use_container_width=True)
        if st.button("평가 이력 모두 지우기"):
            st.session_state.reports = []
            st.rerun()
        st.warning("평가 이력은 현재 Streamlit 세션에서만 유지되며, 재접속 시 복원되지 않습니다. 필요한 경우 파일을 내려받으세요.")

st.divider()
st.caption("AI Answer Auditor · 증거 문장 자동대조는 정확한 문자열 일치 검사이며 의미적 사실 검증을 보증하지 않습니다. 공개 서비스에 내부·개인정보 자료를 업로드하지 마세요.")
