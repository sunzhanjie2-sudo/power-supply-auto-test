"""Live oscilloscope preview. Instrument I/O never runs on the GUI thread."""

import threading

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)
from ..waveforms.ui.scope_view import ScopeView


class WaveformWorker(QThread):
    frame = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, scope, channel: int, parent=None):
        super().__init__(parent)
        self.scope = scope
        self.channel = channel
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                if not self.scope.connected or not self.scope.comm.is_connected:
                    self.error.emit("示波器连接已断开")
                    break
                self.frame.emit(self.scope.get_waveform_capture(self.channel))
            except Exception as exc:
                self.error.emit(str(exc))
                break
            self._stop.wait(0.35)


class WaveformWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("示波器实时波形")
        self.resize(900, 560)
        self._scope = None
        self._worker = None

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.channel = QComboBox()
        self.channel.addItems(["CH1", "CH2", "CH3", "CH4"])
        self.channel.currentIndexChanged.connect(self._restart)
        self.btn_start = QPushButton("开始预览")
        self.btn_start.clicked.connect(self.start_preview)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self.stop_preview)
        self.btn_stop.setEnabled(False)
        self.status = QLabel("等待连接示波器")
        controls.addWidget(QLabel("通道"))
        controls.addWidget(self.channel)
        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        controls.addWidget(self.status, 1)
        layout.addLayout(controls)

        self.view = ScopeView()
        self.view.data_source = "真实仪器 · 等待采集"
        layout.addWidget(self.view)

    def set_scope(self, scope):
        if scope is self._scope:
            return
        if not self.stop_preview():
            return
        self._scope = scope
        channels = getattr(scope, "_channels", None) or [1, 2]
        self.channel.blockSignals(True)
        self.channel.clear()
        for ch in channels:
            self.channel.addItem(f"CH{ch}", ch)
        self.channel.blockSignals(False)
        self.status.setText("已连接，点击开始预览")

    def start_preview(self):
        if self._worker is not None:
            return
        if (self._scope is None or not self._scope.connected
                or not self._scope.comm or not self._scope.comm.is_connected):
            self.status.setText("请先连接示波器")
            return
        channel = self.channel.currentData()
        if channel is None:
            self.status.setText("请选择示波器通道")
            return
        self._worker = WaveformWorker(self._scope, channel, self)
        self._worker.frame.connect(self._draw_frame)
        self._worker.error.connect(self._show_error)
        self._worker.finished.connect(self._worker_finished)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status.setText("读取波形中…")
        self._worker.start()

    def stop_preview(self):
        worker = self._worker
        if worker is not None:
            worker.stop()
            worker.wait(6000)  # a VISA waveform read may take up to 4 s
            if worker.isRunning():
                self.status.setText("等待示波器读取结束")
                return False
            self._worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.setText("预览已停止")
        return True

    def _restart(self):
        if self._worker is not None and self.stop_preview():
            self.start_preview()

    def _draw_frame(self, record):
        if self.sender() is not self._worker:
            return
        self.view.set_data(record.waveforms, record.settings['channels'],
                           record.settings['timebase'], record.settings['trigger'])
        self.view.data_source = "真实仪器 · 同帧采样"
        waveform = next(iter(record.waveforms.values()))
        self.status.setText(f"{waveform.channel}  {waveform.points} 点  Vpp={waveform.vpp:.4g} V")

    def _show_error(self, message):
        if self.sender() is self._worker:
            self.view.data_source = "保留上一帧 · 采集异常"
            self.view.update()
            self.status.setText(f"读取失败：{message}")

    def _worker_finished(self):
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
        worker.deleteLater()

    def closeEvent(self, event):
        if self.stop_preview():
            event.accept()
        else:
            event.ignore()
