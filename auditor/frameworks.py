"""Financial AI assurance reference catalogs from user-provided sources.

Source interpretation: 2026-11-12 financial security conference presentation,
24p: 2026-10-21 DRAFT 5 safety/12 items + 5 trust/16 items.
It is NOT an official final certification, and model output is not evidence of controls.
A second risk score is workbook-proposed 4 parts/16 items/100 points, where HIGHER is WORSE.
"""
from __future__ import annotations
from collections import Counter
from typing import Iterable

FRAMEWORK_SOURCE = (
    "금융보안원, 「금융분야 AI 안전성·신뢰성 평가 체계」, 2026-11-12 발표자료 "
    "24~29쪽, 평가기준(안) 2026-10-21 기준. 최종 인증기준이 아님."
)
RISK_SOURCE = (
    "첨부 「AI 서비스 위험평가 워크북」의 4부문·16항목·100점 잔여위험 예시. "
    "원문 RMF와 법령 적용 여부를 별도 확인해야 하며 공식 위험판정이 아님."
)

# ID, 영역, 세부 점검항목, 확인방법, 필요한 증적, 적용 대상
_SAFETY = [
("S01", "AI 보안 정책적 대응", "AI 보안 위협 식별·평가체계", "서비스별 자산·공격경로·피해영향을 목록화하고 위험평가한 기록 확인", "위협모델, 위험평가표, 공격표면 목록", "공통"),
("S02", "AI 보안 정책적 대응", "AI 보안 위협 대응체계", "우선순위별 완화 조치·책임자·기한 및 이행점검 기록 확인", "위험처리계획, 대응절차, 조치완료 증적", "공통"),
("S03", "AI 보안 기술적 대응", "입출력 관리", "입력 필터, 기밀·개인신용정보 출력 차단, 길이제한·업로드 검사 및 예외처리 테스트", "입출력 필터 설정, 개인정보 탐지 결과, 모의점검 기록", "공통"),
("S04", "AI 보안 기술적 대응", "적대적공격 방어", "탈옥·프롬프트 인젝션·데이터 오염에 대한 공격 시나리오 및 방어 성능 확인", "레드티밍 시나리오, 차단률, 재현로그, 시정조치", "생성형/RAG/Agent"),
("S05", "AI 보안 기술적 대응", "모니터링", "입출력·데이터 접근·모델 이상행동 탐지 및 사고 대응 절차 점검", "탐지규칙, 이벤트 로그, 알람 및 대응이력", "공통"),
("S06", "AI 보안 기술적 대응", "에이전트 보안", "도구 호출 최소권한, 승인 게이트, 실행 범위·횟수 제한, 중단 기능 확인", "권한매트릭스, 도구 실행로그, 승인 기록, 중단시험", "Agent"),
("S07", "AI 자산 보호 및 관리", "AI 자산 식별 및 관리", "모델·데이터·벡터DB·도구·API 키의 식별, 버전, 책임자와 접근권한 확인", "AI 인벤토리, 형상관리, 접근권한 점검표", "공통"),
("S08", "외부 리소스 검증", "외부 모델 검증", "반입 모델의 출처·라이선스·해시·안전성·공급자 변경을 검증했는지 확인", "모델 검증서, 무결성 정보, 계약/변경평가", "외부 모델 이용"),
("S09", "외부 리소스 검증", "외부 데이터 검증", "외부 문서의 출처·무결성·오염 가능성 및 업데이트 승인 확인", "데이터 원천목록, 검증규칙, 오염검사 결과", "외부 데이터/RAG"),
("S10", "외부 리소스 검증", "공급망 보안", "라이브러리·모델·도구·API 공급업체의 위험과 변경통제를 검증", "SBOM/구성목록, 공급업체 검토, 취약점 대응", "공통"),
("S11", "기존 보안체계와의 통합", "추가 보안조치", "비밀키 보호, 접근통제, 암호화, 망·개발보안 통제를 AI 서비스로 확대", "비밀관리 정책, 접근통제 설정, 보안점검 결과", "공통"),
("S12", "기존 보안체계와의 통합", "AI 보안 교육", "개발자·운영자·사용자 대상 AI 위험 교육 및 이수 확인", "교육계획, 대상자 목록, 이수 기록", "공통"),
]
_TRUST = [
("T01", "위험관리 및 거버넌스", "조직 구성", "AI 의사결정기구·전담부서·1/2/3선 역할과 책임이 지정되었는가", "조직도, RACI, 위원회 운영기록", "공통"),
("T02", "위험관리 및 거버넌스", "규정 마련", "AI 개발·검증·배포·변경·종료 단계별 정책과 책임 기준 수립 여부", "내규, 운영지침, 개정/승인 기록", "공통"),
("T03", "위험관리 및 거버넌스", "위험관리체계 구성", "서비스별 위험식별·등급·경감·잔여위험 승인·재평가 절차 확인", "위험평가표, 처리계획, 승인 및 재평가 이력", "공통"),
("T04", "위험관리 및 거버넌스", "규제 검토 및 대응", "적용 법규·감독요건 식별과 법률 검토, 후속조치 확인", "법규 매핑표, 준법 의견서, 시정조치", "금융/대고객"),
("T05", "모델 관리", "서비스 성능 평가", "서비스 특성에 맞는 성능지표 선정 근거, 테스트셋, 객관적 평가 수행", "성능지표 정의서, 평가 데이터셋, 시험 성적", "공통"),
("T06", "모델 관리", "성능 기준치 이탈 대응", "임계값 설정, 임계치 이탈 탐지, 조치 및 재시험 기록 확인", "품질 임계값 문서, 모니터링 로그, 장애 대응", "공통"),
("T07", "모델 관리", "환각 완화", "근거 기반 답변 검증·인용 확인·환각률 추적·오류수정 절차 확인", "RAG 평가결과, 환각사례, 근거검증 로그", "생성형/RAG"),
("T08", "모델 관리", "인적 감독 및 통제", "고위험 판단·실행 전 인적 검토, 승인/재정의, 중단·수동전환 확인", "업무 흐름도, 인적승인 로그, kill-switch 시험", "판단형/Agent/대고객"),
("T09", "모델 관리", "서비스 성능 개선", "성능 추세 분석 및 버전별 개선·재평가·회귀시험 확인", "변경관리, 개선계획, 회귀시험/재평가 결과", "공통"),
("T10", "데이터 관리", "데이터 수집·이용·보유·파기", "목적·동의·보유기간·파기·외부전송 적법성 검토", "데이터 흐름도, 처리방침, 동의/파기 증적", "개인/금융정보 취급"),
("T11", "데이터 관리", "데이터 품질 관리", "데이터 정확성·완전성·정합성, 이상치·오염 관리, 품질 변경 추적", "품질규칙, 정합성 점검 결과, 오류처리대장", "공통"),
("T12", "공정성·편향성", "데이터 공정성·편향성 평가", "집단 대표성, 수집/라벨링 편향, 대리변수 위험 점검", "데이터셋 구성표, 편향분석, 표본 적정성", "개인별 판단형"),
("T13", "공정성·편향성", "모델 공정성·편향성 평가", "집단별 결과 차이, 공정성 지표, 조정·재평가 확인", "집단별 성능, 공정성 지표, 조치이력", "개인별 판단형"),
("T14", "설명가능성", "AI 활용 고지", "AI 활용·생성물 표시·이용자 안내의 적절성 확인", "고지 화면, 약관/안내문, 테스트 기록", "대고객"),
("T15", "설명가능성", "AI 의사결정 안내", "결과 근거와 영향, 설명 요청 처리 방법이 마련되었는가", "설명자료, 결정근거 로그, 안내 사례", "고객 영향 판단형"),
("T16", "설명가능성", "이의제기 절차 마련", "이의신청 접수·인간 재검토·처리결과 안내 절차 확인", "민원 절차, 이의신청 사례, 처리내역", "대고객/고객 영향"),
]

def _item(row, part):
    control_id, domain, name, check, evidence, applicability = row
    return {"id": control_id, "평가계층": part, "평가영역": domain, "평가항목": name,
            "확인방법": check, "필요증적": evidence, "적용대상": applicability,
            "출처": FRAMEWORK_SOURCE}

CONTROLS = [_item(x,"안전성") for x in _SAFETY] + [_item(x,"신뢰성") for x in _TRUST]
STATUSES = ["미평가", "충족", "부분충족", "미충족", "해당없음"]

RISK_WEIGHTS = [
    ("L01", "합법성", "금융소비자보호법 위반", 8),
    ("L02", "합법성", "AI기본법 위반", 4),
    ("L03", "합법성", "데이터 관련법 위반", 4),
    ("L04", "합법성", "개별 업권법 위반", 4),
    ("R01", "신뢰성", "품질", 6), ("R02", "신뢰성", "편향성", 6),
    ("R03", "신뢰성", "공정성", 6), ("R04", "신뢰성", "설명가능성", 6),
    ("R05", "신뢰성", "성능", 6),
    ("F01", "신의성실", "계약 권리 침해", 6),
    ("F02", "신의성실", "책임 투명성", 6),
    ("F03", "신의성실", "소비자 보호방안", 8),
    ("C01", "보안성", "보안", 8), ("C02", "보안성", "안정성", 8),
    ("C03", "보안성", "위탁/관리", 8), ("C04", "보안성", "프라이버시", 6)
]
MITIGATION = {"미이행":1.0, "부분이행":0.5, "완료":0.0}

def controls_summary(rows: Iterable[dict]) -> dict:
    """Evidence-based coverage; never interpret as certification/pass of entire AI service."""
    items = list(rows)
    known = {x["id"] for x in CONTROLS}
    if len(items) != len(CONTROLS) or {r.get("id") for r in items} != known:
        raise ValueError("28개 전체 항목의 상태가 필요합니다.")
    counts = Counter()
    for r in items:
        s = r.get("상태", "미평가")
        if s not in STATUSES:
            raise ValueError("정의되지 않은 평가상태: " + str(s))
        if s in ("충족", "부분충족") and not str(r.get("증적", "")).strip():
            raise ValueError(f"{r['id']}: 충족·부분충족 판정은 구체적인 증적을 작성해야 합니다.")
        if s == "해당없음" and not str(r.get("판단사유", "")).strip():
            raise ValueError(f"{r['id']}: 해당없음은 제외 근거가 필요합니다.")
        counts[s] += 1
    applicable = len(items)-counts["해당없음"]
    completed = counts["충족"]+counts["부분충족"]+counts["미충족"]
    return {"total":len(items), "applicable":applicable, "reviewed":completed,
            "review_rate":round(100*completed/applicable,1) if applicable else None,
            "fully_met":counts["충족"], "partly_met":counts["부분충족"],
            "unmet":counts["미충족"], "not_reviewed":counts["미평가"],
            "na":counts["해당없음"], "all_reviewed":(completed==applicable and applicable>0)}


def calculate_residual_risk(rows: Iterable[dict], high_impact: bool = False, financial_stability: bool = False) -> dict:
    """No unassessed item is silently treated as zero; official legal determination excluded."""
    items=list(rows)
    weights={i[0]:i[3] for i in RISK_WEIGHTS}
    if len(items)!=len(weights) or {r.get("id") for r in items} != set(weights):
        raise ValueError("잔여위험은 16개 항목 전체를 평가해야 합니다.")
    total=0.0
    missing=[]
    by_area={}
    for r in items:
        state=r.get("경감수준","미평가")
        if state not in MITIGATION:
            missing.append(r["id"])
            continue
        if state in ("부분이행", "완료") and not str(r.get("증적","")).strip():
            missing.append(r["id"])
            continue
        points=weights[r["id"]]*MITIGATION[state]
        total+=points
        by_area[r.get("부문","")]=by_area.get(r.get("부문",""),0)+points
    if missing:
        return {"score":None,"grade":"평가 보류", "missing":missing,
                "partial_sum":round(total,1),"parts":by_area,
                "reason":"미평가 또는 경감 증적 누락. 잠정합계는 위험등급 판정에 사용하지 않습니다."}
    total=round(total,1)
    if total>=75 or financial_stability:
        grade="출시 재검토"
    elif total>=50 or high_impact:
        grade="고위험(관리)"
    elif total>=25:
        grade="중위험(관리)"
    else:
        grade="저위험(관리)"
    return {"score":total,"grade":grade,"missing":[],"parts":by_area,
            "reason":"워크북 예시 임계값 25/50/75 적용. 고영향 판정은 사용자 확정 입력이며 법적 판단을 자동화하지 않습니다."}

assert len(CONTROLS)==28
assert len([x for x in CONTROLS if x["평가계층"]=="안전성"])==12
assert len([x for x in CONTROLS if x["평가계층"]=="신뢰성"])==16
assert sum(x[3] for x in RISK_WEIGHTS)==100
