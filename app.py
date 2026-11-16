"""AI Answer Auditor PRO v2 · Streamlit Community Cloud entry point."""
from __future__ import annotations
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from auditor.documents import parse_uploads
from auditor.datasets import SAMPLE_CASES, template_csv, parse_dataset, DATASET_CATEGORIES
from auditor.evaluation import evaluate, judges_disagree, normalize_rubric
from auditor.frameworks import (CONTROLS, FRAMEWORK_SOURCE, RISK_SOURCE, RISK_WEIGHTS,
                                controls_summary, calculate_residual_risk)
from auditor.pro_reports import professional_report
from auditor.providers import generated_answer, web_evidence
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
검증 가능한 증적, 독립적인 GPT·Gemini 평가, 도메인 데이터셋, 감사형 보고서</p>
</div>
""", unsafe_allow_html=True)

QUALITY_PROFILES={
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

def make_report(target,answer,question,rubric,scope,web_data=None,case=None):
    case=case or {}
    clean_q=redact_pii(question)
    docs=redact_records(find_evidence(st.session_state.records,clean_q+" "+redact_pii(answer[:500]),limit=10))
    if not docs:raise ValueError("연관된 문서 근거를 찾지 못했습니다. 원본 근거 파일을 추가하세요.")
    material=format_evidence(docs)
    web_summary,urls=web_data if web_data else ("",[])
    report={
        "timestamp":datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "case_id":case.get("case_id",""),"domain":case.get("domain",service_domain),
        "category":case.get("category",""),"service_type":case.get("service_type",service_kind),
        "expected_behavior":case.get("expected_behavior",""),"reference_answer":case.get("reference_answer",""),
        "question":clean_q,"answer":redact_pii(answer),"target":target,"mode":scope,"sources":docs,
        "web_urls":urls,"judges":{},"disagreements":[]}
    for judge in ("GPT","Gemini"):
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
    return report

initialize()
st.info("세 가지 다른 평가입니다. ① 답변 품질은 높을수록 좋음 ② 28개 관리통제는 증적 확인 후 수동 판정 ③ 잔여위험은 높을수록 위험. 이 앱은 공식 금융보안원 인증/적합성 판정을 대체하지 않습니다.")

with st.sidebar:
    st.markdown("### AI 서비스 평가 설정")
    service_name=st.text_input("서비스명",value="AI 답변 검증 시범서비스",max_chars=80)
    service_domain=st.selectbox("서비스 도메인",["금융 고객안내","금융 투자정보","금융 IT·정보보호","금융 내부업무","공공·일반","기타"])
    service_kind=st.selectbox("주요 AI 유형",["RAG","LLM","Agent","판단형 AI"])
    st.divider()
    access_type=st.radio("API 사용 방식",["내 API 키 사용"]+(["운영자 무료 체험"] if demo_enabled() else []))
    if access_type=="내 API 키 사용":
        st.text_input("OpenAI API 키",type="password",key="openai_personal_key",placeholder="sk-...")
        st.text_input("Gemini API 키",type="password",key="gemini_personal_key")
    else:st.caption("운영자 체험은 2회 평가 호출까지만 허용됩니다. 서비스 전체 무료 제공이 아닙니다.")
    gpt_model=st.selectbox("GPT 심사/생성 모델",["gpt-6-luna","gpt-6.1-terra"],index=0)
    gemini_model=st.selectbox("Gemini 심사/생성 모델",["gemini-3.5-flash-lite","gemini-3.8-flash"],index=0)
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
                st.session_state.records,st.session_state.notices=parse_uploads(raw)
                st.session_state.file_fingerprint=sha
                st.session_state.answers={}
            except Exception as e:st.session_state.records=[];safe_error(e)
    elif st.session_state.file_fingerprint:
        st.session_state.file_fingerprint="";st.session_state.records=[];st.session_state.answers={}
    records=st.session_state.records
    if records:
        names=sorted({r['file'] for r in records})
        c1,c2,c3=st.columns(3)
        c1.metric("파일 수",len(names));c2.metric("검색 단락",len(records));c3.metric("문자 수",f"{sum(len(r['text']) for r in records):,}")
        for x in st.session_state.notices:st.warning(x)
        private=sorted({label for r in records for label in detect_sensitive(r['text'])})
        if private:st.error("민감정보 의심 항목: "+", ".join(private)+". 자동 마스킹으로 모든 유출 위험을 제거할 수 없습니다.")
        st.dataframe(pd.DataFrame([{"파일명":n,"단락":sum(r['file']==n for r in records)} for n in names]),hide_index=True,use_container_width=True)
        picked=st.selectbox("근거 원문 보기",[r['id'] for r in records[:150]])
        hit=next(r for r in records if r['id']==picked)
        st.caption(f"{hit['file']} · {hit['location']}");st.code(hit['text'][:2000],language=None)
    else:st.info("샘플 공개 규정 TXT 또는 공개 문서 파일을 업로드해 시작할 수 있습니다.")

with data_tab:
    st.subheader("도메인 평가 데이터셋 관리")
    st.write("산업별 질문·기대행동·평가대상 답변을 등록하고, 같은 기준으로 반복 측정할 사례를 관리합니다.")
    st.download_button("가상 샘플 8건 · 데이터셋 CSV 템플릿",template_csv(),"evaluation_dataset_template.csv","text/csv")
    dataset_upload=st.file_uploader("CSV 또는 Excel 평가 데이터셋 업로드",type=["csv","xlsx"],key="dataset_upload")
    if dataset_upload:
        data=dataset_upload.getvalue();sha=hashlib.sha256(data).hexdigest()
        if sha!=st.session_state.dataset_fingerprint:
            try:
                st.session_state.datasets=parse_dataset(dataset_upload.name,data)
                st.session_state.dataset_source=dataset_upload.name
                st.session_state.dataset_fingerprint=sha
                st.success(f"{len(st.session_state.datasets)}건 데이터셋을 불러왔습니다.")
            except Exception as e:safe_error(e)
    if st.button("공개 가상 샘플로 초기화"):
        st.session_state.datasets=list(SAMPLE_CASES)
        st.session_state.dataset_fingerprint="";st.session_state.dataset_source="공개 가상 샘플"
        st.rerun()
    cases=st.session_state.datasets
    st.caption(f"데이터셋: {st.session_state.dataset_source} · {len(cases)}건 · 서버에 영구 저장하지 않음")
    f1,f2,f3=st.columns(3)
    types=["전체"]+sorted(set(r.get('service_type','') for r in cases))
    domains=["전체"]+sorted(set(r.get('domain','') for r in cases))
    categories=["전체"]+sorted(set(r.get('category','') for r in cases))
    typ=f1.selectbox("AI 유형",types,key="dataset_type")
    dm=f2.selectbox("업무 도메인",domains,key="dataset_domain")
    ct=f3.selectbox("평가 분류",categories,key="dataset_category")
    filtered=[c for c in cases if (typ=="전체" or c['service_type']==typ) and
              (dm=="전체" or c['domain']==dm) and (ct=="전체" or c['category']==ct)]
    any_sensitive=sorted({tag for row in cases for tag in detect_sensitive(" ".join(str(v) for v in row.values()))})
    if any_sensitive:st.error("데이터셋 내 민감정보 의심: "+", ".join(any_sensitive)+". 업로드·외부 전송 전 제거해 주세요.")
    if filtered:
        st.dataframe(pd.DataFrame(filtered),hide_index=True,use_container_width=True)
        choose=st.selectbox("질문·평가에 적용할 테스트 케이스",range(len(filtered)),
                            format_func=lambda i:filtered[i]['case_id']+" | "+filtered[i]['question'][:70])
        selected_case=filtered[choose]
        st.caption("기대답변은 제공자가 정의한 비교 기준이며, 그 자체로 검증된 사실이 아닙니다. 원본 파일에서 다시 검증합니다.")
        if st.button("선택한 케이스를 ③ 질문·답변으로 가져오기",type="primary"):
            st.session_state.selected_case=selected_case
            st.session_state.selected_case_id=selected_case['case_id']
            st.session_state.question=selected_case['question']
            st.session_state.external_response=selected_case.get('candidate_answer','')
            st.rerun()
        st.markdown("**현재 선택된 사례 메타데이터**")
        st.json({k:selected_case[k] for k in ['case_id','domain','service_type','category','expected_behavior']})
    else:st.info("선택한 조건에 맞는 평가 사례가 없습니다.")
    st.caption("분류 예시: "+" · ".join(DATASET_CATEGORIES))

with qa_tab:
    st.subheader("AI 답변 생성·등록")
    case=st.session_state.selected_case
    if case:st.caption("적용된 데이터셋: "+case.get('case_id','')+" · "+case.get('category',''))
    question=st.text_area("사용자 질문",key="question",height=120,max_chars=2800)
    external=st.text_area("외부 모델 답변 (붙여넣기)",key="external_response",height=170,max_chars=8500)
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
    st.subheader("답변 품질 · 모델 간 독립 교차 평가")
    st.markdown('<span class="pill">품질점수: 100점에 가까울수록 좋음</span>',unsafe_allow_html=True)
    mode=st.radio("근거 범위",["업로드 파일만","업로드 파일 + 웹 검색"],horizontal=True,
                  disabled=access_type=="운영자 무료 체험")
    profile=st.selectbox("평가 프로파일",list(QUALITY_PROFILES),index=list(QUALITY_PROFILES).index(st.session_state.profile_selected))
    if profile!=st.session_state.profile_selected:
        st.session_state.profile_selected=profile
        st.session_state.pop('rubric_editor',None)
    st.caption("평가 프로파일은 참고용 설계값입니다. 품질 점수는 LLM 심사자의 추정이며 실제 공식 RAGAS 계산 결과가 아닙니다.")
    editable=st.data_editor(pd.DataFrame(QUALITY_PROFILES[profile]),hide_index=True,num_rows="dynamic",key="rubric_editor",
                            use_container_width=True,
                            column_config={"항목":st.column_config.TextColumn("평가항목",required=True),
                                           "배점":st.column_config.NumberColumn("배점",min_value=0,max_value=100,step=1)})
    try:
        rubric=normalize_rubric(editable.to_dict('records'))
        st.caption("배점 합계: 100점")
    except ValueError as e:rubric=None;st.warning(str(e))
    candidates={f"{k} 생성 답변":v for k,v in st.session_state.answers.items() if v.strip()}
    if st.session_state.external_response.strip():candidates['외부 입력 답변']=st.session_state.external_response
    targets=st.multiselect("평가 대상 답변",list(candidates),default=list(candidates)[:2])
    if access_type=="운영자 무료 체험":
        targets=[t for t in targets if t=='외부 입력 답변']
        st.caption("운영자 무료 체험: 외부 답변 1건에 대해 GPT·Gemini 각각 1회 평가, 웹 검색 불가")
    if st.button("선택한 답변의 GPT × Gemini 독립 평가 실행",type="primary",use_container_width=True):
        try:
            if rubric is None:raise ValueError("배점 합계를 100점으로 설정해 주세요.")
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
                report=make_report(target,candidates[target],st.session_state.question,rubric,mode,
                                   web_data,active_case)
                if report['judges']:st.session_state.reports.insert(0,report)
            st.success("평가가 완료되었습니다. ⑦ 대시보드에서 결과를 확인하세요.")
        except Exception as e:safe_error(e)
    st.divider()
    with st.expander("데이터셋으로 배치 평가 (개인 API 키 / 최대 3건)"):
        st.caption("평가대상답변(candidate_answer)이 들어 있는 사례만 평가합니다. 각 사례당 GPT·Gemini 심사 2회 호출. 웹 검색은 수행하지 않습니다.")
        ready=[c for c in st.session_state.datasets if c.get('candidate_answer') and c.get('question')]
        batch=st.multiselect("배치 평가 사례ID",[r['case_id'] for r in ready],max_selections=3)
        confirmed=st.checkbox("모델 API 비용이 발생함을 확인하고 배치평가를 실행합니다.")
        if st.button("선택 사례 배치 평가",disabled=not confirmed):
            try:
                if access_type!="내 API 키 사용":raise ValueError("배치 평가는 개인 API 사용 방식에서만 가능합니다.")
                if not rubric or not batch or not st.session_state.records:raise ValueError("배점·사례·원본 근거 파일을 확인하세요.")
                for cid in batch:
                    c=next(r for r in ready if r['case_id']==cid)
                    r=make_report('데이터셋 대상 답변',c['candidate_answer'],c['question'],rubric,'업로드 파일만',case=c)
                    if r['judges']:st.session_state.reports.insert(0,r)
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
        c.metric("평균 품질점수",f"{sum(averages)/len(averages):.1f}/100" if averages else '—')
        d.metric("재검토 항목",len(r.get('disagreements',[])))
        if len(judges)!=2:st.warning("모델 한쪽 평가가 실패해 교차평가가 완결되지 않았습니다.")
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
        st.caption("주의: 문서 검색된 단락만 참조하며, 스캔 PDF·복잡한 표·이미지·미검색 구간은 누락될 수 있습니다. 숫자는 AI 평가자의 추정값입니다.")
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
st.caption("AI Answer Auditor PRO v2 · 증적 기반 평가 지원 도구 · 금융보안원 공식 인증/평가서비스 아님 · 내부 전용 버전 주의")
