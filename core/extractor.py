# -*- coding: utf-8 -*-
"""Đọc DOCX/PDF, bóc văn bản + bảng hạng mục."""
import re, os


def _docx(path):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    lines, items = [], []
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            t = Paragraph(child, doc).text.strip()
            if t:
                lines.append(t)
        elif child.tag == qn('w:tbl'):
            tbl = Table(child, doc)
            rows = [["\n".join(p.text.strip() for p in c.paragraphs if p.text.strip()) for c in r.cells] for r in tbl.rows]
            lines.append("\n".join(" | ".join(r) for r in rows))
            hdr = " ".join(rows[0]).lower() if rows else ""
            if "tên hàng" in hdr or "thông số" in hdr:
                for r in rows[1:]:
                    if len(r) >= 3 and r[0].strip():
                        items.append({"stt": r[0].strip(), "ten": r[1].strip(), "thongso": r[2].strip()})
    return "\n".join(lines), items


def _pdf(path):
    import fitz
    doc = fitz.open(path)
    text = "\n".join(pg.get_text() for pg in doc)
    items = []
    # fallback: dòng bắt đầu bằng số thứ tự
    for m in re.finditer(r"^(\d{1,3})[\.\)\s]+(.{4,80}?)\n((?:(?!^\d{1,3}[\.\)\s]).*\n?){1,30})", text, re.M):
        items.append({"stt": m.group(1), "ten": m.group(2).strip(), "thongso": m.group(3).strip()[:2000]})
    return text, items


def extract(path):
    """Trả về {text, items[{stt,ten,thongso}], meta}."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        text, items = _docx(path)
    elif ext == ".pdf":
        text, items = _pdf(path)
    else:
        raise ValueError("Chỉ hỗ trợ .docx và .pdf")
    return {"text": text, "items": items, "meta": {"file": os.path.basename(path), "n_items": len(items)}}
