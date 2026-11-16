"""Read supported uploads completely in memory, with traceable evidence locations."""
from __future__ import annotations

import csv
import io
import os
import re
from typing import Dict, Iterable, List, Tuple

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 6
ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".pptx"}
MAX_SEGMENT_CHARS = 1500
MAX_SEGMENTS = 500


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _split_text(text: str, label: str) -> Iterable[Tuple[str, str]]:
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return
    # Overlap helps preserve claims crossing segment boundaries.
    pos = 0
    number = 0
    while pos < len(text):
        number += 1
        end = min(len(text), pos + MAX_SEGMENT_CHARS)
        if end < len(text):
            cut = max(text.rfind("\n", pos + 700, end), text.rfind(". ", pos + 700, end))
            if cut > pos:
                end = cut + 1
        chunk = text[pos:end].strip()
        if chunk:
            yield f"{label}, 문단 {number}", chunk
        if end >= len(text):
            break
        pos = max(pos + 1, end - 130)


def _parse_one(name: str, data: bytes) -> List[Tuple[str, str]]:
    ext = os.path.splitext(name)[1].lower()
    result: List[Tuple[str, str]] = []
    if ext == ".pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as pdf:
            for page_no, page in enumerate(pdf, 1):
                result.extend(_split_text(page.get_text("text"), f"PDF {page_no}페이지"))
    elif ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for t in doc.tables:
            for row in t.rows:
                lines.append(" | ".join(c.text.replace("\n", " ").strip() for c in row.cells))
        result.extend(_split_text("\n".join(lines), "Word 본문"))
    elif ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        for slide_no, slide in enumerate(prs.slides, 1):
            parts = [sh.text for sh in slide.shapes if sh.has_text_frame]
            for sh in slide.shapes:
                if sh.has_table:
                    for row in sh.table.rows:
                        parts.append(" | ".join(cell.text for cell in row.cells))
            result.extend(_split_text("\n".join(parts), f"슬라이드 {slide_no}"))
    elif ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            for ws in wb:
                batch: List[str] = []
                start = 1
                for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    cells = [f"{i+1}열={str(v)[:260]}" for i, v in enumerate(row[:35]) if v is not None]
                    if cells:
                        batch.append(f"{row_idx}행: " + ", ".join(cells))
                    if row_idx % 15 == 0:
                        if batch:
                            result.extend(_split_text("\n".join(batch), f"시트 {ws.title}, {start}-{row_idx}행"))
                        start, batch = row_idx + 1, []
                    if row_idx >= 600:
                        result.append((f"시트 {ws.title}", "[경고] 600행 이후 내용은 처리 제한으로 생략"))
                        break
                if batch:
                    result.extend(_split_text("\n".join(batch), f"시트 {ws.title}, {start}-{min(ws.max_row or start,600)}행"))
        finally:
            wb.close()
    elif ext == ".csv":
        rows = csv.reader(io.StringIO(_decode(data)))
        batch: List[str] = []
        start = 1
        for row_idx, row in enumerate(rows, 1):
            batch.append(f"{row_idx}행: " + " | ".join(str(x)[:260] for x in row[:35]))
            if row_idx % 15 == 0:
                result.extend(_split_text("\n".join(batch), f"CSV {start}-{row_idx}행"))
                start, batch = row_idx + 1, []
            if row_idx >= 600:
                result.append(("CSV", "[경고] 600행 이후 내용은 처리 제한으로 생략"))
                break
        if batch:
            result.extend(_split_text("\n".join(batch), f"CSV {start}행 이후"))
    elif ext == ".txt":
        result.extend(_split_text(_decode(data), "텍스트"))
    return result


def parse_uploads(files: List[Tuple[str, bytes]]) -> Tuple[List[Dict], List[str]]:
    if len(files) > MAX_FILES:
        raise ValueError(f"파일은 최대 {MAX_FILES}개입니다.")
    if sum(len(d) for _, d in files) > MAX_TOTAL_BYTES:
        raise ValueError("파일 전체 크기는 16MB 이하여야 합니다.")
    records: List[Dict] = []
    notices: List[str] = []
    for name, data in files:
        if os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
            raise ValueError(f"지원하지 않는 형식: {name}")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"파일당 8MB 이하여야 합니다: {name}")
        segments = _parse_one(name, data)
        if not segments:
            notices.append(f"{name}: 추출된 텍스트가 없습니다. 스캔 PDF/이미지에는 OCR이 필요합니다.")
        for location, text in segments:
            if len(records) >= MAX_SEGMENTS:
                notices.append("처리량 제한으로 일부 문서 내용이 생략되었습니다.")
                break
            if text.startswith("[경고]"):
                notices.append(f"{name}: {text}")
                continue
            records.append({"id": f"D{len(records)+1}", "file": name, "location": location, "text": text})
    return records, list(dict.fromkeys(notices))
