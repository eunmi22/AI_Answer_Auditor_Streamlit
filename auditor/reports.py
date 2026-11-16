"""In-memory Excel/CSV exports. No report is written to shared server storage."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List


def _safe(value: object) -> str:
    # Explicit string writing prevents Xlsx formula injection; prefix for CSV tools.
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def excel_report(report: Dict) -> bytes:
    import xlsxwriter
    buffer = io.BytesIO()
    wb = xlsxwriter.Workbook(buffer, {"in_memory": True})
    title = wb.add_format({"bold": True, "font_size": 18, "font_color": "#153D5C"})
    header = wb.add_format({"bold": True, "bg_color": "#153D5C", "font_color": "#FFFFFF", "border": 0, "valign": "vcenter"})
    body = wb.add_format({"text_wrap": True, "valign": "top", "bottom": 1, "bottom_color": "#E5EAF0"})
    number = wb.add_format({"num_format": "0.0", "valign": "top"})

    def table(name: str, columns: List[str], rows: List[List[object]], widths=None):
        sh = wb.add_worksheet(name)
        sh.freeze_panes(1, 0)
        sh.set_default_row(23)
        for j, col in enumerate(columns):
            sh.write_string(0, j, col, header)
            sh.set_column(j, j, widths[j] if widths and j < len(widths) else 28)
        for i, row in enumerate(rows, 1):
            for j, val in enumerate(row):
                if isinstance(val, (float, int)) and not isinstance(val, bool):
                    sh.write_number(i, j, val, number)
                else:
                    sh.write_string(i, j, _safe(val), body)
            sh.set_row(i, min(140, 36 if len(str(row)) < 170 else 62))
        sh.autofilter(0, 0, max(1,len(rows)), max(0,len(columns)-1))
        return sh

    sh = wb.add_worksheet("개요")
    sh.set_column("A:A", 21)
    sh.set_column("B:B", 92)
    sh.write("A1", "AI 답변 신뢰성 평가보고서", title)
    from .evaluation import risk_level
    scores_all = [e.get("total", 0) for e in report.get("judges", {}).values()]
    average_score = round(sum(scores_all)/len(scores_all), 1) if scores_all else 0
    fields = [
        ("평가 일시", report.get("timestamp", "")), ("질문", report.get("question", "")),
        ("답변 구분", report.get("target", "")), ("검증 모드", report.get("mode", "")),
        ("평가 대상 답변", report.get("answer", "")),
        ("평균 종합점수", average_score),
        ("잠정 위험등급", risk_level(average_score)),
        ("종합평가", "두 모델의 독립적인 AI 판단이며, 사실의 확정적 검증 또는 RAGAS 원본 구현 결과가 아닙니다."),
    ]
    for i, (key, val) in enumerate(fields, 3):
        sh.write_string(i, 0, key, header)
        sh.write_string(i, 1, _safe(val), body)
        sh.set_row(i, 60 if key in ("질문", "평가 대상 답변") else 28)
    sh.write("A14", "평가 모델", header)
    sh.write("B14", "종합점수", header)
    for i, (judge, ev) in enumerate(report.get("judges", {}).items(), 14):
        sh.write_string(i, 0, judge, body)
        sh.write_number(i, 1, ev["total"], number)

    scores = []
    findings = []
    checklists = []
    improved = []
    for judge, ev in report.get("judges", {}).items():
        for s in ev["scores"]:
            scores.append([judge, s["name"], s["weight"], s["quality"], s["weighted"], s["reason"]])
        for f in ev["findings"]:
            findings.append([judge, f["claim"], f["status"], ", ".join(f["source_ids"]), f["evidence_quote"],
                             "확인" if f["quote_verified"] else "미확인", f["explanation"], f["recommendation"]])
        for c in ev["checklist"]:
            checklists.append([judge, c["item"], c["status"]])
        improved.append([judge, ev["summary"], ev["improved_answer"], " / ".join(ev["limitations"])])
    table("항목별점수", ["평가자", "항목", "배점", "품질점수(100)", "가중점수", "평가사유"], scores,
          [18, 24, 10, 18, 15, 72])
    table("주장별검증", ["평가자", "AI 주장", "판정", "근거ID", "근거인용", "문서 인용검증", "판정사유", "개선권고"], findings,
          [15, 57, 16, 17, 55, 18, 54, 55])
    table("체크리스트", ["평가자", "점검항목", "상태"], checklists, [20, 75, 24])
    table("개선답변", ["평가자", "총평", "개선 답변", "한계"], improved, [18, 60, 96, 70])
    evrows = [[r["id"], r["file"], r["location"], r["text"]] for r in report.get("sources", [])]
    table("문서근거", ["근거ID", "파일명", "위치", "근거 발췌"], evrows, [13, 36, 35, 104])
    webrows = [[w["id"], w["title"], w["url"]] for w in report.get("web_urls", [])]
    table("웹출처", ["출처ID", "문서명", "URL (검색 도구 제공)"] , webrows, [13, 55, 90])
    wb.close()
    return buffer.getvalue()


def csv_history(reports: List[Dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["평가일시", "질문", "답변출처", "근거모드", "GPT평가", "Gemini평가", "평균", "차이발생 항목"])
    for r in reports:
        judges = r.get("judges", {})
        scores = [e["total"] for e in judges.values()]
        diff = ", ".join(r.get("disagreements", []))
        writer.writerow([_safe(r.get("timestamp", "")), _safe(r.get("question", "")),
                         _safe(r.get("target", "")), _safe(r.get("mode", "")),
                         judges.get("GPT", {}).get("total", ""), judges.get("Gemini", {}).get("total", ""),
                         round(sum(scores)/len(scores), 1) if scores else "", _safe(diff)])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
