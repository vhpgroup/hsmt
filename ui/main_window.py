# -*- coding: utf-8 -*-
import os
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QMainWindow, QToolBar, QFileDialog, QTabWidget, QWidget, QVBoxLayout,
                               QLabel, QProgressBar, QTextBrowser, QMessageBox, QDialog, QStatusBar)
from core import extractor, preprocess, analyzer, cache, exporter
from core.ai_engine import AIEngine
from .settings_dialog import SettingsDialog
from . import widgets


class Worker(QThread):
    progress = Signal(str, int)
    item_ready = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            cfg = cache.load_config()
            self.progress.emit("Đang đọc file…", 5)
            raw = extractor.extract(self.path)
            items = preprocess.clean(raw["items"])
            if not items:
                raise RuntimeError("Không tìm thấy bảng hạng mục trong file")
            ai = AIEngine(cfg)
            counter = {"used": 0}
            results = analyzer.run(items, cfg, ai, lambda s, p: self.progress.emit(s, p), counter,
                                   on_item=self.item_ready.emit)
            self.progress.emit("Trích thông tin dự án…", 94)
            try:
                proj = ai.project_info(raw["text"])
            except Exception:
                proj = {}
            self.progress.emit("Phân tích sâu nghĩa vụ nhà thầu…", 97)
            try:
                duties = ai.duties(raw["text"])
            except Exception:
                duties = []
            self.done.emit({"meta": raw["meta"], "items": results, "duties": duties, "proj": proj,
                            "usage": ai.usage, "searches": counter["used"]})
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔍 Trợ Lý Phân Tích Hồ Sơ Thầu v1.0")
        self.resize(1280, 760)
        self.data = None
        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        for text, fn in [("📂 Import hồ sơ", self.import_file), ("▶ Phân tích", self.analyze),
                         ("👁 Xem trước", self.preview), ("📄 Xuất Word", lambda: self.export("docx")),
                         ("📕 Xuất PDF", lambda: self.export("pdf")), ("📊 Xuất Excel", lambda: self.export("xlsx")),
                         ("⚙️ Cài đặt", self.settings)]:
            a = tb.addAction(text); a.triggered.connect(fn)
        self.pbar = QProgressBar(); self.plabel = QLabel("Chưa có file — bấm Import hồ sơ")
        tabs = QTabWidget()
        # Tab 0: Thông tin dự án
        t0 = QWidget(); v0 = QVBoxLayout(t0)
        self.proj_view = QTextBrowser()
        self.proj_view.setHtml("<p>Thông tin dự án sẽ hiển thị sau khi phân tích.</p>")
        v0.addWidget(self.proj_view)
        # Tab 1: Phân tích hồ sơ mời thầu
        t1 = QWidget(); v1 = QVBoxLayout(t1)
        self.info = QLabel("🏥 Thông tin gói thầu: (sẽ hiện sau khi phân tích)"); self.info.setWordWrap(True)
        self.id_table = widgets.make_table(widgets.ID_HEADERS)
        self.duties_view = QTextBrowser()
        v1.addWidget(self.info); v1.addWidget(QLabel("📊 Bảng kết quả nhận diện Model/Hãng:"))
        v1.addWidget(self.id_table, 1)
        # Tab 2: So sánh tương đương
        t2 = QWidget(); v2 = QVBoxLayout(t2)
        self.cmp_table = widgets.make_table(widgets.CMP_HEADERS)
        v2.addWidget(self.cmp_table)
        # Tab 3: Nghĩa vụ nhà thầu
        t3 = QWidget(); v3 = QVBoxLayout(t3)
        v3.addWidget(self.duties_view)
        tabs.addTab(t0, "🏥 Thông tin dự án")
        tabs.addTab(t1, "📋 Phân tích hồ sơ mời thầu")
        tabs.addTab(t2, "⚖️ So sánh sản phẩm tương đương")
        tabs.addTab(t3, "📑 Nghĩa vụ nhà thầu")
        central = QWidget(); v = QVBoxLayout(central)
        v.addWidget(self.plabel); v.addWidget(self.pbar); v.addWidget(tabs, 1)
        self.setCentralWidget(central)
        sb = QStatusBar(); self.setStatusBar(sb)
        self.st = QLabel("Sẵn sàng"); sb.addWidget(self.st)
        self.file_path = None

    def import_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn hồ sơ", "", "Hồ sơ (*.docx *.pdf)")
        if p:
            self.file_path = p
            self.plabel.setText(f"Đã chọn: {os.path.basename(p)} — bấm ▶ Phân tích")

    def analyze(self):
        if not self.file_path:
            return QMessageBox.warning(self, "Thiếu file", "Hãy Import hồ sơ trước.")
        if not cache.load_config().get("api_key"):
            QMessageBox.information(self, "Thiếu API key", "Vào ⚙️ Cài đặt điền API key AI trước.")
            return self.settings()
        self.live_items = {}
        self.id_table.setRowCount(0); self.cmp_table.setRowCount(0)
        self.worker = Worker(self.file_path)
        self.worker.progress.connect(lambda s, p: (self.plabel.setText(s), self.pbar.setValue(p)))
        self.worker.item_ready.connect(self.on_item)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(lambda e: QMessageBox.critical(self, "Lỗi", e))
        self.worker.start()

    def on_item(self, row):
        """Hiển thị live: cập nhật/thêm dòng ngay khi phân tích xong (không chờ hết)."""
        self.live_items[row["id"]] = row
        ordered = list(self.live_items.values())
        widgets.fill_identify(self.id_table, ordered)
        widgets.fill_compare(self.cmp_table, ordered)

    def on_done(self, data):
        self.data = data
        self.pbar.setValue(100)
        self.plabel.setText(f"✅ Xong — {len(data['items'])} hạng mục")
        self.info.setText(f"🏥 File: {data['meta'].get('file')} — {len(data['items'])} hạng mục | "
                          f"🔬 Phương pháp: trích thông số → AI nhận diện → web xác minh → so sánh tương đương")
        widgets.fill_identify(self.id_table, data["items"])
        widgets.fill_compare(self.cmp_table, data["items"])
        p = data.get("proj", {})
        prow = "".join(f"<tr><td width=180><b>{k}</b></td><td>{p.get(f,'')}</td></tr>" for k, f in [
            ("Chủ đầu tư", "chu_dau_tu"), ("Địa chỉ", "dia_chi"), ("Tên gói thầu", "ten_goi_thau"),
            ("Nguồn vốn", "nguon_von"), ("Phương thức LCNT", "phuong_thuc"), ("Loại hợp đồng", "loai_hop_dong"),
            ("Thời gian thực hiện", "thoi_gian_thuc_hien"), ("Địa điểm", "dia_diem")])
        khac = "".join(f"<li>{x}</li>" for x in p.get("khac", []))
        self.proj_view.setHtml(f"<h2>🏥 Thông tin dự án</h2><table border=1 cellspacing=0 cellpadding=5>{prow}</table>"
                               f"{'<h3>Thông tin khác</h3><ul>'+khac+'</ul>' if khac else ''}")
        html = ""
        for g in data.get("duties", []):
            html += f"<h3>{g.get('nhom','')}</h3>"
            if g.get("yeu_cau"):
                html += "<b>Yêu cầu:</b><ul>" + "".join(f"<li>{b}</li>" for b in g["yeu_cau"]) + "</ul>"
            if g.get("tai_lieu_can_nop"):
                html += "<b>📎 Tài liệu cần nộp:</b><ul>" + "".join(f"<li>{b}</li>" for b in g["tai_lieu_can_nop"]) + "</ul>"
            if g.get("rui_ro_bi_loai"):
                html += f"<p style='color:#b02222'>⚠️ <b>Rủi ro bị loại:</b> {g['rui_ro_bi_loai']}</p>"
            if g.get("checklist"):
                html += "<b>✅ Checklist:</b><ul>" + "".join(f"<li>{b}</li>" for b in g["checklist"]) + "</ul>"
        self.duties_view.setHtml(html or "<p>Không trích được nghĩa vụ.</p>")
        u = data.get("usage", {})
        cfg = cache.load_config()
        if cfg.get("search_provider", "serper") == "serper":
            total = cache.bump_counter("serper", data.get("searches", 0))
        else:
            total = cache.counter("serper")
        quota = int(cfg.get("serper_quota", 2500))
        self.st.setText(f"🟢 Token: {u.get('in',0)} vào / {u.get('out',0)} ra · "
                        f"🔎 Serper: {total}/{quota:,} credit đã dùng (lần này +{data.get('searches',0)})")

    def preview(self):
        if not self.data:
            return QMessageBox.warning(self, "Chưa có dữ liệu", "Hãy phân tích trước.")
        d = QDialog(self); d.setWindowTitle("👁 Xem trước báo cáo"); d.resize(1000, 640)
        v = QVBoxLayout(d); tb = QTextBrowser(); tb.setHtml(exporter.preview_html(self.data))
        v.addWidget(tb); d.exec()

    def export(self, kind):
        if not self.data:
            return QMessageBox.warning(self, "Chưa có dữ liệu", "Hãy phân tích trước.")
        ext = {"docx": "Word (*.docx)", "pdf": "PDF (*.pdf)", "xlsx": "Excel (*.xlsx)"}[kind]
        p, _ = QFileDialog.getSaveFileName(self, "Lưu báo cáo", f"Bao_cao_phan_tich.{kind}", ext)
        if not p:
            return
        try:
            getattr(exporter, f"export_{kind}")(self.data, p)
            QMessageBox.information(self, "Xong", f"Đã xuất: {p}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất file", str(e))

    def settings(self):
        SettingsDialog(self).exec()
