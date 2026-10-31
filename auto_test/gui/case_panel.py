# -*- coding: utf-8 -*-
"""「用例测试」面板：黑盒测试用例 生成 → 执行 → 自动回填 → 报告，全 UI 操作。

流程：配置页填样机/通道/边界 → 主窗口「一键连接仪器」→ 本页「开始测试」（自动生成用例）→
数据与波形自动回填 → 产出《型号_黑盒测试报告.xlsx》。
环温由用户输入（温箱流程已移除），只执行该环温对应的工况块。
"""
import os
import threading
from datetime import datetime
from ..runtime import reports_directory, safe_filename

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QProgressBar, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QMessageBox, QDoubleSpinBox,
    QFileDialog, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QColor

from ..test_case import PowerSpec, TestCaseGenerator
from ..test_case.test_case_runner import KIND_NAME, CaseExecutor, available_temps, build_tasks

_KINDS = ("ripple", "dynamic", "stability", "startup")
_STATUS_COLOR = {"PASS": "#C6EFCE", "FAIL": "#FF4444", "SKIP": "#D9D9D9", "ERROR": "#FFCC99"}


class _CaseBridge(QObject):
    """跨线程信号桥：执行器回调在工作线程触发，经 Qt 信号投递到 GUI 主线程。"""

    task_start = pyqtSignal(object, int, int)
    task_done = pyqtSignal(object, object, int, int)
    confirm_request = pyqtSignal()
    error = pyqtSignal(str)
    finished = pyqtSignal()


class CasePanel(QWidget):
    """用例测试面板"""

    COLUMNS = ["步骤", "测试项", "环温(℃)", "工况", "Vin(V)", "通道",
               "设定电流(A)", "实测最小(V)", "实测最大(V)", "纹波(Vpp)", "结果"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instruments = {}
        self._config_getter = None
        self.before_test_start = None
        self.executor = None
        self._wb = None
        self.case_path = ""
        self.report_path = ""
        self._row_map = {}
        self._waveform_paths = {}
        self._waveform_viewer = None
        # 人工确认跨线程握手（工作线程阻塞等待主线程弹窗结果）
        self._confirm_msg = ""
        self._confirm_evt = threading.Event()
        self._confirm_result = True
        self._bridge = _CaseBridge()
        self._setup_ui()
        self._connect_bridge()

    # ---------- UI ----------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        gen_group = QGroupBox("测试用例")
        gen_layout = QHBoxLayout(gen_group)
        self.label_info = QLabel("样机：未加载（请在「配置」页填写）")
        gen_layout.addWidget(self.label_info, 1)
        self.btn_generate = QPushButton("生成测试用例")
        self.btn_generate.clicked.connect(self.generate_case)
        gen_layout.addWidget(self.btn_generate)
        self.btn_open_case = QPushButton("打开用例")
        self.btn_open_case.clicked.connect(lambda: self._open_path(self.case_path))
        self.btn_open_case.setEnabled(False)
        gen_layout.addWidget(self.btn_open_case)
        self.btn_open_report = QPushButton("打开报告")
        self.btn_open_report.clicked.connect(lambda: self._open_path(self.report_path))
        self.btn_open_report.setEnabled(False)
        gen_layout.addWidget(self.btn_open_report)
        layout.addWidget(gen_group)

        opt_group = QGroupBox("执行设置（环温由当前环境实际温度决定）")
        opt_layout = QHBoxLayout(opt_group)
        opt_layout.addWidget(QLabel("环温(℃)："))
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(-70.0, 150.0)
        self.spin_temp.setDecimals(1)
        self.spin_temp.setValue(25.0)
        self.spin_temp.setSingleStep(5.0)
        opt_layout.addWidget(self.spin_temp)
        opt_layout.addWidget(QLabel("  测试项："))
        self.chk = {}
        for kind in _KINDS:
            cb = QCheckBox(KIND_NAME[kind])
            cb.setChecked(True)
            self.chk[kind] = cb
            opt_layout.addWidget(cb)
        opt_layout.addStretch()
        layout.addWidget(opt_group)

        ctrl_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始测试")
        self.btn_start.clicked.connect(self._start)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(self._pause)
        self.btn_pause.setEnabled(False)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setEnabled(False)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_pause)
        ctrl_layout.addWidget(self.btn_stop)
        self.btn_waveform = QPushButton("查看工况波形")
        self.btn_waveform.clicked.connect(self._view_selected_waveform)
        self.btn_waveform.setEnabled(False)
        ctrl_layout.addWidget(self.btn_waveform)
        self.btn_history_waveform = QPushButton("打开历史波形")
        self.btn_history_waveform.clicked.connect(self._open_history_waveform)
        ctrl_layout.addWidget(self.btn_history_waveform)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.label_status = QLabel("就绪（请先在主窗口「一键连接仪器」）")
        layout.addWidget(self.progress)
        layout.addWidget(self.label_status)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._waveform_selection_changed)
        self.table.cellDoubleClicked.connect(lambda row, col: self._view_selected_waveform())
        layout.addWidget(self.table, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

    def _connect_bridge(self):
        b = self._bridge
        b.task_start.connect(self._on_task_start)
        b.task_done.connect(self._on_task_done)
        b.confirm_request.connect(self._show_confirm)
        b.error.connect(lambda msg: self._log(f"[错误] {msg}"))
        b.finished.connect(self._on_finished)

    # ---------- 外部注入（主窗口调用） ----------
    def set_instruments(self, instruments: dict):
        self.instruments = instruments or {}
        if self.instruments.get("power_supply") and self.instruments.get("electronic_load"):
            self.label_status.setText("仪器已连接，可执行用例测试")
        else:
            self.label_status.setText("缺少直流源/电子负载：可生成用例，执行时相关工况将跳过")

    def set_config_getter(self, getter):
        self._config_getter = getter

    def refresh_info(self):
        cfg = self._get_config()
        if not cfg:
            return
        b = cfg.boundary
        self.label_info.setText(
            f"样机：{cfg.model_name or '未命名'}  |  {len(cfg.output_channels)} 路输出  |  "
            f"Vin {b.vin_min:g}~{b.vin_max:g}V  |  "
            f"环温块 {b.temp_min:g}/{b.temp_rated:g}/{b.temp_max:g}℃")

    def shutdown(self):
        if self.executor and self.executor.running:
            self.executor.stop()
            self._confirm_result = False
            self._confirm_evt.set()
            self.executor._thread.join(timeout=10)
            return not self.executor.running
        return True

    # ---------- 内部辅助 ----------
    def _get_config(self):
        return self._config_getter() if self._config_getter else None

    def _get_spec(self):
        cfg = self._get_config()
        if not cfg:
            return None
        return PowerSpec.from_config(cfg)

    def _output_dir(self):
        cfg = self._get_config()
        return (cfg.output_root if cfg and cfg.output_root
                else str(reports_directory()))

    def _case_name(self, cfg, suffix="用例"):
        mark = "报告" if suffix == "报告" else "用例"
        return f"{safe_filename(cfg.model_name or '电源')}_黑盒测试{mark}.xlsx"

    @staticmethod
    def _open_path(path):
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception:
                pass

    def _log(self, msg: str):
        self.log.append(msg)

    # ---------- 用例生成 ----------
    def generate_case(self):
        """按当前配置生成（覆盖）黑盒测试用例 Excel。"""
        spec = self._get_spec()
        if spec is None or spec.n == 0:
            QMessageBox.warning(self, "提示", "请先在「配置」页填写输出通道")
            return
        cfg = self._get_config()
        try:
            spec.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "规格无效", str(exc))
            return
        out_dir = self._output_dir()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, self._case_name(cfg))
        try:
            TestCaseGenerator(spec).generate(path)
        except PermissionError:
            QMessageBox.critical(self, "文件被占用", "用例文件正被 Excel 打开，请关闭后重试。")
            return
        except Exception as e:
            QMessageBox.critical(self, "生成失败", f"生成测试用例时出错:\n{e}")
            return
        self.case_path = path
        self.btn_open_case.setEnabled(True)
        self.refresh_info()
        self._log(f"测试用例已生成（{spec.n} 路输出，环温块 {available_temps(spec)}℃）: {path}")
        self.label_status.setText("用例已生成；输入环温后点「开始测试」（开始时会按最新配置重建用例）")

    # ---------- 执行 ----------
    def _start(self):
        if self.executor and self.executor.running:
            return
        spec = self._get_spec()
        if spec is None or spec.n == 0:
            QMessageBox.warning(self, "提示", "请先在「配置」页填写输出通道")
            return
        kinds = tuple(k for k in _KINDS if self.chk[k].isChecked())
        if not kinds:
            QMessageBox.warning(self, "提示", "请至少勾选一个测试项")
            return
        temp = round(float(self.spin_temp.value()), 1)
        blocks = available_temps(spec)
        if not any(abs(temp - t) <= 0.5 for t in blocks):
            QMessageBox.warning(
                self, "环温不匹配",
                f"输入环温 {temp:g}℃ 不在用例工况中。\n可选环温块：{' / '.join(f'{t:g}' for t in blocks)}℃\n"
                "如需其他环温，请在「配置」页修改边界温度后重新生成用例。")
            return
        if not (self.instruments.get("power_supply") and self.instruments.get("electronic_load")):
            QMessageBox.warning(self, "提示",
                                "未连接直流源/电子负载，所有工况都将跳过。\n请先在主窗口「一键连接仪器」。")
            return
        if not self.instruments.get("oscilloscope"):
            QMessageBox.warning(self, "示波器未连接", "所选测试需要示波器，请先连接后再测试。")
            return

        cfg = self._get_config()
        try:
            spec.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "规格无效", str(exc))
            return
        out_dir = os.path.join(self._output_dir(), safe_filename(cfg.model_name) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, self._case_name(cfg))
        self.report_path = os.path.join(out_dir, self._case_name(cfg, suffix="报告"))

        # 按当前配置重建空用例（保证 Excel 行号与任务映射一致），再逐工况增量保存
        gen = TestCaseGenerator(spec)
        self._wb = gen.build_workbook()
        try:
            self._wb.save(path)
        except PermissionError:
            QMessageBox.critical(self, "文件被占用", "用例文件正被 Excel 打开，请关闭后重试。")
            return
        self.case_path = path
        self.btn_open_case.setEnabled(True)

        self._tasks = build_tasks(spec, kinds, temp)
        if not self._tasks:
            QMessageBox.warning(self, "提示", "没有可执行的工况")
            return

        ch_names = [o.name for o in spec.outputs]
        self._populate_table(self._tasks, ch_names)
        self.progress.setMaximum(len(self._tasks))
        self.progress.setValue(0)

        self.executor = CaseExecutor(
            spec, self.instruments, self._wb, self._tasks, path,
            archiver_dir=out_dir,
            on_task_start=lambda t, i, n: self._bridge.task_start.emit(t, i, n),
            on_task_done=lambda t, r, i, n: self._bridge.task_done.emit(t, r, i, n),
            on_confirm=self._confirm_from_worker,
            on_error=lambda msg: self._bridge.error.emit(msg),
            on_finished=self._bridge.finished.emit,
        )
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("暂停")
        self.btn_stop.setEnabled(True)
        if self.before_test_start and not self.before_test_start():
            self._reset_controls()
            QMessageBox.warning(self, "示波器忙", "实时波形读取尚未结束，请稍后重试。")
            return
        self.executor.start()
        self.btn_open_report.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self._log(f"开始执行：{len(self._tasks)} 个工况，环温 {temp:g}℃，测试项 {'、'.join(kinds)}")

    def _populate_table(self, tasks, ch_names):
        self.table.setRowCount(0)
        self._row_map = {}
        self._waveform_paths = {}
        self.btn_waveform.setEnabled(False)
        for i, t in enumerate(tasks):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_map[i] = row
            cells = [str(i + 1), t.test_item, f"{t.temp:g}", t.name, f"{t.vin:g}",
                     ch_names[t.channel] if t.channel < len(ch_names) else f"CH{t.channel + 1}",
                     f"{t.currents[t.channel]:g}", "-", "-", "-", "待执行"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

    def _on_task_start(self, task, index, total):
        self.label_status.setText(f"执行中: {task.test_item} - {task.name}（{index + 1}/{total}）")
        row = self._row_map.get(index)
        if row is not None:
            self.table.item(row, 10).setText("执行中...")
        self._log(f"[{index + 1}/{total}] {task.test_item} | {task.name} | Vin={task.vin:g}V")

    def _on_task_done(self, task, result, index, total):
        self.progress.setValue(index + 1)
        status = result.get("status", "ERROR")
        row = self._row_map.get(index)
        if row is not None:
            path = result.get("npz") or result.get("csv")
            if path:
                self._waveform_paths[row] = path
                self.table.item(row, 1).setToolTip("双击查看已保存的工况波形")
            for col, key in ((7, "vmin"), (8, "vmax"), (9, "ripple")):
                v = result.get(key)
                self.table.item(row, col).setText("-" if v is None else f"{v:g}")
            item = QTableWidgetItem(status)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 10, item)
            color = _STATUS_COLOR.get(status, "#FFFFFF")
            fg = QColor("#FFFFFF") if status == "FAIL" else QColor("#000000")
            for c in range(self.table.columnCount()):
                self.table.item(row, c).setBackground(QColor(color))
                self.table.item(row, c).setForeground(fg)
        note = result.get("note", "")
        extra = f"（{note}）" if note else ""
        self._log(f"  [{status}] {task.test_item} {task.name}{extra}")
        self._waveform_selection_changed()

    def _waveform_selection_changed(self):
        self.btn_waveform.setEnabled(self.table.currentRow() in self._waveform_paths)

    def _view_selected_waveform(self):
        path = self._waveform_paths.get(self.table.currentRow())
        if path:
            self._show_waveform(path)

    def _open_history_waveform(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开历史工况波形", self._output_dir(),
                                             "波形记录 (*.npz *.csv)")
        if path:
            self._show_waveform(path)

    def _show_waveform(self, path):
        from ..waveforms.ui.viewer import WaveformViewer
        try:
            if self._waveform_viewer is None:
                self._waveform_viewer = WaveformViewer(self)
            self._waveform_viewer.load_file(path)
            self._waveform_viewer.show()
            self._waveform_viewer.raise_()
            self._waveform_viewer.activateWindow()
        except Exception as exc:
            QMessageBox.warning(self, "无法打开波形", str(exc))

    def _on_finished(self):
        self._reset_controls()
        ex = self.executor
        if ex is None:
            return
        saved = ""
        try:
            if self._wb is not None and self.report_path:
                self._wb.save(self.report_path)
                saved = self.report_path
                self.btn_open_report.setEnabled(True)
        except Exception as e:
            self._log(f"[错误] 报告保存失败: {e}")

        stats = f"PASS {ex.counts['PASS']}，FAIL {ex.counts['FAIL']}，ERROR {ex.counts['ERROR']}，SKIP {ex.counts['SKIP']}"
        self._log(f"测试结果：{stats}；{ex.outcome()}")
        if not saved:
            self.btn_open_report.setEnabled(False)
            self.label_status.setText("测试结束，报告保存失败")
            QMessageBox.critical(self, "报告保存失败", "数据仍在内存中，请关闭占用文件的 Excel 后重新保存。")
        elif ex.error_msg:
            self.label_status.setText(f"测试异常终止: {ex.error_msg}")
            QMessageBox.critical(self, "测试异常", ex.error_msg)
        elif ex.was_stopped:
            self.label_status.setText("测试已停止（已完成工况的数据已回填保留）")
        else:
            self.label_status.setText(f"{ex.outcome()}；报告已保存")
            msg = f"{ex.outcome()}\n{stats}"
            if saved:
                msg += f"\n报告文件: {saved}"
            if ex.save_error:
                msg += f"\n注意: 用例文件保存失败（可能被 Excel 占用），已完成数据在报告中。"
            if ex.all_passed:
                QMessageBox.information(self, "全部通过", msg)
            else:
                QMessageBox.warning(self, "存在未通过工况", msg)

    def _reset_controls(self):
        self.btn_start.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("暂停")
        self.btn_stop.setEnabled(False)

    def _pause(self):
        if not self.executor:
            return
        if self.btn_pause.text() == "暂停":
            self.executor.pause()
            self.btn_pause.setText("继续")
            self._log("已暂停（当前工况完成后生效）")
        else:
            self.executor.resume()
            self.btn_pause.setText("暂停")
            self._log("已继续")

    def _stop(self):
        if self.executor:
            self.executor.stop()
            self._log("正在停止（当前工况完成后结束）...")
            self.btn_stop.setEnabled(False)

    # ---------- 人工确认（多路换线提示） ----------
    def _confirm_from_worker(self, msg: str) -> bool:
        """工作线程调用：投递到主线程弹窗，阻塞等待用户确认。"""
        self._confirm_msg = msg
        self._confirm_evt.clear()
        self._bridge.confirm_request.emit()
        ok = self._confirm_evt.wait(timeout=600)
        return ok and self._confirm_result

    def _show_confirm(self):
        ret = QMessageBox.question(self, "需要人工操作", self._confirm_msg,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        self._confirm_result = ret == QMessageBox.Yes
        self._confirm_evt.set()
