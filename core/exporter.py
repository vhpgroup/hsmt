# -*- coding: utf-8 -*-
"""Xuất Word/PDF/Excel + HTML xem trước. Bảng 7 cột như báo cáo chuẩn."""
HEADERS = ["STT", "Tên hàng hóa", "Thông số kỹ thuật chính (theo E-HSMT)",
           "KẾT QUẢ: Model + Hãng", "Độ tin cậy", "Căn cứ nhận diện", "Nguồn tra cứu"]


def _rows(data):
    rows = []
    for it in data["items"]:
        d = it.get("ident", {})
        model = f"{d.get('model','')} — {d.get('hang','')}".strip(" —")
        if d.get("goi_y_hang_pho_thong"):
            model += f" (gợi ý: {d['goi_y_hang_pho_thong']})"
        src = (it.get("so_sanh") or {}).get("nhan_xet", "")
        rows.append([it["stt"], it["ten"], it["thongso"][:400], model,
                     d.get("tin_cay", ""), d.get("can_cu", ""), src[:200]])
    return rows


def export_docx(data, path):
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.section import WD_ORIENT
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21)
    doc.add_heading("BÁO CÁO PHÂN TÍCH HỒ SƠ MỜI THẦU", 0)
    doc.add_paragraph(f"File: {data['meta'].get('file','')} — {len(data['items'])} hạng mục")
    t = doc.add_table(rows=1, cols=7); t.style = "Table Grid"
    for i, h in enumerate(HEADERS):
        t.rows[0].cells[i].text = h
    for r in _rows(data):
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)
    doc.add_heading("SO SÁNH SẢN PHẨM TƯƠNG ĐƯƠNG", 1)
    for it in data["items"]:
        ss = it.get("so_sanh")
        if not ss or not ss.get("ung_vien"):
            continue
        doc.add_paragraph(f"STT {it['stt']} — {it['ten']}", style="Heading 2")
        t2 = doc.add_table(rows=1, cols=4); t2.style = "Table Grid"
        for i, h in enumerate(["Model (Hãng)", "Đánh giá tiêu chí", "Kết luận", "Ghi chú/Nguồn"]):
            t2.rows[0].cells[i].text = h
        for u in ss["ung_vien"]:
            c = t2.add_row().cells
            c[0].text = f"{u.get('model','')} ({u.get('hang','')})"
            c[1].text = " ".join(u.get("marks", []))
            c[2].text = u.get("ket_luan", "")
            c[3].text = u.get("ghi_chu_nguon", "")
        doc.add_paragraph("Nhận xét: " + ss.get("nhan_xet", ""))
    doc.add_heading("NGHĨA VỤ NHÀ THẦU", 1)
    for g in data.get("duties", []):
        doc.add_paragraph(g.get("nhom", ""), style="Heading 2")
        for b in g.get("noi_dung", []):
            doc.add_paragraph(b, style="List Bullet")
    doc.save(path)


def export_pdf(data, path):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    for f in (r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"):
        if os.path.exists(f):
            pdfmetrics.registerFont(TTFont("VN", f)); break
    S = ParagraphStyle("c", fontName="VN", fontSize=7.5, leading=9.5)
    H = ParagraphStyle("h", fontName="VN", fontSize=13, leading=16, spaceAfter=6)
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm)
    tbl = [[Paragraph(h, S) for h in HEADERS]] + [[Paragraph(str(v), S) for v in r] for r in _rows(data)]
    t = Table(tbl, colWidths=[1*cm, 3.2*cm, 7.5*cm, 5.5*cm, 2*cm, 4.5*cm, 3.8*cm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    doc.build([Paragraph("BÁO CÁO PHÂN TÍCH HỒ SƠ MỜI THẦU", H), t, Spacer(1, 8),
               Paragraph("Chi tiết so sánh tương đương & nghĩa vụ nhà thầu: xem bản Word/Excel.", S)])


def export_xlsx(data, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active; ws.title = "Nhận diện"
    ws.append(HEADERS)
    for r in _rows(data):
        ws.append([str(v) for v in r])
    ws.auto_filter.ref = ws.dimensions
    ws2 = wb.create_sheet("So sánh tương đương")
    ws2.append(["STT", "Hạng mục", "Model", "Hãng", "Đánh giá", "Kết luận", "Nguồn"])
    for it in data["items"]:
        for u in (it.get("so_sanh") or {}).get("ung_vien", []):
            ws2.append([str(it["stt"]), it["ten"], u.get("model", ""), u.get("hang", ""),
                        " ".join(u.get("marks", [])), u.get("ket_luan", ""), u.get("ghi_chu_nguon", "")])
    ws2.auto_filter.ref = ws2.dimensions
    ws3 = wb.create_sheet("Nghĩa vụ nhà thầu")
    for g in data.get("duties", []):
        ws3.append([g.get("nhom", "")])
        for b in g.get("noi_dung", []):
            ws3.append(["", b])
    wb.save(path)


def preview_html(data):
    rows = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in _rows(data))
    duties = "".join(f"<h3>{g.get('nhom','')}</h3><ul>" + "".join(f"<li>{b}</li>" for b in g.get("noi_dung", [])) + "</ul>"
                     for g in data.get("duties", []))
    return (f"<h1>BÁO CÁO PHÂN TÍCH HỒ SƠ MỜI THẦU</h1><p>{data['meta'].get('file','')} — {len(data['items'])} hạng mục</p>"
            f"<table border=1 cellspacing=0 cellpadding=3><tr>{''.join(f'<th>{h}</th>' for h in HEADERS)}</tr>{rows}</table>"
            f"<h2>Nghĩa vụ nhà thầu</h2>{duties}")
