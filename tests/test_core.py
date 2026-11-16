import csv
import io
import json

import pytest

from auditor.documents import parse_uploads
from auditor.retrieval import find_evidence
from auditor.security import detect_sensitive, redact_pii
from auditor.evaluation import normalize_rubric, validate_result, judges_disagree
from auditor.reports import excel_report, csv_history


def test_txt_retrieval():
    docs, warnings = parse_uploads([("규정.txt", "로그는 3년간 보관한다.\n장애 발생 시 담당자에게 보고한다.".encode("utf-8"))])
    assert len(docs) > 0
    assert docs[0]["file"] == "규정.txt"
    found = find_evidence(docs, "로그 보관기간은?")
    assert "3년" in found[0]["text"]


def test_csv_location():
    docs, _ = parse_uploads([("매출.csv", "메뉴,가격\n우동,5000\n라면,6000".encode("utf-8"))])
    assert docs[0]["location"].startswith("CSV")
    assert "우동" in docs[0]["text"]


def test_pii_redact():
    text = "문의: alpha@example.com, 연락처 010-1234-5678"
    assert "이메일" in detect_sensitive(text)
    assert "전화번호" in detect_sensitive(text)
    out = redact_pii(text)
    assert "example.com" not in out and "010-1234" not in out


def test_rubric_weights():
    x = normalize_rubric([{"항목":"충실도","배점":60},{"항목":"정확도","배점":40}])
    assert sum(r["weight"] for r in x) == 100
    with pytest.raises(ValueError):
        normalize_rubric([{"항목":"A","배점":60}])


def test_quote_must_exist_in_source():
    doc = {"id":"D1", "file":"규정.txt", "location":"텍스트 1", "text":"로그는 3년간 보관한다."}
    base = {"scores":[{"name":"근거 충실도","quality":80,"reason":"보통"}],
            "summary":"요약", "findings":[{"claim":"로그 보관기간은 3년","status":"근거 확인","source_ids":["D1"],
            "evidence_quote":"3년간 보관한다", "explanation":"", "recommendation":""}],
            "improved_answer":"3년", "checklist":[], "limitations":[]}
    rubric = [{"name":"근거 충실도","weight":100}]
    valid = validate_result(base, rubric, [doc], [])
    assert valid["total"] == 80
    assert valid["findings"][0]["quote_verified"]
    base["findings"][0]["evidence_quote"] = "5년간 보관한다"
    invalid = validate_result(base, rubric, [doc], [])
    assert invalid["findings"][0]["status"] == "평가 보류"


def test_report_xlsx_and_csv():
    from openpyxl import load_workbook
    report = {
        "timestamp":"2026-11-17 00:00 KST", "question":"로그 보관기간?", "answer":"3년", "target":"GPT 생성 답변",
        "mode":"업로드 파일만", "sources":[{"id":"D1","file":"규정.txt","location":"문단 1","text":"3년"}],
        "web_urls":[], "judges":{"GPT":{"total":95,"summary":"정확", "scores":[{"name":"근거 충실도","weight":100,"quality":95,"weighted":95,"reason":"확인"}],
              "findings":[],"improved_answer":"3년", "limitations":[],"checklist":[]}},"disagreements":[]}
    value = excel_report(report)
    assert value.startswith(b"PK")
    wb = load_workbook(io.BytesIO(value), read_only=True)
    assert "문서근거" in wb.sheetnames
    assert wb["개요"]["A1"].value == "AI 답변 신뢰성 평가보고서"
    wb.close()
    csv_result = csv_history([report]).decode("utf-8-sig")
    assert "GPT 생성 답변" in csv_result


def test_pdf_word_excel_pptx_parsers():
    import fitz
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((75, 75), "audit retention policy", fontsize=13)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    doc = Document()
    doc.add_paragraph("Word policy version 1")
    doc_buffer = io.BytesIO()
    doc.save(doc_buffer)

    wb = Workbook()
    ws = wb.active
    ws.title = "표본"
    ws.append(["항목", "결과"])
    ws.append(["감사", "적합"])
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Governance review"
    ppt_buffer = io.BytesIO()
    presentation.save(ppt_buffer)

    docs, warnings = parse_uploads([
        ("a.pdf", pdf_bytes),
        ("a.docx", doc_buffer.getvalue()),
        ("a.xlsx", excel_buffer.getvalue()),
        ("a.pptx", ppt_buffer.getvalue()),
    ])
    full = " ".join(d["text"] for d in docs)
    assert "audit retention" in full
    assert "Word policy" in full
    assert "감사" in full
    assert "Governance review" in full
    assert any("PDF 1페이지" in d["location"] for d in docs)
    assert any("시트 표본" in d["location"] for d in docs)
    assert any("슬라이드 1" in d["location"] for d in docs)
