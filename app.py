"""AI Answer Auditor PRO v4 · automatic domain detection and reviewable evaluation dataset."""
from __future__ import annotations
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from auditor.documents import parse_uploads
from auditor.autodataset import (DOMAINS, local_drafts, generate_ai_drafts,
                                classify_documents, dataset_csv_bytes, dataset_excel_bytes)
from auditor.datasets import SAMPLE_CASES, template_csv, parse_dataset, DATASET_CATEGORIES
from auditor.evaluation import evaluate, judges_disagree, normalize_rubric
from auditor.ragas_engine import (run_ragas, RAGAS_NON_LLM, RAGAS_LLM, selected_judges,
                                  merge_assessment_status, ragas_metric_requirements)
from auditor.frameworks import (CONTROLS, FRAMEWORK_SOURCE, RISK_SOURCE, RISK_WEIGHTS,
                                controls_summary, calculate_residual_risk)
from auditor.pro_reports import professional_report
from auditor.providers import generated_answer, web_evidence, openai_text, gemini_text
from auditor.quota import take_demo_credit
from auditor.reports import csv_history, excel_report
from auditor.retrieval import find_evidence, format_evidence
from auditor.security import detect_sensitive, redact_pii, redact_records

st.set_page_config(page_title="AI Answer Auditor PRO | 금융 AI 전문 평가", page_icon="🛡️", layout="wide")
st.markdown("""
<style>
.block-container {max-width:1480px;padding-top:1.4rem;padding-bottom:2rem}
[data-testid="stSidebar"] {background:#F3F7FC}
h1,h2,h3 {letter-spacing:-.035em}
.hero {background:linear-gradient(105deg,#071B31,#153C64 74%,#315C98);
color:white;border-radius:16px;padding:24px 28px;margin-bottom:15px}
.hero h1 {color:white;font-size:2.05rem;margin:0 0 6px 0}
.hero p {color:#D1E5F5;margin:0;line-height:1.55}
.kicker {color:#88BFFF;letter-spacing:2px;font-size:.77rem;font-weight:700;margin-bottom:5px}
.pill {display:inline-block;border-radius:30px;background:#E9EFFA;color:#224776;padding:3px 11px;font-size:.8rem;font-weight:600}
[data-testid="stMetric"]{background:white;border:1px solid #D9E5F4;border-radius:12px;padding:11px 15px}
[data-testid="stTabs"] button {font-weight:600}
.small-note{font-size:.85rem;color:#51647B}
</style>
<div class="hero">
<div class="kicker">FINANCIAL AI ASSURANCE · REFERENCE IMPLEMENTATION</div>
<h1>AI Answer Auditor PRO</h1>
<p>답변 품질 평가 × 안전성·신뢰성 28개 점검 × 잔여위험 16개 항목<br>
업로드 즉시 도메인 자동분류·평가데이터셋 초안생성 · RAGAS + GPT·Gemini 심사 · 감사형 보고서</p>
</div>
""", unsafe_allow_html=True)

QUALITY_PROFILES={
    "학술논문 분석 · 심층": [
        {"항목":"원문 근거 충실도","배점":25},
        {"항목":"연구목적·연구문제 이해","배점":15},
        {"항목":"연구방법 분석 정확성","배점":20},
        {"항목":"연구결과·기여도 해석","배점":15},
        {"항목":"연구 한계 분석","배점":15},
        {"항목":"인용·출처 정확성","배점":10}],
    "RAG · 근거형": [
        {"항목":"근거 충실도","배점":30},{"항목":"사실·수치 정확성","배점":25},
        {"항목":"질문 관련성","배점":15},{"항목":"답변 완전성","배점":10},
        {"항목":"근거 추적가능성","배점":10},{"항목":"응답 안전성·정보 노출","배점":10}],
    "LLM · 일반 답변": [
        {"항목":"사실·수치 정확성","배점":30},{"항목":"질문 관련성","배점":25},
        {"항목":"답변 완전성","배점":20},{"항목":"일관된 논리 구성","배점":10},
        {"항목":"응답 안전성·정보 노출","배점":15}],
    "Agent · 실행 설명": [
        {"항목":"주장·실행 근거 충실도","배점":30},{"항목":"사실·결과 정확성","배점":25},
        {"항목":"목표 적합성","배점":15},{"항목":"설명·완전성","배점":10},
        {"항목":"권한·승인 설명의 적절성","배점":20}],
}

def secret(k, default=None):
    try: return st.secrets.get(k,default)
    except Exception: return default

def initialize():
    initial={
        "records":[], "notices":[], "file_fingerprint":"", "answers":{}, "reports":[], "usage_log":[],
        "demo_calls":0, "datasets":list(SAMPLE_CASES), "dataset_fingerprint":"", "dataset_source":"공개 가상 샘플",
        "selected_case":{}, "selected_case_id":"", "external_response":"", "question":"",
        "framework_rows":[{**c,"상태":"미평가","증적":"","판단사유":""} for c in CONTROLS],
        "risk_rows":[{"id":i,"부문":p,"항목":name,"배점":w,"경감수준":"미평가","증적":"","판단사유":""} for i,p,name,w in RISK_WEIGHTS],
        "profile_selected":"RAG · 근거형", "approval":False,"consent":False,
        "auto_domain":"기타", "auto_file_classes":[], "auto_warnings":[],
        "dataset_revision":0, "autodata_source_sha":"", "domain_overrides":{},
        "auto_generation_provider":"원문 발췌 (무료)",
    }
    for k,v in initial.items():
        if k not in st.session_state:st.session_state[k]=v

def demo_enabled():
    return all([bool(secret("DEMO_ENABLED",False)),bool(secret("UPSTASH_REDIS_REST_URL")),
                bool(secret("UPSTASH_REDIS_REST_TOKEN")),bool(secret("OPENAI_API_KEY")),bool(secret("GEMINI_API_KEY"))])

def key_of(vendor):
    if access_type=="운영자 무료 체험":
        return secret("OPENAI_API_KEY" if vendor=="GPT" else "GEMINI_API_KEY", "")
    return (st.session_state.get("openai_personal_key") if vendor=="GPT" else st.session_state.get("gemini_personal_key")) or ""

def preflight(vendor):
    if not st.session_state.approval or not st.session_state.consent:
        raise ValueError("공개/승인된 자료 확인과 외부 AI API 전송 동의가 필요합니다.")
    k=key_of(vendor)
    if not k:raise ValueError(f"{vendor} API 키가 필요합니다.")
    if access_type=="운영자 무료 체험":
        if st.session_state.demo_calls>=2:raise ValueError("무료 체험은 세션당 최대 2회 모델 호출입니다.")
        take_demo_credit(secret("UPSTASH_REDIS_REST_URL"),secret("UPSTASH_REDIS_REST_TOKEN"),
                         int(secret("DEMO_DAILY_REQUESTS",24)))
        st.session_state.demo_calls+=1
    return k

def safe_error(exc):
    if isinstance(exc,(ValueError,RuntimeError)):
        st.error(str(exc)[:260])
    else:st.error(f"요청 처리 실패 ({type(exc).__name__}). 모델 접근권한, API 설정과 요청 한도를 확인하세요.")

def logged(usage):
    st.session_state.usage_log.append(usage)

def generated_for_current_upload(records, count, mode, overrides=None):
    """Auto-generate drafts; API mode is opt-in and session-only."""
    drafts,classes=local_drafts(records, count, overrides=overrides)
    warnings=[]
    if mode != "원문 발췌 (무료)":
        vendor="GPT" if mode.startswith("GPT") else "Gemini"
        if access_type != "내 API 키 사용":
            warnings.append("운영자 무료 체험에서는 자동생성을 원문 발췌로 제한합니다.")
        elif not (st.session_state.approval and st.session_state.consent):
            warnings.append("외부 API 동의가 없어 원문 발췌 방식으로 생성했습니다.")
        elif any(detect_sensitive(r.get('text','')) for r in records):
            warnings.append("민감정보 의심 패턴이 있어 원문을 외부 AI에 전송하지 않았습니다.")
        elif not key_of(vendor):
            warnings.append(f"{vendor} API 키가 없어 원문 발췌 방식으로 생성했습니다.")
        else:
            key=key_of(vendor)
            model=gpt_model if vendor=="GPT" else gemini_model
            def invoke(prompt):
                if vendor=="GPT":
                    text,usage,_=openai_text(key,model,prompt,json_mode=True)
                else:
                    text,usage,_=gemini_text(key,model,prompt,json_mode=True)
                return text,usage
            # Bound the number of AI calls and the maximum case count.
            drafts,classes,usages,warnings=generate_ai_drafts(records,min(count,12),invoke,overrides=overrides)
            for usage in usages:logged(usage)
    return drafts,classes,warnings


def set_dataset(drafts, source, classes, warnings):
    st.session_state.datasets=drafts
    st.session_state.dataset_source=source
    st.session_state.dataset_fingerprint=""
    st.session_state.auto_file_classes=classes
    st.session_state.auto_domain=classes[0].domain if classes else "기타"
    st.session_state.auto_warnings=warnings
    st.session_state.dataset_revision+=1
    st.session_state.selected_case={}
    st.session_state.selected_case_id=""
    st.session_state.dataset_reference_confirmed=False
    st.session_state.manual_reference_verified_sig=""


def manual_reference_verified(question):
    text=st.session_state.get('manual_reference','').strip()
    signature=hashlib.sha256((question.strip()+"\x00"+text).encode('utf-8')).hexdigest()
    return bool(text) and st.session_state.get('manual_reference_verified_sig')==signature

def make_report(target,answer,question,rubric,scope,web_data=None,case=None,*,
                judges_selected=None,ragas_config=None):
    case=case or {}
    judges_selected=list(judges_selected or [])
    ragas_config=ragas_config or {}
    clean_q=redact_pii(question)
    docs=redact_records(find_evidence(st.session_state.records,clean_q,limit=10))
    if not docs:raise ValueError("연관된 문서 근거를 찾지 못했습니다. 원본 근거 파일을 추가하세요.")
    material=format_evidence(docs)
    web_summary,urls=web_data if web_data else ("",[])
    # Only the dataset reference for the EXACT SAME question is a valid candidate reference.
    reference=redact_pii(case.get("reference_answer", "")) if case.get("question", "").strip()==question.strip() else ""
    report={
        "timestamp":datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "case_id":case.get("case_id",""),"domain":case.get("domain",service_domain),
        "category":case.get("category",""),"service_type":case.get("service_type",service_kind),
        "expected_behavior":case.get("expected_behavior",""),"reference_answer":reference,
        "question":clean_q,"answer":redact_pii(answer),"target":target,"mode":scope,"sources":docs,
        "web_urls":urls,"judges":{},"selected_judges":judges_selected,"disagreements":[],"ragas":{}}
    # RAGAS LLM evaluator is independent from the optional judge checkboxes.
    ragas_key=""
    if ragas_config.get("llm") and any(m in RAGAS_LLM for m in ragas_config.get("metrics", [])):
        ragas_key=preflight("GPT")  # OpenAI LLM for RAGAS metrics, NOT GPT rubric judge.
    with st.spinner(f"{target} · 정식 RAGAS 지표 계산 중"):
        report["ragas"]=run_ragas(
            clean_q,redact_pii(answer),[d["text"] for d in docs],reference=reference,
            use_llm=bool(ragas_config.get("llm",False)),api_key=ragas_key,
            model=ragas_config.get("model","gpt-4o-mini"),
            embedding_model=ragas_config.get("embedding_model","text-embedding-3-small"),
            enabled_metrics=ragas_config.get("metrics",list(RAGAS_NON_LLM)),
        )
    if ragas_key:
        logged({"vendor":"RAGAS / OpenAI","model":ragas_config.get("model","gpt-4o-mini"),
                "input_tokens":0,"output_tokens":0,"estimated_usd":None,
                "note":"RAGAS 내부 호출 횟수·임베딩 비용은 별도 미집계"})
    for judge in judges_selected:
        with st.spinner(f"{target} · {judge} 독립 평가 중"):
            try:
                k=preflight(judge)
                ev,u=evaluate(judge,k,gpt_model if judge=="GPT" else gemini_model,clean_q,
                              redact_pii(answer),material,docs,web_summary,urls,rubric,
                              expected_behavior=redact_pii(case.get("expected_behavior","")))
                report["judges"][judge]=ev; logged(u)
            except Exception as e:safe_error(e)
    if len(report["judges"])==2:
        report["disagreements"]=judges_disagree(report["judges"]["GPT"],report["judges"]["Gemini"])
    report["assessment_status"]=merge_assessment_status(report["ragas"],report["judges"])
    return report

initialize()
st.info("평가 결과는 ① RAGAS 지표 ② 선택한 GPT/Gemini 심사점수 ③ 안전성·신뢰성 관리통제 ④ 잔여위험으로 구분합니다. 점수의 단위와 의미가 달라 합산하지 않습니다. 금융보안원 공식 인증이 아닙니다.")

with st.sidebar:
    st.markdown("### AI 서비스 평가 설정")
    service_name=st.text_input("서비스명",value="AI 답변 검증 시범서비스",max_chars=80)
    service_domain=st.selectbox("서비스 도메인", list(DOMAINS),
        index=list(DOMAINS).index(st.session_state.auto_domain),
        key="service_domain_"+st.session_state.file_fingerprint[:10])
    st.caption("파일 업로드 시 자동 분류됩니다. 필요하면 직접 변경하세요.")
    auto_case_count=st.slider("자동 생성할 평가 사례 수",min_value=4,max_value=12,value=10,step=2)
    auto_mode=st.selectbox("데이터셋 자동 생성 방식",
           ["원문 발췌 (무료)","GPT 질문·정답 초안 생성 (API 비용)","Gemini 질문·정답 초안 생성 (API 비용)"],
           help="무료 모드는 원문을 그대로 발췌하여 질문·답변 초안을 만듭니다. GPT/Gemini는 사용자 API 키와 외부 전송 동의가 필요합니다.")
    service_kind=st.selectbox("주요 AI 유형",["RAG","LLM","Agent","판단형 AI"])
    st.divider()
    access_type=st.radio("API 사용 방식",["내 API 키 사용"]+(["운영자 무료 체험"] if demo_enabled() else []))
    if access_type=="내 API 키 사용":
        st.text_input("OpenAI API 키",type="password",key="openai_personal_key",placeholder="sk-...")
        st.text_input("Gemini API 키",type="password",key="gemini_personal_key")
    else:st.caption("운영자 체험은 2회 평가 호출까지만 허용됩니다. 서비스 전체 무료 제공이 아닙니다.")
    gpt_model=st.selectbox("GPT 심사/생성 모델",["gpt-4o-mini","gpt-4.1-mini","gpt-6-luna"],index=0)
    gemini_model=st.selectbox("Gemini 심사/생성 모델",["gemini-3.5-flash-lite","gemini-3.8-flash","gemini-2.5-flash"],index=0)
    st.checkbox("외부 전송 승인된 공개·가상 자료만 사용합니다.",key="approval")
    st.checkbox("자료·질문·답변의 외부 AI API 전송에 동의합니다.",key="consent")
    st.warning("내부 전용 버전 주의: 비공개 금융자료·개인정보는 업로드하지 마세요.")
    st.caption(f"이번 세션 AI 호출: {len(st.session_state.usage_log)}건")
    cost=[u.get("estimated_usd") for u in st.session_state.usage_log if u.get("estimated_usd") is not None]
    if cost:st.caption(f"OpenAI 텍스트 예상 비용 일부: ${sum(cost):.5f} (검색·Gemini 제외)")
    if st.button("현재 API 키 초기화"):
        for k in ("openai_personal_key","gemini_personal_key"):st.session_state.pop(k,None)
        st.rerun()

file_tab,data_tab,qa_tab,judge_tab,assure_tab,risk_tab,dash_tab,export_tab=st.tabs([
    "① 근거파일", "② 평가 데이터셋", "③ 질문·답변", "④ 답변 자동평가",
    "⑤ 안전성·신뢰성", "⑥ 잔여위험", "⑦ 결과 대시보드", "⑧ 보고서"
])

with file_tab:
    st.subheader("원본 파일 등록 및 근거 추적")
    st.caption("PDF·DOCX·XLSX·CSV·TXT·PPTX, 파일당 8MB / 총 16MB / 최대 6개. 스캔 이미지 OCR은 포함하지 않습니다.")
    uploads=st.file_uploader("외부 전송이 승인된 평가 근거 파일만 업로드하세요",type=["pdf","docx","xlsx","csv","txt","pptx"],accept_multiple_files=True)
    if uploads:
        raw=[(x.name,x.getvalue()) for x in uploads]
        sha=hashlib.sha256(b"".join(name.encode()+hashlib.sha256(b).digest() for name,b in raw)).hexdigest()
        if sha!=st.session_state.file_fingerprint:
            try:
                doc_records,notices=parse_uploads(raw)
                st.session_state.domain_overrides={}
                st.session_state.records,st.session_state.notices=doc_records,notices
                st.session_state.answers={}
                drafts,classes,warnings=generated_for_current_upload(doc_records,auto_case_count,auto_mode)
                set_dataset(drafts,"업로드 문서 자동생성 초안",classes,warnings)
                st.session_state.file_fingerprint=sha
                st.session_state.autodata_source_sha=sha
                st.rerun()
            except Exception as e:st.session_state.records=[];safe_error(e)
    elif st.session_state.file_fingerprint:
        st.session_state.file_fingerprint="";st.session_state.records=[];st.session_state.answers={}
        st.session_state.autodata_source_sha="";st.session_state.auto_file_classes=[]
        st.session_state.domain_overrides={}
        st.session_state.datasets=[];st.session_state.selected_case={}
        st.session_state.auto_domain="기타";st.session_state.dataset_source="원본 파일 없음"
    records=st.session_state.records
    if records:
        names=sorted({r['file'] for r in records})
        c1,c2,c3=st.columns(3)
        c1.metric("파일 수",len(names));c2.metric("검색 단락",len(records));c3.metric("문자 수",f"{sum(len(r['text']) for r in records):,}")
        for x in st.session_state.notices:st.warning(x)
        private=sorted({label for r in records for label in detect_sensitive(r['text'])})
        if private:st.error("민감정보 의심 항목: "+", ".join(private)+". 자동 마스킹으로 모든 유출 위험을 제거할 수 없습니다.")
        st.markdown("#### 업로드 문서별 자동 도메인 분류")
        classes=st.session_state.auto_file_classes or classify_documents(records)
        st.dataframe(pd.DataFrame([{"파일명":c.filename,"자동 분류":c.domain,
            "추정 신뢰도(규칙 점수)":f"{c.confidence:.0%}",
            "분류 단서":", ".join(c.reasons[:3])} for c in classes]),
            hide_index=True,use_container_width=True)
        st.caption("분류 신뢰도는 통계적 확률이 아닌 규칙 기반 점수입니다. 혼합 문서는 도메인을 직접 수정할 수 있습니다.")
        if st.session_state.dataset_source=="업로드 문서 자동생성 초안":
            st.success(f"평가 데이터셋 초안 {len(st.session_state.datasets)}건이 자동 생성되었습니다. ② 탭에서 검토·확정하세요.")
        for warning in st.session_state.auto_warnings:st.warning(warning)
        st.dataframe(pd.DataFrame([{"파일명":n,"단락":sum(r['file']==n for r in records)} for n in names]),hide_index=True,use_container_width=True)
        picked=st.selectbox("근거 원문 보기",[r['id'] for r in records[:150]])
        hit=next(r for r in records if r['id']==picked)
        st.caption(f"{hit['file']} · {hit['location']}");st.code(hit['text'][:2000],language=None)
    else:st.info("샘플 공개 규정 TXT 또는 공개 문서 파일을 업로드해 시작할 수 있습니다.")

with data_tab:
    st.subheader("도메인 자동분류 · 평가 데이터셋 자동생성")
    st.write("① 파일을 업로드하면 도메인과 평가 질문·원문발췌 답변 초안이 자동 생성됩니다. ② 초안은 사용자가 검토해야 RAGAS 정답으로 활용합니다.")
    if st.session_state.records:
        st.caption("자동 분류: " + ", ".join(f"{c.filename} → {c.domain}" for c in st.session_state.auto_file_classes))
        with st.expander("파일별 도메인 분류 수정 (선택)"):
            current_overrides={}
            for cls in st.session_state.auto_file_classes:
                options=list(DOMAINS)
                chosen_domain=st.selectbox(f"{cls.filename} 분류 변경",options,
                    index=options.index(cls.domain),
                    key="domain_override_"+hashlib.sha256((cls.filename+st.session_state.file_fingerprint).encode()).hexdigest()[:16])
                if chosen_domain!=cls.domain:current_overrides[cls.filename]=chosen_domain
            st.session_state.domain_overrides=current_overrides
            if current_overrides:st.info("아래 '다시 생성' 버튼을 누르면 변경한 도메인의 평가 질문 유형이 적용됩니다.")
        if st.button("현재 업로드 파일로 데이터셋 다시 생성",help="설정된 생성 방식·문항 수 및 선택한 도메인을 적용하며 기존 데이터셋을 교체합니다."):
            with st.spinner("문서별 데이터셋 초안 생성 중"):
                try:
                    drafts,classes,warnings=generated_for_current_upload(st.session_state.records,auto_case_count,auto_mode,
                                                                           st.session_state.domain_overrides)
                    set_dataset(drafts,"업로드 문서 자동생성 초안",classes,warnings)
                    st.rerun()
                except Exception as exc:safe_error(exc)
    else:
        st.info("먼저 ① 근거파일 탭에서 문서를 업로드하세요. 원문이 없으면 자동 분류·초안 생성이 불가능합니다.")
    with st.expander("기존 CSV·Excel 평가 데이터셋 수동 등록 / 샘플 불러오기"):
        st.download_button("데이터셋 CSV 템플릿",template_csv(),"evaluation_dataset_template.csv","text/csv")
        dataset_upload=st.file_uploader("CSV 또는 Excel 업로드",type=["csv","xlsx"],key="dataset_upload")
        if dataset_upload:
            data=dataset_upload.getvalue();sha=hashlib.sha256(data).hexdigest()
            if sha!=st.session_state.dataset_fingerprint:
                try:
                    st.session_state.datasets=parse_dataset(dataset_upload.name,data)
                    st.session_state.dataset_source=dataset_upload.name
                    st.session_state.dataset_fingerprint=sha
                    st.session_state.dataset_revision+=1
                    st.session_state.selected_case={}
                    st.success(f"{len(st.session_state.datasets)}건 데이터셋을 불러왔습니다. 검토 상태는 초기화되었습니다.")
                except Exception as e:safe_error(e)
        if st.button("공개 가상 샘플로 초기화"):
            st.session_state.datasets=[{**r,"review_status":"검토 필요"} for r in SAMPLE_CASES]
            st.session_state.dataset_fingerprint="";st.session_state.dataset_source="공개 가상 샘플"
            st.session_state.dataset_revision+=1
            st.rerun()
    cases=st.session_state.datasets
    st.caption(f"데이터셋: {st.session_state.dataset_source} · {len(cases)}건 · 저장 위치: 현재 브라우저 세션")
    if cases:
        total_confirmed=sum(1 for row in cases if row.get('review_status')=='확정')
        c1,c2,c3=st.columns(3)
        c1.metric("전체",len(cases));c2.metric("원문 검토·확정",total_confirmed);c3.metric("검토 필요",len(cases)-total_confirmed)
        st.markdown("#### 평가 초안 확인 · 직접 편집")
        st.caption("질문과 기준답변을 수정할 수 있습니다. 수정하면 해당 사례는 다시 '검토 필요'가 됩니다. 출처 정보는 변경하지 않도록 보호합니다.")
        column_names=["case_id","domain","service_type","category","question","reference_answer",
                      "expected_behavior","context","candidate_answer","source_id","source_quote","source_file","source_location","review_status","generation_method"]
        table=pd.DataFrame([{k:str(r.get(k,'') or '') for k in column_names} for r in cases])
        edited=st.data_editor(table,hide_index=True,num_rows="fixed",use_container_width=True,
                   disabled=["case_id","context","source_id","source_quote","source_file","source_location","review_status","generation_method"],
                   key=f"dataset_editor_{st.session_state.dataset_revision}",height=330,
                   column_config={"question":st.column_config.TextColumn("평가 질문",width="large"),
                                  "reference_answer":st.column_config.TextColumn("기준답변 초안",width="large"),
                                  "review_status":st.column_config.TextColumn("검토 상태")})
        if st.button("편집 내용 저장",key="save_dataset_edits"):
            changed=0
            for row,newrow in zip(cases,edited.to_dict('records')):
                for key in ("domain","service_type","category","question","reference_answer","expected_behavior","candidate_answer"):
                    v=str(newrow.get(key,'') or '').strip()[:3500]
                    if v!=str(row.get(key,'') or ''):
                        row[key]=v;row['review_status']='검토 필요';changed+=1
            if changed:
                st.session_state.dataset_revision+=1
                st.session_state.dataset_reference_confirmed=False
                st.session_state.selected_case={}
                st.success(f"{changed}개 항목을 저장했습니다. 변경된 사례는 다시 검토해 주세요.")
                st.rerun()
            else:st.info("변경된 내용이 없습니다.")
        st.divider()
        f1,f2,f3=st.columns(3)
        types=["전체"]+sorted(set(r.get('service_type','') for r in cases))
        domains=["전체"]+sorted(set(r.get('domain','') for r in cases))
        categories=["전체"]+sorted(set(r.get('category','') for r in cases))
        typ=f1.selectbox("AI 유형",types,key="dataset_type")
        dm=f2.selectbox("업무 도메인",domains,key="dataset_domain")
        ct=f3.selectbox("평가 분류",categories,key="dataset_category")
        filtered=[c for c in cases if (typ=="전체" or c.get('service_type')==typ) and
                  (dm=="전체" or c.get('domain')==dm) and (ct=="전체" or c.get('category')==ct)]
        sensitive=sorted({tag for row in cases for tag in detect_sensitive(" ".join(str(v) for v in row.values()))})
        if sensitive:st.error("개인정보·내부 표시 의심: "+", ".join(sensitive)+". 외부 전송 전 확인하세요.")
        if filtered:
            # Use stable ID labels because Streamlit cannot hash dicts consistently.
            pick=st.selectbox("검토할 케이스",[r['case_id'] for r in filtered],key="chosen_auto_case_id")
            row=next(r for r in filtered if r['case_id']==pick)
            st.markdown("**질문**");st.write(row['question'])
            st.markdown("**기준답변 초안**");st.write(row.get('reference_answer',''))
            st.markdown("**원문 근거**")
            source_id=row.get('source_id','')
            original=next((r for r in st.session_state.records if r.get('id')==source_id),None)
            if original:
                st.caption(f"{original['file']} · {original['location']} · [{source_id}]")
                st.code(row.get('source_quote') or original['text'][:450],language=None)
                if row.get('source_quote') and ' '.join(row['source_quote'].split()) not in ' '.join(original['text'].split()):
                    st.error("인용문이 현재 원문과 일치하지 않습니다. 이 사례는 확정할 수 없습니다.")
            else:
                st.warning("원본 파일의 자동 근거 ID가 없습니다. 사용자가 직접 원본에서 대조해야 합니다.")
                st.caption(row.get('context','근거 미지정'))
            acknowledged=st.checkbox("원본 문서를 직접 읽고 위 기준답변의 정확성·완전성을 확인했습니다.",
                                      key=f"review_confirm_{st.session_state.dataset_revision}_{pick}")
            cconf,capply=st.columns(2)
            if cconf.button("이 사례의 기준답변 확정",disabled=not acknowledged, use_container_width=True):
                if not row.get('reference_answer','').strip():
                    st.error("기준답변이 비어 있습니다.")
                elif original and row.get('source_quote') and ' '.join(row['source_quote'].split()) not in ' '.join(original['text'].split()):
                    st.error("인용문 검증에 실패했습니다.")
                else:
                    row['review_status']='확정'
                    if st.session_state.selected_case_id==pick:st.session_state.selected_case=row.copy()
                    st.success("현재 사례만 기준답변을 확정했습니다.")
            if capply.button("③ 질문·답변 화면에 가져오기",use_container_width=True):
                st.session_state.selected_case=row.copy()
                st.session_state.selected_case_id=pick
                st.session_state.question=row['question']
                st.session_state.external_response=row.get('candidate_answer','')
                st.session_state.manual_reference=''
                st.session_state.manual_reference_verified_sig=''
                st.rerun()
            st.markdown("#### 평가대상 AI 답변 생성 (선택)")
            st.caption("기준답변과 달리 candidate_answer는 실제 평가를 받는 모델의 응답입니다. 비워둬도 데이터셋으로 저장할 수 있습니다.")
            candidate_vendor=st.selectbox("선택 사례에 답변할 모델",["사용 안 함","GPT","Gemini"],key="candidate_vendor")
            if st.button("이 사례의 AI 답변 생성하여 candidate_answer에 저장",disabled=candidate_vendor=="사용 안 함"):
                try:
                    if access_type != "내 API 키 사용":
                        raise ValueError("운영자 무료 체험에서는 데이터셋 AI 답변 생성을 지원하지 않습니다.")
                    if any(detect_sensitive(r.get('text','')) for r in st.session_state.records):
                        raise ValueError("업로드 자료에 민감정보 의심 패턴이 있어 외부 모델 호출을 중단했습니다.")
                    docs=redact_records(find_evidence(st.session_state.records,redact_pii(row['question']),limit=8))
                    if not docs:raise ValueError("평가 질문 관련 근거가 검색되지 않았습니다.")
                    vendor=candidate_vendor
                    with st.spinner("평가대상 AI 답변을 생성하고 있습니다"):
                        txt,usage=generated_answer(vendor,preflight(vendor),gpt_model if vendor=="GPT" else gemini_model,
                             redact_pii(row['question']),format_evidence(docs))
                        row['candidate_answer']=txt[:3500]
                        logged(usage)
                        st.session_state.dataset_revision+=1
                        st.session_state.answers[vendor]=txt
                        st.session_state.selected_case=row.copy()
                        st.session_state.selected_case_id=pick
                    st.rerun()
                except Exception as exc:safe_error(exc)
            st.markdown("**평가 케이스 다운로드**")
            down1,down2=st.columns(2)
            down1.download_button("CSV 내려받기",dataset_csv_bytes(cases),"auto_evaluation_dataset.csv","text/csv",use_container_width=True)
            down2.download_button("Excel 내려받기",dataset_excel_bytes(cases),"auto_evaluation_dataset.xlsx",
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
        else:
            st.info("선택한 필터에 해당하는 평가 케이스가 없습니다.")

with qa_tab:
    st.subheader("AI 답변 생성·등록")
    case=st.session_state.selected_case
    if case:st.caption("적용된 데이터셋: "+case.get('case_id','')+" · "+case.get('category',''))
    question=st.text_area("사용자 질문",key="question",height=120,max_chars=2800)
    external=st.text_area("외부 모델 답변 (붙여넣기)",key="external_response",height=170,max_chars=8500)
    st.markdown("**RAGAS를 위한 검증된 기준 답변 (선택)**")
    st.text_area("기준 답변(reference_answer) 직접 입력",key="manual_reference",height=100,max_chars=4500,
                 help="Factual Correctness 및 비LLM 문자열지표 비교용. 원문으로 확인된 정답만 입력하세요.")
    if st.button("현재 질문·정답을 원본과 대조한 것으로 확정",key="confirm_reference",
                 disabled=not bool(question.strip() and st.session_state.get('manual_reference','').strip())):
        value=st.session_state.manual_reference.strip()
        st.session_state.manual_reference_verified_sig=hashlib.sha256(
            (question.strip()+"\x00"+value).encode('utf-8')).hexdigest()
    st.caption("기준답변 검증 상태: "+("확정 (현재 질문에만 유효)" if manual_reference_verified(question) else "미확정 · RAGAS 정답형 지표에 사용 안 함"))
    if question and detect_sensitive(question):st.warning("질문에 개인정보로 보이는 패턴이 있습니다. 외부 전송하지 않기를 권고합니다.")
    if case:
        with st.expander("데이터셋의 기대답변·기대행동 (참고, 정답 확정 아님)"):
            st.write(case.get('reference_answer') or '미설정')
            st.caption(case.get('expected_behavior',''))
    cols=st.columns(3)
    pressed=[cols[i].button(name,use_container_width=True,disabled=(access_type=="운영자 무료 체험"))
             for i,name in enumerate(["GPT로 답변 생성","Gemini로 답변 생성","두 모델 모두 생성"])]
    if any(pressed):
        try:
            if not st.session_state.records or not question.strip():raise ValueError("원본 파일과 질문이 필요합니다.")
            ev_docs=redact_records(find_evidence(st.session_state.records,redact_pii(question)))
            if not ev_docs:raise ValueError("원본 근거를 찾지 못했습니다.")
            chosen=["GPT"] if pressed[0] else (["Gemini"] if pressed[1] else ["GPT","Gemini"])
            for vendor in chosen:
                with st.spinner(vendor+" 답변 생성 중"):
                    txt,u=generated_answer(vendor,preflight(vendor),gpt_model if vendor=="GPT" else gemini_model,
                                           redact_pii(question),format_evidence(ev_docs))
                    st.session_state.answers[vendor]=txt;logged(u)
            st.success("AI 답변 생성이 완료되었습니다.")
        except Exception as e:safe_error(e)
    for vendor,txt in st.session_state.answers.items():
        with st.expander(f"{vendor} 답변",expanded=True):st.write(txt)

with judge_tab:
    st.subheader("답변 품질 · 정식 RAGAS + 선택형 GPT·Gemini 심사")
    st.markdown('<span class="pill">품질점수: 100점에 가까울수록 좋음</span>',unsafe_allow_html=True)
    mode=st.radio("근거 범위",["업로드 파일만","업로드 파일 + 웹 검색"],horizontal=True,
                  disabled=access_type=="운영자 무료 체험")
    if mode=="업로드 파일 + 웹 검색":
        st.caption("웹 검색은 OpenAI API를 통해 수행합니다. GPT 별도 심사 OFF와 무관하게 웹 검색 API 키가 필요합니다.")
    profile=st.selectbox("평가 프로파일",list(QUALITY_PROFILES),index=list(QUALITY_PROFILES).index(st.session_state.profile_selected))
    if profile!=st.session_state.profile_selected:
        st.session_state.profile_selected=profile
        st.session_state.pop('rubric_editor',None)
    st.caption("LLM 심사용 배점입니다. RAGAS 공식 지표(0~1)는 별도 계산하고 LLM 심사점수(0~100)와 합산하지 않습니다.")
    editable=st.data_editor(pd.DataFrame(QUALITY_PROFILES[profile]),hide_index=True,num_rows="dynamic",key="rubric_editor",
                            use_container_width=True,
                            column_config={"항목":st.column_config.TextColumn("평가항목",required=True),
                                           "배점":st.column_config.NumberColumn("배점",min_value=0,max_value=100,step=1)})
    try:
        rubric=normalize_rubric(editable.to_dict('records'))
        st.caption("배점 합계: 100점")
    except ValueError as e:rubric=None;st.warning(str(e))
    st.markdown("#### ① RAGAS 평가 엔진")
    st.caption("RAGAS 0.4.4 공식 라이브러리. LLM 지표는 OpenAI를 여러 번 호출할 수 있습니다. RAGAS 검색품질 지표는 원 AI 서비스의 검색 성능이 아니라 이 앱의 **질문 기반 파일 검색**을 측정합니다. '웹 검색' 내용은 RAGAS retrieved_contexts에 포함되지 않습니다.")
    ragas_llm=st.checkbox("RAGAS의 LLM 기반 지표 실행 (OpenAI 별도 평가 엔진)",value=False,
                          disabled=access_type=="운영자 무료 체험",key="ragas_llm_switch")
    ragas_model=st.text_input("RAGAS 평가용 OpenAI 모델명",value="gpt-4o-mini",disabled=not ragas_llm,
                              help="GPT 심사 체크 여부와 무관하며, RAGAS 내부에서 OpenAI LLM을 별도로 호출합니다.")
    with st.expander("RAGAS 지표 선택 및 필요조건",expanded=False):
        chosen_ragas=st.multiselect("실행할 RAGAS 지표",list(RAGAS_NON_LLM)+list(RAGAS_LLM),
               default=list(RAGAS_NON_LLM)+["Faithfulness","Factual Correctness"],
               key="ragas_metric_choice")
        st.dataframe(pd.DataFrame([{"지표":m,"필요조건":ragas_metric_requirements(m)} for m in
             list(RAGAS_NON_LLM)+list(RAGAS_LLM)]),hide_index=True,use_container_width=True)
    st.checkbox("② 탭에서 개별 확정한 기준답변을 RAGAS 정답형 지표에 사용",key="dataset_reference_confirmed",
                help="해당 사례의 'review_status=확정'과 이 확인을 모두 충족할 때에만 reference_answer를 평가에 전달합니다.")
    st.markdown("#### ② LLM-as-a-Judge 평가자 선택")
    col_j1,col_j2=st.columns(2)
    use_gpt=col_j1.checkbox("GPT로 별도 심사",value=True,key="judge_gpt_switch")
    use_gemini=col_j2.checkbox("Gemini로 별도 심사",value=True,key="judge_gemini_switch")
    chosen_judges=selected_judges(use_gpt,use_gemini)
    st.caption("현재 선택: "+(" + ".join(chosen_judges) if chosen_judges else "독립 심사모델 없음 (RAGAS만 실행)"))
    if not chosen_judges and not chosen_ragas:
        st.warning("평가 모델과 RAGAS 지표가 모두 꺼져 있어 실행 가능한 평가가 없습니다.")
    if ragas_llm and not key_of("GPT"):
        st.warning("RAGAS LLM 지표는 별도 OpenAI API 키가 필요합니다. Gemini 단독 심사를 선택하더라도 이 키가 필요합니다.")
    if not ragas_llm and any(m in RAGAS_LLM for m in chosen_ragas):
        st.info("RAGAS LLM 실행을 끈 상태입니다. 선택된 LLM 기반 지표는 '미실시'로 기록됩니다.")
    candidates={f"{k} 생성 답변":v for k,v in st.session_state.answers.items() if v.strip()}
    if st.session_state.external_response.strip():candidates['외부 입력 답변']=st.session_state.external_response
    targets=st.multiselect("평가 대상 답변",list(candidates),default=list(candidates)[:2])
    if access_type=="운영자 무료 체험":
        targets=[t for t in targets if t=='외부 입력 답변']
        st.caption("운영자 무료 체험: 외부 답변 1건에 대해 GPT·Gemini 각각 1회 평가, 웹 검색 불가")
    if not chosen_judges and not ragas_llm and not manual_reference_verified(st.session_state.question) and not (
            st.session_state.get('dataset_reference_confirmed') and (st.session_state.selected_case or {}).get('review_status')=='확정'):
        st.warning("GPT·Gemini 미선택 + RAGAS LLM 미사용 상태에서는 검증된 기준 답변을 입력해야 계산 가능한 정량 지표가 생깁니다.")
    if st.button("선택한 답변의 평가 실행",type="primary",use_container_width=True):
        try:
            if rubric is None and chosen_judges:raise ValueError("LLM 심사 배점 합계를 100점으로 설정해 주세요.")
            if not chosen_judges and not chosen_ragas:raise ValueError("RAGAS 지표 또는 LLM 심사모델을 한 개 이상 선택하세요.")
            if not st.session_state.records or not st.session_state.question.strip():raise ValueError("원본 근거 파일과 질문이 필요합니다.")
            if not targets:raise ValueError("평가 대상 답변을 선택하세요.")
            if access_type=="운영자 무료 체험" and (len(targets)!=1 or st.session_state.reports):
                raise ValueError("운영자 무료 체험은 한 세션에서 한 건만 평가합니다.")
            web_data=("",[])
            if mode=="업로드 파일 + 웹 검색":
                with st.spinner("웹 검색 결과 요약 조회 중"):
                    s,urls,u=web_evidence(preflight('GPT'),gpt_model,redact_pii(st.session_state.question))
                    web_data=(s,urls);logged(u)
            for target in targets:
                active_case=st.session_state.selected_case if (st.session_state.selected_case and
                    st.session_state.selected_case.get('question')==st.session_state.question) else {}
                # User-supplied reference must be explicitly confirmed for the exact question.
                if not (st.session_state.get('dataset_reference_confirmed') and active_case.get('review_status')=='확정'):
                    active_case={**active_case,"reference_answer":""}
                if manual_reference_verified(st.session_state.question):
                    active_case={**active_case,"question":st.session_state.question,
                                 "reference_answer":st.session_state.manual_reference.strip()}
                report=make_report(target,candidates[target],st.session_state.question,rubric,mode,
                                   web_data,active_case,judges_selected=chosen_judges,
                                   ragas_config={"llm":ragas_llm,"model":ragas_model,"metrics":chosen_ragas})
                st.session_state.reports.insert(0,report)
            st.success("평가 실행을 종료했습니다. 미실시·실패 지표는 대시보드에서 별도로 확인하세요.")
        except Exception as e:safe_error(e)
    st.divider()
    with st.expander("데이터셋으로 배치 평가 (개인 API 키 / 최대 3건)"):
        st.caption("평가대상답변(candidate_answer)이 있는 사례만 평가합니다. GPT/Gemini 체크에 따라 호출 수가 달라지며 RAGAS LLM 지표는 별도 과금됩니다.")
        ready=[c for c in st.session_state.datasets if c.get('candidate_answer') and c.get('question')]
        batch=st.multiselect("배치 평가 사례ID",[r['case_id'] for r in ready],max_selections=3)
        confirmed=st.checkbox("모델 API 비용이 발생함을 확인하고 배치평가를 실행합니다.")
        if st.button("선택 사례 배치 평가",disabled=not confirmed):
            try:
                if access_type!="내 API 키 사용":raise ValueError("배치 평가는 개인 API 사용 방식에서만 가능합니다.")
                if (not rubric and chosen_judges) or not batch or not st.session_state.records:raise ValueError("배점·사례·원본 근거 파일을 확인하세요.")
                for cid in batch:
                    c=next(r for r in ready if r['case_id']==cid)
                    source_case=c if (st.session_state.get('dataset_reference_confirmed') and c.get('review_status')=='확정') else {**c,'reference_answer':''}
                    r=make_report('데이터셋 대상 답변',c['candidate_answer'],c['question'],rubric,'업로드 파일만',case=source_case,
                                  judges_selected=chosen_judges,
                                  ragas_config={"llm":ragas_llm,"model":ragas_model,"metrics":chosen_ragas})
                    st.session_state.reports.insert(0,r)
                st.success("데이터셋 배치 평가를 완료했습니다.")
            except Exception as e:safe_error(e)

with assure_tab:
    st.subheader("금융 AI 안전성·신뢰성 · 5+5개 영역 / 28개 점검항목")
    st.caption(FRAMEWORK_SOURCE)
    st.warning("점검 결과는 평가자가 증적을 검토하여 입력합니다. AI 답변이 좋다는 이유로 이 28개 항목을 자동 합격 처리하지 않습니다.")
    try:
        summary=controls_summary(st.session_state.framework_rows)
        c1,c2,c3,c4=st.columns(4)
        c1.metric("점검완료",f"{summary['reviewed']}/{summary['applicable']}")
        c2.metric("충족",summary['fully_met']);c3.metric("부분충족",summary['partly_met']);c4.metric("미충족",summary['unmet'])
    except Exception as e:st.error(str(e))
    part=st.radio("평가계층",["안전성","신뢰성","전체"],horizontal=True)
    view=[r for r in st.session_state.framework_rows if part=='전체' or r['평가계층']==part]
    status_map={r['id']:r for r in st.session_state.framework_rows}
    display=[{k:r.get(k,'') for k in ['id','평가계층','평가영역','평가항목','확인방법','필요증적','상태','증적','판단사유']} for r in view]
    edited=st.data_editor(pd.DataFrame(display),hide_index=True,use_container_width=True,disabled=['id','평가계층','평가영역','평가항목','확인방법','필요증적'],
        key=f"assurance_editor_{part}",column_config={"상태":st.column_config.SelectboxColumn("상태",options=['미평가','충족','부분충족','미충족','해당없음'],required=True),
                 "증적":st.column_config.TextColumn("증적 식별자/검토 내용",max_chars=500),
                 "판단사유":st.column_config.TextColumn("판정사유 및 개선권고",max_chars=700)})
    if st.button("28개 관리통제 평가내용 저장",type="primary"):
        try:
            merged={r['id']:dict(r) for r in st.session_state.framework_rows}
            for rec in edited.to_dict('records'):
                merged[rec['id']].update({k:str(rec.get(k) or '') for k in ['상태','증적','판단사유']})
            new=list(merged.values());controls_summary(new)
            st.session_state.framework_rows=new
            st.success("평가자 입력·증적 내용이 현재 세션에 저장되었습니다.")
        except Exception as e:safe_error(e)
    with st.expander("원문 활용 위치 및 평가 원칙"):
        st.write("첨부 발표자료 24~29쪽의 10개 영역·28개 항목 이름을 반영하고, 확인방법·필요증적은 서비스 개발을 위해 실무형으로 구체화했습니다.")
        st.write("'충족/부분충족'에는 실제 증적 기재 필수. '해당없음'에는 판단사유 필수. 미평가 상태에서는 전체 적합 판정을 내리지 않습니다.")
        st.write("공정성은 개인별 판단형 모델에서 집단/결과 데이터가 필요합니다. 단일 챗봇 응답만으로 점수화하지 않습니다.")

with risk_tab:
    st.subheader("AI 서비스 잔여위험 · 4부문 / 16항목 / 100점")
    st.markdown('<span class="pill">잔여위험 점수: 높을수록 위험</span>',unsafe_allow_html=True)
    st.caption(RISK_SOURCE)
    st.info("미이행 100% · 부분이행 50% · 완료 0%로 산정하는 워크북의 참고 모델입니다. 항목 증적이 빠지면 등급을 판정하지 않습니다.")
    hf=st.checkbox("고영향 AI 해당 여부가 별도 검토로 확정됨 (자동 법적 판정 아님)",key="high_impact")
    ff=st.checkbox("금융안정성 훼손 우려가 확인됨",key="financial_stability")
    edited_risk=st.data_editor(pd.DataFrame(st.session_state.risk_rows),hide_index=True,use_container_width=True,
        disabled=['id','부문','항목','배점'],key='risk_editor',
        column_config={"경감수준":st.column_config.SelectboxColumn("경감수준",options=['미평가','미이행','부분이행','완료'],required=True),
                       "증적":st.column_config.TextColumn("완화조치 증적",max_chars=500),
                       "판단사유":st.column_config.TextColumn("위험판정/미비점",max_chars=700)})
    if st.button("16개 잔여위험 평가내용 저장",type="primary"):
        st.session_state.risk_rows=edited_risk.to_dict('records')
        st.success("평가내용이 현재 세션에 저장되었습니다.")
    risk=calculate_residual_risk(st.session_state.risk_rows,hf,ff)
    a,b,c=st.columns(3)
    a.metric("위험점수",f"{risk['score']}/100" if risk['score'] is not None else '산정 보류')
    b.metric("위험등급",risk['grade']);c.metric("미평가/증적미비 항목",len(risk['missing']))
    if risk['missing']:st.warning(f"누락 항목: {', '.join(risk['missing'])}. 전체 위험판정 보류.")
    elif risk['parts']:
        st.bar_chart(pd.DataFrame([{'부문':k,'잔여위험점수':v} for k,v in risk['parts'].items()]).set_index('부문'))
    with st.expander("위험등급 판단 기준(참고용)"):
        st.write("0~24.9점 저위험 / 25~49.9점 중위험 / 50~74.9점 고위험 / 75점 이상 출시 재검토. 고영향 확정시 고위험 이상, 금융안정성 우려 시 출시 재검토.")
        st.caption("이는 첨부 워크북의 예시 배점과 구간입니다. 금융회사의 승인된 위험관리 기준과 동일하다고 가정하지 마세요.")

with dash_tab:
    st.subheader("평가 결과 · 객관적 비교 대시보드")
    controls=controls_summary(st.session_state.framework_rows)
    risk=calculate_residual_risk(st.session_state.risk_rows,st.session_state.get('high_impact',False),st.session_state.get('financial_stability',False))
    x,y,z=st.columns(3)
    x.metric("평가한 답변",len(st.session_state.reports))
    y.metric("28개 통제 점검완료",f"{controls['reviewed']}/{controls['applicable']}")
    z.metric("잔여위험",risk['grade'])
    if not st.session_state.reports:
        st.info("답변 평가를 실행하면 모델별 점수·근거 검증·오류 개선권고를 볼 수 있습니다.")
    else:
        items=[f"{i+1}. {r.get('case_id','')} / {r['target']} / {r['timestamp']}" for i,r in enumerate(st.session_state.reports)]
        selected=st.selectbox("평가 결과 선택",range(len(items)),format_func=lambda i:items[i])
        r=st.session_state.reports[selected];judges=r['judges']
        a,b,c,d=st.columns(4)
        a.metric("GPT 평가",f"{judges['GPT']['total']:.1f}" if 'GPT' in judges else '미실시')
        b.metric("Gemini 평가",f"{judges['Gemini']['total']:.1f}" if 'Gemini' in judges else '미실시')
        averages=[j['total'] for j in judges.values()]
        c.metric("LLM 심사 평균",f"{sum(averages)/len(averages):.1f}/100" if averages else '미실시')
        d.metric("재검토 항목",len(r.get('disagreements',[])))
        st.markdown("#### RAGAS 공식 지표 (0~1점 척도)")
        st.caption("RAGAS와 GPT/Gemini의 사용자 정의 점수를 자동으로 합산하지 않습니다. RAGAS LLM 평가는 별도 API 호출입니다.")
        rr=r.get('ragas',{})
        ragas_rows=rr.get('metrics',[])
        if ragas_rows:
            st.dataframe(pd.DataFrame([{
                "RAGAS 지표":v.get('metric',''),"상태":v.get('status',''),
                "점수 (0~1)":v.get('score') if v.get('status')=='완료' else None,
                "계산/미실시 사유":v.get('reason','')
            } for v in ragas_rows]),hide_index=True,use_container_width=True)
            st.caption(f"RAGAS 버전: {rr.get('version','')} / RAGAS LLM: {rr.get('llm_model','미사용') or '미사용'}")
        else:st.info("선택된 RAGAS 지표가 없습니다.")
        for warning in rr.get('warnings',[]):st.warning(warning)
        st.markdown("#### 선택형 GPT·Gemini 심사 (100점 만점)")
        if len(r.get('selected_judges',[]))==2 and len(judges)!=2:
            st.warning("두 모델 심사를 선택했으나 일부 호출이 실패했습니다.")
        elif not r.get('selected_judges'):
            st.info("GPT·Gemini의 LLM-as-a-Judge 평가를 실행하지 않았습니다 (사용자 선택).")
        st.caption("평가 상태: "+r.get('assessment_status','미기록'))
        if r['disagreements']:st.warning("평가자 간 15점 이상 점수차: "+', '.join(r['disagreements']))
        scores=[{"평가지표":s['name'],"평가모델":judge,"점수":s['quality'],"배점":s['weight'],"가중점수":s['weighted'],"판단사유":s['reason']}
                for judge,e in judges.items() for s in e['scores']]
        if scores:
            df=pd.DataFrame(scores)
            st.bar_chart(df.pivot(index='평가지표',columns='평가모델',values='점수'))
            st.dataframe(df,hide_index=True,use_container_width=True)
        for judge,e in judges.items():
            with st.expander(f"{judge} · 주장의 원문 검증 / 개선 권고",expanded=True):
                st.write(e['summary'])
                findings=e.get('findings',[])
                if findings:
                    fd=pd.DataFrame([{"주장":f['claim'],"근거판정":f['status'],"출처ID":','.join(f['source_ids']),
                                      "실제 인용문 일치":'일치' if f['quote_verified'] else '불일치/미확인',
                                      "사유":f['explanation'],"개선권고":f['recommendation']} for f in findings])
                    st.dataframe(fd,hide_index=True,use_container_width=True)
                st.markdown("**개선 제안 답변**")
                st.write(e['improved_answer'])
                st.caption("검증 한계: "+' · '.join(e.get('limitations',[])))
        with st.expander("평가에 실제 사용한 근거 발췌"):
            for source in r['sources']:
                st.markdown(f"**[{source['id']}] {source['file']} / {source['location']}**")
                st.code(source['text'][:1700],language=None)
            for w in r['web_urls']:
                st.write(f"[{w['id']}] {w['title']} · {w['url']}")
        st.caption("주의: RAGAS 문자열 유사도는 사실 정확도를 증명하지 않습니다. 문서 검색 누락·스캔PDF·복잡한 표는 평가의 한계입니다.")
    st.divider()
    st.markdown("#### 서비스 통제 점검 현황")
    stat=pd.DataFrame(st.session_state.framework_rows)
    st.dataframe(stat.groupby(['평가계층','상태']).size().unstack(fill_value=0),use_container_width=True)

with export_tab:
    st.subheader("감사·평가 보고서")
    st.write("답변의 주장별 판정, 28개 관리통제와 증적, 16개 잔여위험 산정, 데이터셋을 하나의 보고서로 제공합니다.")
    service={"서비스명":service_name,"도메인":service_domain,"유형":service_kind,
             "고영향확정":st.session_state.get('high_impact',False),
             "금융안정성우려":st.session_state.get('financial_stability',False)}
    data=professional_report(st.session_state.reports,st.session_state.framework_rows,
                             st.session_state.risk_rows,service,st.session_state.datasets)
    st.download_button("통합 전문 평가보고서 Excel 다운로드",data,"AI_금융AI_전문평가보고서.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
    if st.session_state.reports:
        st.download_button("답변 평가 이력 CSV 다운로드",csv_history(st.session_state.reports),
                           "AI_답변평가_이력.csv","text/csv")
        idx=st.selectbox("단일 답변 상세보고서",range(len(st.session_state.reports)),format_func=lambda i:
                         f"{i+1}. {st.session_state.reports[i]['target']}")
        st.download_button("단일 답변 검증 Excel 다운로드",excel_report(st.session_state.reports[idx]),
                           "AI_단일답변_검증.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if st.button("답변 평가 이력 초기화"):
        st.session_state.reports=[];st.rerun()
    st.warning("평가 이력과 입력내용은 세션 내에서만 보관되며 서비스 차원의 장기 저장·접근통제·로그 보존을 구현하지 않았습니다.")
    st.info("출처: 첨부 금융보안원 발표자료(2026.11.12, 24~29쪽) 및 사용자 제공 AI 서비스 위험평가 워크북. 규정·검증 요건은 실 서비스에 적용하기 전에 공식 최신 원문을 재확인해야 합니다.")

st.divider()
st.caption("AI Answer Auditor PRO v4 · 자동분류·자동데이터셋 · 정식 RAGAS 정량지표 + 선택형 LLM-as-a-Judge · 금융보안원 공식 인증/평가서비스 아님 · 내부 전용 버전 주의")
