# -*- coding: utf-8 -*-
import os
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import analyzer, cache, exporter, extractor, preprocess
from core.ai_engine import AIEngine
from . import widgets
from .settings_dialog import SettingsDialog


class Worker(QThread):
    progress = Signal(str, int)
    project_ready = Signal(dict)
    duties_ready = Signal(dict)
    item_ready = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self._pause_gate = threading.Event()
        self._pause_gate.set()
        self._last_progress = 0

    def emit_progress(self, text, value):
        self._last_progress = value
        self.progress.emit(text, value)

    def pause(self):
        self._pause_gate.clear()

    def resume(self):
        self._pause_gate.set()

    def wait_if_paused(self):
        if not self._pause_gate.is_set():
            self.progress.emit("Đã tạm dừng - bấm Tiếp tục để chạy tiếp", self._last_progress)
        self._pause_gate.wait()

    def run(self):
        try:
            cfg = cache.load_config()
            self.emit_progress("Đang đọc file...", 5)
            raw = extractor.extract(self.path)
            ai = AIEngine(cfg)
            counter = {"used": 0}

            # Ưu tiên phân tích bảng hạng mục TRƯỚC — thông tin dự án & nghĩa vụ chạy cuối
            items = preprocess.clean(raw["items"])
            if not items:
                raise RuntimeError("Không tìm thấy bảng hạng mục trong file")

            self.wait_if_paused()
            results = analyzer.run(
                items,
                cfg,
                ai,
                self.emit_progress,
                counter,
                on_item=self.item_ready.emit,
                pause_check=self.wait_if_paused,
            )

            self.wait_if_paused()
            self.emit_progress("Trích thông tin dự án...", 96)
            try:
                proj = ai.project_info(raw["text"])
            except Exception:
                proj = {}
            self.project_ready.emit({
                "meta": raw["meta"],
                "items": [],
                "duties": [],
                "proj": proj,
                "usage": ai.usage,
                "searches": counter["used"],
            })

            self.wait_if_paused()
            self.emit_progress("Phân tích nghĩa vụ nhà thầu...", 98)
            try:
                duties = ai.duties(raw["text"])
            except Exception:
                duties = []
            self.duties_ready.emit({
                "meta": raw["meta"],
                "items": [],
                "duties": duties,
                "proj": proj,
                "usage": ai.usage,
                "searches": counter["used"],
            })

            self.done.emit({
                "meta": raw["meta"],
                "items": results,
                "duties": duties,
                "proj": proj,
                "usage": ai.usage,
                "searches": counter["used"],
            })
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trợ Lý Phân Tích Hồ Sơ Thầu v1.0")
        self.resize(1440, 820)
        self.data = None
        self.file_path = None
        self.live_items = {}

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        for text, fn in [
            ("📂 Import hồ sơ", self.import_file),
            ("▶ Phân tích", self.analyze),
            ("👁 Xem trước", self.preview),
            ("📄 Xuất Word", lambda: self.export("docx")),
            ("📕 Xuất PDF", lambda: self.export("pdf")),
            ("📊 Xuất Excel", lambda: self.export("xlsx")),
            ("⚙️ Cài đặt", self.settings),
        ]:
            action = tb.addAction(text)
            action.triggered.connect(fn)
        self.pause_action = tb.addAction("⏸ Tạm dừng")
        self.pause_action.triggered.connect(self.toggle_pause)
        self.pause_action.setEnabled(False)

        self.pbar = QProgressBar()
        self.plabel = QLabel("Chưa có file - bấm Import hồ sơ")

        tabs = QTabWidget()
        t0 = QWidget()
        v0 = QVBoxLayout(t0)
        self.proj_view = QTextBrowser()
        self.proj_view.setHtml("<p>Thông tin dự án sẽ hiển thị ngay sau khi AI trích xong.</p>")
        v0.addWidget(self.proj_view)

        t1 = QWidget()
        v1 = QVBoxLayout(t1)
        self.info = QLabel("Thông tin gói thầu: sẽ hiển thị sau khi phân tích.")
        self.info.setWordWrap(True)
        self.id_table = widgets.make_table(widgets.ID_HEADERS)
        v1.addWidget(self.info)
        v1.addWidget(QLabel("Bảng kết quả model/hãng:"))
        v1.addWidget(self.id_table, 1)

        t2 = QWidget()
        v2 = QVBoxLayout(t2)
        self.cmp_table = widgets.make_table(widgets.CMP_HEADERS)
        v2.addWidget(self.cmp_table)

        t3 = QWidget()
        v3 = QVBoxLayout(t3)
        self.duties_view = QTextBrowser()
        self.duties_view.setHtml("<p>Nghĩa vụ nhà thầu sẽ hiển thị sau thông tin dự án.</p>")
        v3.addWidget(self.duties_view)

        tabs.addTab(t0, "Thông tin dự án")
        tabs.addTab(t1, "Phân tích HSMT")
        tabs.addTab(t2, "So sánh sản phẩm")
        tabs.addTab(t3, "Nghĩa vụ nhà thầu")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.plabel)
        layout.addWidget(self.pbar)
        layout.addWidget(tabs, 1)
        self.setCentralWidget(central)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.st = QLabel("Sẵn sàng")
        sb.addWidget(self.st)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn hồ sơ", "", "Hồ sơ (*.docx *.pdf)")
        if path:
            self.file_path = path
            self.plabel.setText(f"Đã chọn: {os.path.basename(path)} - bấm Phân tích")

    def analyze(self):
        if getattr(self, "worker", None) and self.worker.isRunning():
            return QMessageBox.information(self, "Đang phân tích", "Tác vụ phân tích đang chạy.")
        if not self.file_path:
            return QMessageBox.warning(self, "Thiếu file", "Hãy Import hồ sơ trước.")
        if not cache.load_config().get("api_key"):
            QMessageBox.information(self, "Thiếu API key", "Vào Cài đặt điền API key AI trước.")
            return self.settings()

        self.live_items = {}
        self.id_table.setRowCount(0)
        self.cmp_table.setRowCount(0)
        self.worker = Worker(self.file_path)
        self.worker.progress.connect(lambda s, p: (self.plabel.setText(s), self.pbar.setValue(p)))
        self.worker.project_ready.connect(self.on_project_ready)
        self.worker.duties_ready.connect(self.on_duties_ready)
        self.worker.item_ready.connect(self.on_item)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.is_paused = False
        self.pause_action.setText("⏸ Tạm dừng")
        self.pause_action.setEnabled(True)
        self.worker.start()

    def toggle_pause(self):
        worker = getattr(self, "worker", None)
        if not worker or not worker.isRunning():
            return
        if self.is_paused:
            worker.resume()
            self.is_paused = False
            self.pause_action.setText("⏸ Tạm dừng")
            self.st.setText("Tiếp tục phân tích")
        else:
            worker.pause()
            self.is_paused = True
            self.pause_action.setText("▶ Tiếp tục")
            self.st.setText("Đã tạm dừng")

    def reset_run_controls(self):
        self.is_paused = False
        self.pause_action.setText("⏸ Tạm dừng")
        self.pause_action.setEnabled(False)

    def render_project(self, data):
        p = data.get("proj", {}) or {}
        rows = "".join(f"<tr><td width=180><b>{k}</b></td><td>{p.get(f, '')}</td></tr>" for k, f in [
            ("Chủ đầu tư", "chu_dau_tu"),
            ("Địa chỉ", "dia_chi"),
            ("Tên gói thầu", "ten_goi_thau"),
            ("Nguồn vốn", "nguon_von"),
            ("Phương thức LCNT", "phuong_thuc"),
            ("Loại hợp đồng", "loai_hop_dong"),
            ("Thời gian thực hiện", "thoi_gian_thuc_hien"),
            ("Địa điểm", "dia_diem"),
        ])
        other = "".join(f"<li>{x}</li>" for x in p.get("khac", []))
        self.proj_view.setHtml(
            f"<h2>Thông tin dự án</h2><table border=1 cellspacing=0 cellpadding=5>{rows}</table>"
            f"{'<h3>Thông tin khác</h3><ul>' + other + '</ul>' if other else ''}"
        )

    def render_duties(self, data):
        html = ""
        for group in data.get("duties", []) or []:
            html += f"<h3>{group.get('nhom', '')}</h3>"
            if group.get("yeu_cau"):
                html += "<b>Yêu cầu:</b><ul>" + "".join(f"<li>{x}</li>" for x in group["yeu_cau"]) + "</ul>"
            if group.get("tai_lieu_can_nop"):
                html += "<b>Tài liệu cần nộp:</b><ul>" + "".join(
                    f"<li>{x}</li>" for x in group["tai_lieu_can_nop"]
                ) + "</ul>"
            if group.get("rui_ro_bi_loai"):
                html += f"<p style='color:#b02222'><b>Rủi ro bị loại:</b> {group['rui_ro_bi_loai']}</p>"
            if group.get("checklist"):
                html += "<b>Checklist:</b><ul>" + "".join(f"<li>{x}</li>" for x in group["checklist"]) + "</ul>"
        self.duties_view.setHtml(html or "<p>Không trích được nghĩa vụ.</p>")

    def on_project_ready(self, data):
        self.data = data
        self.render_project(data)
        u = data.get("usage", {})
        self.st.setText(f"Đã có thông tin dự án. Token: {u.get('in', 0)} vào / {u.get('out', 0)} ra")

    def on_duties_ready(self, data):
        self.data = data
        self.render_project(data)
        self.render_duties(data)
        u = data.get("usage", {})
        self.st.setText(f"Đã có nghĩa vụ nhà thầu. Token: {u.get('in', 0)} vào / {u.get('out', 0)} ra")

    def on_failed(self, error):
        self.reset_run_controls()
        QMessageBox.critical(self, "Lỗi", error)

    def on_item(self, row):
        self.live_items[row["id"]] = row
        ordered = list(self.live_items.values())
        widgets.fill_identify(self.id_table, ordered)
        widgets.fill_compare(self.cmp_table, ordered)

    def on_done(self, data):
        self.reset_run_controls()
        self.data = data
        self.pbar.setValue(100)
        self.plabel.setText(f"Xong - {len(data['items'])} hạng mục")
        self.info.setText(
            f"File: {data['meta'].get('file')} - {len(data['items'])} hạng mục | "
            "Phương pháp: dự án -> nghĩa vụ -> trích thông số -> Serper -> đối chiếu model đạt 100%"
        )
        widgets.fill_identify(self.id_table, data["items"])
        widgets.fill_compare(self.cmp_table, data["items"])
        self.render_project(data)
        self.render_duties(data)

        cfg = cache.load_config()
        if cfg.get("search_provider", "serper") == "serper":
            total = cache.bump_counter("serper", data.get("searches", 0))
        else:
            total = cache.counter("serper")
        quota = int(cfg.get("serper_quota", 2500))
        u = data.get("usage", {})
        self.st.setText(
            f"Token: {u.get('in', 0)} vào / {u.get('out', 0)} ra - "
            f"Serper: {total}/{quota:,} credit đã dùng (lần này +{data.get('searches', 0)})"
        )

    def preview(self):
        if not self.data:
            return QMessageBox.warning(self, "Chưa có dữ liệu", "Hãy phân tích trước.")
        dialog = QDialog(self)
        dialog.setWindowTitle("Xem trước báo cáo")
        dialog.resize(1000, 640)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(exporter.preview_html(self.data))
        layout.addWidget(browser)
        dialog.exec()

    def export(self, kind):
        if not self.data:
            return QMessageBox.warning(self, "Chưa có dữ liệu", "Hãy phân tích trước.")
        ext = {"docx": "Word (*.docx)", "pdf": "PDF (*.pdf)", "xlsx": "Excel (*.xlsx)"}[kind]
        path, _ = QFileDialog.getSaveFileName(self, "Lưu báo cáo", f"Bao_cao_phan_tich.{kind}", ext)
        if not path:
            return
        try:
            getattr(exporter, f"export_{kind}")(self.data, path)
            QMessageBox.information(self, "Xong", f"Đã xuất: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất file", str(e))

    def settings(self):
        SettingsDialog(self).exec()
