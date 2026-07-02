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
            results = analyzer.run(items, cfg, ai, lambda s, p: self.progress.emit(s, p), counter)
            self.progress.emit("Phân tích nghĩa vụ nhà thầu…", 96)
            try:
                duties = ai.duties(raw["text"])
            except Exception:
                duties = []
            self.done.emit({"meta": raw["meta"], "items": results, "duties": duties,
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
        # Tab 1: Phân tích hồ sơ mời thầu
        t1 = QWidget(); v1 = QVBoxLayout(t1)
        self.info = QLabel("🏥 Thông tin gói thầu: (sẽ hiện sau khi phân tích)"); self.info.setWordWrap(True)
        self.id_table = widgets.make_table(widgets.ID_HEADERS)
        self.duties_view = QTextBrowser(); self.duties_view.setMaximumHeight(180)
        v1.addWidget(self.info); v1.addWidget(QLabel("📊 Bảng kết quả nhận diện Model/Hãng:"))
        v1.addWidget(self.id_table, 1)
        v1.addWidget(QLabel("📑 Nghĩa vụ nhà thầu:")); v1.addWidget(self.duties_view)
        # Tab 2: So sánh tương đương
        t2 = QWidget(); v2 = QVBoxLayout(t2)
        self.cmp_table = widgets.make_table(widgets.CMP_HEADERS)
        v2.addWidget(self.cmp_table)
        tabs.addTab(t1, "📋 Phân tích hồ sơ mời thầu")
        tabs.addTab(t2, "⚖️ So sánh sản phẩm tương đương")
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
        self.worker = Worker(self.file_path)
        self.worker.progress.connect(lambda s, p: (self.plabel.setText(s), self.pbar.setValue(p)))
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(lambda e: QMessageBox.critical(self, "Lỗi", e))
        self.worker.start()

    def on_done(self, data):
        self.data = data
        self.pbar.setValue(100)
        self.plabel.setText(f"✅ Xong — {len(data['items'])} hạng mục")
        self.info.setText(f"🏥 File: {data['meta'].get('file')} — {len(data['items'])} hạng mục | "
                          f"🔬 Phương pháp: trích thông số → AI nhận diện → web xác minh → so sánh tương đương")
        widgets.fill_identify(self.id_table, data["items"])
        widgets.fill_compare(self.cmp_table, data["items"])
        self.duties_view.setHtml("".join(f"<b>{g.get('nhom','')}</b><ul>" +
                                         "".join(f"<li>{b}</li>" for b in g.get("noi_dung", [])) + "</ul>"
                                         for g in data.get("duties", [])))
        u = data.get("usage", {})
        self.st.setText(f"🟢 Token: {u.get('in',0)} vào / {u.get('out',0)} ra · 🔎 Serper: {data.get('searches',0)} lượt")

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
