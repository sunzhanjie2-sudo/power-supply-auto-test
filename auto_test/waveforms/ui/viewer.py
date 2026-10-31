"""Offline waveform workbench. It never owns or writes to an instrument."""
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                            QLabel, QMessageBox, QPushButton, QVBoxLayout)

from ..measurements import measure
from ..record import WaveformRecord
from .scope_view import ScopeView, _fmt_eng


class WaveformViewer(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("工况波形 · 离线回放")
        self.resize(1100, 800)
        self.record = None
        self.path = ""
        self._timebase = None
        self._reference = None
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        open_button = QPushButton("打开历史波形")
        open_button.clicked.connect(self.open_file)
        toolbar.addWidget(open_button)
        reset = QPushButton("复位视图")
        reset.clicked.connect(self.reset_view)
        toolbar.addWidget(reset)
        self.channel = QComboBox()
        self.channel.currentTextChanged.connect(self._channel_changed)
        toolbar.addWidget(self.channel)
        self.cursors = QCheckBox("游标 A/B")
        self.cursors.toggled.connect(self._cursors_changed)
        toolbar.addWidget(self.cursors)
        self.zoom = QCheckBox("ZOOM 放大")
        self.zoom.toggled.connect(self._zoom_changed)
        toolbar.addWidget(self.zoom)
        toolbar.addWidget(QLabel("电压放大："))
        self.gain = QComboBox()
        for gain in (1, 2, 5, 10, 20):
            self.gain.addItem(f"{gain}×", gain)
        self.gain.currentIndexChanged.connect(self._update_views)
        toolbar.addWidget(self.gain)
        self.reference = QCheckBox("保留参考")
        self.reference.toggled.connect(self._reference_changed)
        toolbar.addWidget(self.reference)
        self.fft = QCheckBox("FFT")
        self.fft.toggled.connect(self._fft_changed)
        toolbar.addWidget(self.fft)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.details = QLabel("打开测试生成的 NPZ 或 CSV，可离线查看；显示操作只调整本地视图。")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.capture_info = QLabel()
        layout.addWidget(self.capture_info)
        self.view = ScopeView()
        self.view.local_zoom = True
        self.view.data_source = "离线波形"
        self.view.timebaseChanged.connect(self._scale_changed)
        self.view.positionChanged.connect(self._position_changed)
        self.view.zoomRangeChanged.connect(self._range_changed)
        self.view.zoomResetRequested.connect(self.reset_view)
        self.view.cursorsChanged.connect(lambda values: self._sync_cursors(self.view))
        layout.addWidget(self.view, 3)
        self.zoom_view = ScopeView()
        self.zoom_view.local_zoom = True
        self.zoom_view.setMinimumHeight(220)
        self.zoom_view.timebaseChanged.connect(self._zoom_scale_changed)
        self.zoom_view.positionChanged.connect(self._zoom_position_changed)
        self.zoom_view.zoomResetRequested.connect(self.reset_view)
        self.zoom_view.cursorsChanged.connect(lambda values: self._sync_cursors(self.zoom_view))
        self.zoom_view.hide()
        layout.addWidget(self.zoom_view, 2)
        self.fft_view = ScopeView()
        self.fft_view.set_fft_enabled(True)
        self.fft_view.hide()
        layout.addWidget(self.fft_view, 2)
        self.stats = QLabel()
        self.stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.stats)
        self.cursor_info = QLabel("滚轮缩放时间轴，拖动平移，双击复位；游标可拖动。")
        layout.addWidget(self.cursor_info)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开工况波形", "",
                                             "波形记录 (*.npz *.csv);;ScopeHost 归档 (*.npz);;CSV (*.csv)")
        if path:
            try:
                self.load_file(path)
            except Exception as exc:
                QMessageBox.warning(self, "无法打开波形", str(exc))

    def load_file(self, path):
        record = WaveformRecord.load(path)
        self.record, self.path = record, str(path)
        self.channel.blockSignals(True)
        self.channel.clear()
        self.channel.addItems(list(record.waveforms))
        self.channel.blockSignals(False)
        task = record.context.get("task", {})
        result = record.context.get("result", {})
        condition = ""
        if task:
            condition = f"{task.get('name', '')}  |  初始 Vin {task.get('vin', '')} V  |  环温 {task.get('temp', '')}℃"
        self.details.setText(f"{Path(path).name}\n{record.identity}  {condition}  {result.get('status', '')}")
        self.setWindowTitle(f"工况波形 · {Path(path).name}")
        self.reset_view()
        return record

    def reset_view(self):
        if not self.record:
            return
        self._timebase = replace(self.record.settings["timebase"])
        self.gain.blockSignals(True)
        self.gain.setCurrentIndex(0)
        self.gain.blockSignals(False)
        tb = self._timebase
        half = tb.scale * tb.horizontal_divisions / 8
        self.view.set_zoom_range((tb.position-half, tb.position+half) if self.zoom.isChecked() else None)
        self._update_views()
        self._cursors_changed(self.cursors.isChecked())

    def _update_views(self, *_):
        if not self.record:
            return
        channels = {name: replace(ch, scale=ch.scale/self.gain.currentData())
                    for name, ch in self.record.settings["channels"].items()}
        trigger = self.record.settings["trigger"]
        self.view.set_data(self.record.waveforms, channels, self._timebase, trigger)
        self.view.references = self._reference.waveforms if self._reference else {}
        self.view.reference_channels = self._reference.settings["channels"] if self._reference else {}
        self.view.data_source = "离线回放 · 保存的采样数据"
        if self.view.zoom_range:
            a, b = self.view.zoom_range
            ztb = replace(self._timebase, scale=(b-a)/self._timebase.horizontal_divisions, position=(a+b)/2)
            self.zoom_view.set_data(self.record.waveforms, channels, ztb, trigger)
            self.zoom_view.data_source = "ZOOM · 局部波形"
        self.fft_view.set_data(self.record.waveforms, channels, self.record.settings["timebase"], trigger)
        self._channel_changed(self.channel.currentText())

    def _clamp_timebase(self, scale, position):
        base = self.record.settings["timebase"]
        minimum = max(wf.x_incr for wf in self.record.waveforms.values())*2/base.horizontal_divisions
        scale = min(base.scale, max(minimum, scale))
        margin = (base.scale-scale)*base.horizontal_divisions/2
        position = min(base.position+margin, max(base.position-margin, position))
        return replace(base, scale=scale, position=position)

    def _scale_changed(self, scale):
        if self.record:
            self._timebase = self._clamp_timebase(scale, self._timebase.position)
            self._update_views()

    def _position_changed(self, position):
        if self.record:
            self._timebase = self._clamp_timebase(self._timebase.scale, position)
            self._update_views()

    def _zoom_changed(self, on):
        self.zoom_view.setVisible(on)
        if self.record:
            tb = self._timebase
            half = tb.scale*tb.horizontal_divisions/8
            self.view.set_zoom_range((tb.position-half, tb.position+half) if on else None)
            self._update_views()

    def _range_changed(self, a, b):
        self._update_views()

    def _zoom_scale_changed(self, scale):
        if self.view.zoom_range:
            a, b = self.view.zoom_range
            half = scale*self._timebase.horizontal_divisions/2
            self.view._emit_zoom_range((a+b)/2-half, (a+b)/2+half)

    def _zoom_position_changed(self, position):
        if self.view.zoom_range:
            a, b = self.view.zoom_range
            self.view._emit_zoom_range(position-(b-a)/2, position+(b-a)/2)

    def _cursors_changed(self, on):
        self.view.set_cursors_enabled(on)
        self.zoom_view.set_cursors_enabled(on)

    def _sync_cursors(self, source):
        target = self.zoom_view if source is self.view else self.view
        target.cursor_times = list(source.cursor_times)
        target.update()
        value = source.cursor_values()
        if source.cursor_enabled:
            dv = _fmt_eng(value['dv'], 'V') if 'dv' in value else '超出采样范围'
            self.cursor_info.setText(f"A {_fmt_eng(value['a'], 's')}  B {_fmt_eng(value['b'], 's')}  |  "
                                     f"Δt {_fmt_eng(value['dt'], 's')}  ΔV {dv}")

    def _channel_changed(self, name):
        if not self.record or name not in self.record.waveforms:
            return
        self.view.cursor_source = self.zoom_view.cursor_source = name
        self.fft_view.fft_source = name
        self.fft_view.update()
        values = {m.name: m for m in measure(self.record.waveforms[name])}
        coupling = self.record.settings['channels'][name].coupling.value
        ch = self.record.settings['channels'][name]
        tb = self.record.settings['timebase']
        self.capture_info.setText(f"保存的采集设置：{name} · {coupling} · {_fmt_eng(ch.scale, 'V')}/div · "
                                  f"偏移 {_fmt_eng(ch.offset, 'V')} · {_fmt_eng(tb.scale, 's')}/div · "
                                  f"{self.record.waveforms[name].points} 点")
        self.stats.setText(f"{name} · {coupling} 耦合采样统计：" + "  |  ".join(
            f"{key} {_fmt_eng(values[key].value, values[key].unit)}"
            for key in ('Vmin', 'Vmax', 'Vpp', 'Vavg', 'Vrms') if key in values))
        self._sync_cursors(self.view)

    def _reference_changed(self, on):
        self._reference = self.record if on else None
        self._update_views()

    def _fft_changed(self, on):
        self.fft_view.setVisible(on)
