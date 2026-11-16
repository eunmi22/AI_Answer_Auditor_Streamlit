"""Spreadsheet report combining answer tests, assurance 28-control checklist, and risk model.
Excel formula injection is prevented by write_string() for all untrusted strings.
"""
from __future__ import annotations
import io
from .frameworks import FRAMEWORK_SOURCE, RISK_SOURCE, controls_summary, calculate_residual_risk


def professional_report(reports, framework_rows, risk_rows, service, dataset_rows) -> bytes:
    import xlsxwriter
    out=io.BytesIO()
    wb=xlsxwriter.Workbook(out,{"in_memory":True})
    head=wb.add_format({"bold":True,"bg_color":"#14253E","font_color":"#FFFFFF","valign":"vcenter"})
    body=wb.add_format({"text_wrap":True,"valign":"top","bottom":1,"bottom_color":"#E7ECF3"})
    title=wb.add_format({"bold":True,"font_size":18,"font_color":"#17365D"})
    number=wb.add_format({"num_format":"0.0"})
    def text(v):
        s=str(v if v is not None else "")
        return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
    def sheet(name, cols, rows, widths=None):
        sh=wb.add_worksheet(name)
        sh.freeze_panes(1,0)
        for j,c in enumerate(cols):
            sh.write_string(0,j,c,head)
            sh.set_column(j,j, widths[j] if widths and j<len(widths) else 28)
        for i, row in enumerate(rows,1):
            for j,x in enumerate(row):
                if isinstance(x, (int,float)) and not isinstance(x,bool): sh.write_number(i,j,x,number)
                else: sh.write_string(i,j,text(x),body)
            sh.set_row(i, min(110, 37 if len(str(row))<160 else 55))
        if rows: sh.autofilter(0,0,len(rows),len(cols)-1)
        return sh
    comp=controls_summary(framework_rows)
    risk=calculate_residual_risk(risk_rows, bool(service.get('고영향확정',False)), bool(service.get('금융안정성우려',False)))
    sh=wb.add_worksheet('표지')
    sh.set_column('A:A',27); sh.set_column('B:B',90)
    sh.write('A1','AI 서비스 전문 평가 보고서',title)
    cover=[('서비스명',service.get('서비스명','')),('운영 도메인',service.get('도메인','')),
           ('서비스 유형',service.get('유형','')),('적용 범위','답변 품질 + 28개 관리통제 + 16개 잔여위험'),
           ('답변 평가건수',len(reports)),('관리통제 평가 완료',f"{comp['reviewed']}/{comp['applicable']} (해당없음 제외)"),
           ('관리통제 충족',comp['fully_met']),('관리통제 미충족',comp['unmet']),
           ('잔여위험 점수',risk['score'] if risk['score'] is not None else '평가보류'),
           ('잔여위험 등급',risk['grade']),('해석 한계','답변 검증은 시스템 통제 증명이 아님. 문서가 없는 항목은 미평가이며 전체 적합/인증 판정을 하지 않습니다.'),
           ('금융AI 평가기준 출처',FRAMEWORK_SOURCE),('잔여위험 산정 출처',RISK_SOURCE)]
    for i,(a,b) in enumerate(cover,2):
        sh.write_string(i,0,text(a),head); sh.write_string(i,1,text(b),body); sh.set_row(i,48 if len(str(b))>70 else 26)
    rows=[]
    for r in reports:
        rows.append([r.get('timestamp',''),r.get('case_id',''),r.get('domain',''),r.get('category',''),r.get('question',''),r.get('target',''),
                     r.get('judges',{}).get('GPT',{}).get('total',''),r.get('judges',{}).get('Gemini',{}).get('total',''),
                     ', '.join(r.get('disagreements',[])),r.get('mode','')])
    sheet('답변 평가목록',['일시','사례ID','도메인','평가유형','질문','대상답변','GPT','Gemini','재검토항목','근거범위'],rows,[24,14,22,20,78,24,12,12,30,20])
    scores=[]; claims=[]; limitations=[]
    for r in reports:
        for judge,e in r.get('judges',{}).items():
            for s in e.get('scores',[]):
                scores.append([r.get('case_id',''),r.get('target',''),judge,s['name'],s['weight'],s['quality'],s['weighted'],s['reason']])
            for f in e.get('findings',[]):
                claims.append([r.get('case_id',''),judge,f.get('claim',''),f.get('status',''), ', '.join(f.get('source_ids',[])),
                               f.get('evidence_quote',''),"확인" if f.get('quote_verified') else "미확인",f.get('explanation',''),f.get('recommendation','')])
            limitations.append([r.get('case_id',''),judge,e.get('summary',''),e.get('improved_answer',''),
                                ' / '.join(e.get('limitations',[]))])
    sheet('항목별 점수',['사례ID','대상','평가자','항목','배점','품질점수','가중점수','사유'],scores,[14,24,15,25,10,12,12,85])
    sheet('근거별 검증',['사례ID','평가자','주장','판정','근거ID','인용문','자동대조','판단 사유','개선 권고'],claims,[14,15,80,16,16,80,13,90,90])
    sheet('평가 의견',['사례ID','평가자','종합 의견','개선 답변','한계'],limitations,[14,15,78,96,75])
    sheet('안전성 신뢰성 28',['ID','계층','평가영역','평가항목','기준/확인방법','필요증적','적용대상','상태','증적','판단사유/개선','출처'],
        [[r.get(c,'') for c in ['id','평가계층','평가영역','평가항목','확인방법','필요증적','적용대상','상태','증적','판단사유','출처']] for r in framework_rows],
        [10,12,27,27,80,65,20,14,85,85,72])
    sheet('잔여위험 16',['ID','부문','항목','배점','경감수준','잔여점수','증적','판단사유','출처'],
          [[r['id'],r['부문'],r['항목'],r['배점'],r.get('경감수준','미평가'),
            (r['배점']*{'미이행':1,'부분이행':0.5,'완료':0}.get(r.get('경감수준'),1)) if r.get('경감수준') in ['미이행','부분이행','완료'] else '',
            r.get('증적',''),r.get('판단사유',''),RISK_SOURCE] for r in risk_rows],
          [11,18,28,10,16,13,82,85,77])
    sheet('평가 데이터셋',['사례ID','도메인','AI유형','평가유형','질문','기대답변(제공자료)','기대행동','참조문맥','평가대상답변'],
          [[r.get(k,'') for k in ['case_id','domain','service_type','category','question','reference_answer','expected_behavior','context','candidate_answer']] for r in dataset_rows],
          [15,27,18,25,88,88,78,70,90])
    wb.close()
    return out.getvalue()
