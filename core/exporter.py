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
        uvs = (it.get("so_sanh") or {}).get("ung_vien", [])
        src = "; ".join(dict.fromkeys(u.get("nguon", "") for u in uvs if u.get("nguon"))) \
              or (it.get("so_sanh") or {}).get("nhan_xet", "")
        rows.append([it["stt"], it["ten"], it["thongso"][:400], model,
                     d.get("tin_cay", ""), d.get("can_cu", ""), src[:250]])
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
    pj = data.get("proj", {})
    if pj:
        doc.add_heading("THÔNG TIN DỰ ÁN", 1)
        t0 = doc.add_table(rows=0, cols=2); t0.style = "Table Grid"
        for k, f in [("Chủ đầu tư", "chu_dau_tu"), ("Địa chỉ", "dia_chi"), ("Tên gói thầu", "ten_goi_thau"),
                     ("Nguồn vốn", "nguon_von"), ("Phương thức LCNT", "phuong_thuc"),
                     ("Loại hợp đồng", "loai_hop_dong"), ("Thời gian thực hiện", "thoi_gian_thuc_hien"),
                     ("Địa điểm", "dia_diem")]:
            r = t0.add_row().cells; r[0].text = k; r[1].text = str(pj.get(f, ""))
        for x in pj.get("khac", []):
            doc.add_paragraph(str(x), style="List Bullet")
    t = doc.add_table(rows=1, cols=7); t.style = "Table Grid"
    for i, h in enumerate(HEADERS):
        t.rows[0].cells[i].text = h
    for r in _rows(data):
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)
    doc.add_heading("SO SÁNH SẢN PHẨM TƯƠNG ĐƯƠNG (yêu cầu đạt 100%)", 1)
    for it in data["items"]:
        ss = it.get("so_sanh")
        if not ss or not ss.get("ung_vien"):
            continue
        doc.add_paragraph(f"STT {it['stt']} — {it['ten']}", style="Heading 2")
        for u in ss["ung_vien"]:
            tag = "ĐẠT 100%" if u.get("dat_100") else "CHƯA ĐẠT 100%"
            doc.add_paragraph(f"{u.get('model','')} ({u.get('hang','')}) — {tag} — Nguồn: {u.get('nguon','')}",
                              style="Heading 3")
            t2 = doc.add_table(rows=1, cols=3); t2.style = "Table Grid"
            for i, h in enumerate(["Yêu cầu HSMT", u.get("model", "Model"), "Đánh giá"]):
                t2.rows[0].cells[i].text = h
            for b in u.get("bang", []):
                c = t2.add_row().cells
                c[0].text = b.get("yeu_cau", ""); c[1].text = b.get("gia_tri", ""); c[2].text = b.get("danh_gia", "")
        doc.add_paragraph("Nhận xét: " + ss.get("nhan_xet", ""))
    doc.add_heading("NGHĨA VỤ NHÀ THẦU (PHÂN TÍCH CHI TIẾT)", 1)
    for g in data.get("duties", []):
        doc.add_paragraph(g.get("nhom", ""), style="Heading 2")
        for b in g.get("yeu_cau", []) or g.get("noi_dung", []):
            doc.add_paragraph(b, style="List Bullet")
        if g.get("tai_lieu_can_nop"):
            doc.add_paragraph("Tài liệu cần nộp:").runs[0].bold = True
            for b in g["tai_lieu_can_nop"]:
                doc.add_paragraph(b, style="List Bullet")
        if g.get("rui_ro_bi_loai"):
            doc.add_paragraph("⚠ Rủi ro bị loại: " + g["rui_ro_bi_loai"])
        if g.get("checklist"):
            doc.add_paragraph("Checklist trước khi nộp thầu:").runs[0].bold = True
            for b in g["checklist"]:
                doc.add_paragraph("☐ " + b, style="List Bullet")
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
    ws2.append(["STT", "Hạng mục", "Model (Hãng)", "Yêu cầu HSMT", "Giá trị của model", "Đánh giá", "Đạt 100%?", "Nguồn"])
    for it in data["items"]:
        for u in (it.get("so_sanh") or {}).get("ung_vien", []):
            tag = "ĐẠT 100%" if u.get("dat_100") else "Chưa đạt"
            for b in u.get("bang", []):
                ws2.append([str(it["stt"]), it["ten"], f"{u.get('model','')} ({u.get('hang','')})",
                            b.get("yeu_cau", ""), b.get("gia_tri", ""), b.get("danh_gia", ""), tag, u.get("nguon", "")])
    ws2.auto_filter.ref = ws2.dimensions
    ws3 = wb.create_sheet("Nghĩa vụ nhà thầu")
    ws3.append(["Nhóm", "Yêu cầu", "Tài liệu cần nộp", "Rủi ro bị loại", "Checklist"])
    for g in data.get("duties", []):
        ws3.append([g.get("nhom", ""), "\n".join(g.get("yeu_cau", []) or g.get("noi_dung", [])),
                    "\n".join(g.get("tai_lieu_can_nop", [])), g.get("rui_ro_bi_loai", ""),
                    "\n".join(g.get("checklist", []))])
    ws3.auto_filter.ref = ws3.dimensions
    ws4 = wb.create_sheet("Thông tin dự án")
    for k, f in [("Chủ đầu tư", "chu_dau_tu"), ("Địa chỉ", "dia_chi"), ("Tên gói thầu", "ten_goi_thau"),
                 ("Nguồn vốn", "nguon_von"), ("Phương thức LCNT", "phuong_thuc"),
                 ("Loại hợp đồng", "loai_hop_dong"), ("Thời gian", "thoi_gian_thuc_hien"), ("Địa điểm", "dia_diem")]:
        ws4.append([k, str(data.get("proj", {}).get(f, ""))])
    wb.save(path)


def preview_html(data):
    rows = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in _rows(data))
    duties = "".join(f"<h3>{g.get('nhom','')}</h3><ul>" + "".join(f"<li>{b}</li>" for b in g.get("noi_dung", [])) + "</ul>"
                     for g in data.get("duties", []))
    return (f"<h1>BÁO CÁO PHÂN TÍCH HỒ SƠ MỜI THẦU</h1><p>{data['meta'].get('file','')} — {len(data['items'])} hạng mục</p>"
            f"<table border=1 cellspacing=0 cellpadding=3><tr>{''.join(f'<th>{h}</th>' for h in HEADERS)}</tr>{rows}</table>"
            f"<h2>Nghĩa vụ nhà thầu</h2>{duties}")
