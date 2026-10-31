"""示波器波形视图控件：网格、通道波形、触发线、FFT、缩放平移。"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal as Signal, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget
import numpy as np

from ..model import ChannelSettings, TimebaseSettings, TriggerSettings, Waveform
from ..measurements import fft_spectrum
from .fonts import ensure_fonts

CHANNEL_COLORS = ["#FFD54A", "#4DD0E1", "#F06292", "#81C784", "#BA68C8", "#FF8A65"]

# 标准 1-2-5 时基档位（s/div）
TIMEBASE_STEPS = [1e-9, 2e-9, 5e-9, 1e-8, 2e-8, 5e-8, 1e-7, 2e-7, 5e-7,
                  1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4,
                  1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0]
VOLT_STEPS = [1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0, 2.0, 5.0, 10.0]


def _fmt_eng(value: float, unit: str = "") -> str:
    """工程计数法格式化：1.00 ms / 2.50 V / 500 kHz。"""
    if not math.isfinite(value):
        return "—"
    if abs(value) < 1e-12:
        return f"0 {unit}".strip()
    prefixes = ["p", "n", "µ", "m", "", "k", "M", "G"]
    exp = math.floor(math.log10(abs(value) * (1 + 1e-12)))
    idx = min(len(prefixes) - 1, max(0, (exp // 3) + 4))
    scaled = value / (10 ** (3 * (idx - 4)))
    if abs(scaled) >= 999.5 and idx < len(prefixes) - 1:
        idx += 1
        scaled /= 1000
    return f"{scaled:.3g} {prefixes[idx]}{unit}".strip()


class ScopeView(QWidget):
    """示波器屏幕：10×8 格，多通道波形 + 可选 FFT 频谱带。"""

    timebaseChanged = Signal(float)
    positionChanged = Signal(float)
    cursorsChanged = Signal(object)
    zoomRangeChanged = Signal(float, float)
    zoomResetRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        ensure_fonts()
        self.setMinimumSize(420, 200)
        self.setMouseTracking(True)
        self.waveforms: dict[str, Waveform] = {}
        self.channels: dict[str, ChannelSettings] = {}
        self.timebase = TimebaseSettings(scale=1e-3)
        self.trigger = TriggerSettings()
        self.fft_enabled = False
        self.fft_source = "CH1"
        self.fft_window = "hann"
        self.fft_span = 0.0
        self.cursor_enabled = False
        self.cursor_times = [-1e-3, 1e-3]
        self.cursor_source = "CH1"
        self._cursor_drag = None
        self.references: dict[str, Waveform] = {}
        self.reference_channels: dict[str, ChannelSettings] = {}
        self._drag_last_x: Optional[int] = None
        self._font = QFont("Microsoft YaHei UI", 9)
        self.data_source = ""
        self.stacked = False
        self.local_zoom = False
        self.zoom_range: Optional[tuple[float, float]] = None
        self._zoom_drag = None

    def set_stacked(self, on: bool) -> None:
        self.stacked = on
        self.update()

    def set_zoom_range(self, selected: Optional[tuple[float, float]]) -> None:
        self.zoom_range = selected
        self.update()

    def _lane_names(self) -> list[str]:
        names = list(dict.fromkeys([*self.waveforms, *self.references]))
        return [name for name in names if self.channels.get(name, self.reference_channels.get(name, ChannelSettings())).enabled]

    def _lane_geometry(self, name: Optional[str] = None) -> tuple[float, float, float, float]:
        x0, y0, gw, gh = self._geometry()
        names = self._lane_names()
        if self.stacked and name in names:
            height = gh / len(names)
            return x0, y0 + names.index(name) * height, gw, height
        return x0, y0, gw, gh

    def _px_to_time(self, x: float) -> float:
        x0, _, gw, _ = self._geometry()
        return self.timebase.position + ((x - x0) / gw - 0.5) * self.timebase.horizontal_divisions * self.timebase.scale

    def _emit_zoom_range(self, start: float, end: float) -> None:
        span = self.timebase.scale * self.timebase.horizontal_divisions
        left, right = self.timebase.position - span / 2, self.timebase.position + span / 2
        minimum = max(span / 100, max((2*w.x_incr for w in self.waveforms.values()), default=0))
        width = min(span, max(minimum, abs(end - start)))
        center = min(right - width / 2, max(left + width / 2, (start + end) / 2))
        self.zoom_range = (center - width / 2, center + width / 2)
        self.update()
        self.zoomRangeChanged.emit(*self.zoom_range)

    def set_cursors_enabled(self, on: bool) -> None:
        self.cursor_enabled = on
        if on:
            self.cursor_times = [self.timebase.position - self.timebase.scale,
                                 self.timebase.position + self.timebase.scale]
        self.update()
        self.cursorsChanged.emit(self.cursor_values())

    def cursor_values(self) -> dict:
        a, b = self.cursor_times
        dt = b - a
        wf = self.waveforms.get(self.cursor_source)
        values = {"a": a, "b": b, "dt": dt, "frequency": 1 / abs(dt) if dt else 0}
        if wf is not None and wf.points and wf.x_start <= min(a, b) and max(a, b) <= wf.x[-1]:
            va, vb = np.interp([a, b], wf.x, wf.y)
            values.update(va=float(va), vb=float(vb), dv=float(vb - va))
        return values

    def set_fft_enabled(self, on: bool) -> None:
        self.fft_enabled = on
        self.update()

    # ---------------- 数据 ----------------
    def set_data(
        self,
        waveforms: dict[str, Waveform],
        channels: dict[str, ChannelSettings],
        timebase: TimebaseSettings,
        trigger: TriggerSettings,
    ) -> None:
        self.waveforms = waveforms
        self.channels = channels
        self.timebase = timebase
        self.trigger = trigger
        self.update()
        if self.cursor_enabled:
            self.cursorsChanged.emit(self.cursor_values())

    # ---------------- 渲染 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor("#0b111b")
        p.fillRect(self.rect(), bg)

        if self.fft_enabled and self.waveforms:
            self._draw_fft_band(p)
            self._draw_annotations(p)
            return
        self._draw_time_grid(p)
        self._draw_waveforms(p)
        self._draw_trigger(p)
        self._draw_zoom_selection(p)
        self._draw_annotations(p)
        if self.cursor_enabled:
            self._draw_cursors(p)

    def _geometry(self) -> tuple[float, float, float, float]:
        w, h = self.width(), self.height()
        return 56.0, 30.0, max(1, w - 80.0), max(1, h - 80.0)

    def _px_per_div(self, gh: float) -> float:
        return gh / 8.0

    def _time_to_px(self, t: float) -> float:
        x0, _, gw, _ = self._geometry()
        half = gw / 2.0
        return x0 + half + (t - self.timebase.position) / self.timebase.scale * (gw / self.timebase.horizontal_divisions)

    def _volts_to_px(self, v: float, ch: ChannelSettings, name: Optional[str] = None) -> float:
        if name is None:
            name = next((key for key, value in self.channels.items() if value.number == ch.number), None)
        _, y0, _, gh = self._lane_geometry(name)
        center = y0 + gh / 2.0
        ppv = (gh / 2.0) / (4.0 * ch.scale)
        return center - (v - ch.screen_center) * ppv

    def _draw_time_grid(self, p: QPainter) -> None:
        x0, y0, gw, gh = self._geometry()
        grid = QPen(QColor("#1E2933"), 1)
        axis = QPen(QColor("#3A4A57"), 1)
        p.setPen(grid)
        divisions = self.timebase.horizontal_divisions
        for i in range(divisions + 1):
            x = x0 + i * gw / divisions
            p.drawLine(int(x), int(y0), int(x), int(y0 + gh))
        lanes = self._lane_names() if self.stacked else [None]
        for name in lanes:
            _, top, _, height = self._lane_geometry(name)
            for j in range(9):
                y = top + j * height / 8.0
                p.setPen(axis if j in (0, 4, 8) else grid)
                p.drawLine(int(x0), int(y), int(x0 + gw), int(y))
            if name:
                ch = self.channels.get(name, self.reference_channels.get(name, ChannelSettings()))
                color_index = int(name[2:]) - 1 if name.startswith("CH") else 4
                p.setFont(self._font)
                p.setPen(QColor(CHANNEL_COLORS[color_index % len(CHANNEL_COLORS)]))
                p.drawText(int(x0 + 8), int(top + 3), 240, 18, Qt.AlignLeft,
                           f"{name}  {_fmt_eng(ch.scale, 'V')}/div")
                ticks = [(0, ch.screen_center + 4*ch.scale), (4, ch.screen_center), (8, ch.screen_center - 4*ch.scale)] if height >= 72 else [(4, ch.screen_center)]
                for j, v in ticks:
                    yy = top + j * height / 8
                    p.drawText(0, int(yy) - (16 if j == 8 else 8 if j == 4 else 0), int(x0 - 5), 16,
                               Qt.AlignRight, _fmt_eng(v, "V"))
        # 触发参考线（水平位置）
        p.setPen(QPen(QColor("#2E4A5A"), 1, Qt.DashLine))
        ref = self._time_to_px(0)
        if x0 <= ref <= x0 + gw:
            p.drawLine(int(ref), int(y0), int(ref), int(y0 + gh))
        # 时基标注
        p.setFont(self._font)
        p.setPen(QColor("#7A8B99"))
        t0 = self.timebase.position - divisions / 2 * self.timebase.scale
        for i in range(divisions + 1):
            t = t0 + i * self.timebase.scale
            p.drawText(int(x0 + i * gw / divisions) - 30, int(y0 + gh + 14), 60, 16,
                       Qt.AlignCenter, _fmt_eng(t, "s"))
        p.drawText(int(x0), int(y0 + gh + 28), 140, 16,
                   Qt.AlignLeft, f"{_fmt_eng(self.timebase.scale, 's')}/div")

    def _draw_waveforms(self, p: QPainter) -> None:
        x0, y0, gw, gh = self._geometry()
        for name, wf in self.references.items():
            ch = self.reference_channels.get(name, ChannelSettings())
            if not self.channels.get(name, ch).enabled:
                continue
            p.save()
            p.setClipRect(QRectF(*self._lane_geometry(name)))
            p.setPen(QPen(QColor("#66778b"), 1, Qt.DotLine))
            p.drawPolyline(self._wave_poly(wf, ch, x0, y0, gw, gh, name))
            p.restore()
        for idx, (name, wf) in enumerate(self.waveforms.items()):
            ch = self.channels.get(name, ChannelSettings(number=idx + 1))
            if not ch.enabled:
                continue
            color_index = int(name[2:]) - 1 if name.startswith("CH") and name[2:].isdigit() else 4
            color = QColor(CHANNEL_COLORS[color_index % len(CHANNEL_COLORS)])
            p.save()
            p.setClipRect(QRectF(*self._lane_geometry(name)))
            p.setPen(QPen(color, 1.5))
            poly = self._wave_poly(wf, ch, x0, y0, gw, gh, name)
            if poly.size() > 1:
                p.drawPolyline(poly)
            p.restore()
        if self.stacked:
            p.setFont(self._font)
            p.setPen(QColor("#91a7bf"))
            p.drawText(int(x0), 4, 500, 18, Qt.AlignLeft,
                       "ZOOM 局部波形 · 通道堆叠" if self.local_zoom else "通道堆叠 · 共用时间轴")
            return
        for idx, (name, wf) in enumerate(self.waveforms.items()):
            ch = self.channels.get(name, ChannelSettings(number=idx + 1))
            color_index = int(name[2:]) - 1 if name.startswith("CH") and name[2:].isdigit() else 4
            color = QColor(CHANNEL_COLORS[color_index % len(CHANNEL_COLORS)])
            p.setFont(self._font)
            p.setPen(color)
            p.drawText(int(x0 + idx * 150), 5, 146, 18, Qt.AlignLeft,
                       f"{name}  {_fmt_eng(ch.scale, 'V')}/div")

    def _wave_poly(self, wf: Waveform, ch: ChannelSettings, x0, y0, gw, gh, name=None):
        """波形 → QPolygonF（批量绘制，比逐点 lineTo 快得多）。"""
        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QPolygonF

        n = wf.points
        if n < 2:
            return QPolygonF()
        # 先截取可见区间；每个像素桶保留极小/极大值，避免窄脉冲被抽样丢弃。
        half_span = self.timebase.horizontal_divisions / 2 * self.timebase.scale
        start = max(0, int((self.timebase.position - half_span - wf.x_start) / wf.x_incr) - 1)
        end = min(n, int((self.timebase.position + half_span - wf.x_start) / wf.x_incr) + 2)
        if start >= end:
            return QPolygonF()
        indices = np.arange(start, end)
        step = max(1, int(len(indices) // max(1, gw)))
        if step > 1:
            full = len(indices) // step * step
            blocks = wf.y[start:start + full].reshape(-1, step)
            bases = np.arange(len(blocks)) * step + start
            extrema = np.column_stack((bases + np.argmin(blocks, axis=1),
                                       bases + np.argmax(blocks, axis=1)))
            indices = np.concatenate((np.sort(extrema, axis=1).ravel(), indices[full:]))
        xs = wf.x_start + indices * wf.x_incr
        ys = wf.y[indices]
        px = self._time_to_px
        py = self._volts_to_px
        pts = [QPointF(px(float(xv)), py(float(yv), ch, name)) for xv, yv in zip(xs, ys)]
        return QPolygonF(pts)

    def _draw_trigger(self, p: QPainter) -> None:
        src = self.trigger.source.upper()
        ch = self.channels.get(src)
        if ch is None:
            return
        x0, y0, gw, gh = self._lane_geometry(src)
        y = self._volts_to_px(self.trigger.level, ch, src)
        if y0 <= y <= y0 + gh:
            p.setPen(QPen(QColor("#FF5252"), 1, Qt.DashLine))
            p.drawLine(int(x0), int(y), int(x0 + gw), int(y))
            p.setFont(self._font)
            p.setPen(QColor("#FF8A80"))
            p.drawText(int(x0 + gw - 70), int(y) - 18, 70, 16, Qt.AlignRight,
                       f"{src} {self.trigger.level:g}V")

    def _draw_zoom_selection(self, p: QPainter) -> None:
        if self.zoom_range is None:
            return
        x0, y0, gw, gh = self._geometry()
        a, b = (min(x0+gw, max(x0, self._time_to_px(t))) for t in self.zoom_range)
        p.save()
        p.setClipRect(QRectF(x0, y0, gw, gh))
        p.fillRect(QRectF(a, y0, b-a, gh), QColor(75, 150, 255, 28))
        p.setPen(QPen(QColor("#70b0ff"), 2))
        p.drawRect(QRectF(a, y0+1, b-a, gh-2))
        for x in (a, b):
            p.fillRect(QRectF(x-3, y0+gh/2-10, 6, 20), QColor("#9ac8ff"))
        p.setFont(self._font)
        p.drawText(int(a+6), int(y0+5), max(1, int(b-a-12)), 18, Qt.AlignLeft, "ZOOM")
        p.restore()

    def _draw_annotations(self, p: QPainter) -> None:
        p.setFont(self._font)
        p.setPen(QColor("#55677A"))
        if self.fft_enabled:
            p.drawText(56, 4, self.width()-80, 18, Qt.AlignLeft, f"{self.data_source} · FFT")
            return
        p.drawText(220, self.height() - 16, self.width() - 420, 16,
                   Qt.AlignCenter, self.data_source)
        status = ""
        if self.timebase.sample_rate and not self.fft_enabled:
            status = f"{_fmt_eng(self.timebase.sample_rate, 'Sa/s')}"
        p.drawText(int(self.width() - 180), int(self.height() - 16), 170, 16,
                   Qt.AlignRight, status)

    def _draw_fft_band(self, p: QPainter) -> None:
        """FFT 频谱带（30% 高度），显示第一个通道的频谱。"""
        wf = self.waveforms.get(self.fft_source)
        if wf is None:
            p.setPen(QColor("#7A8B99"))
            p.drawText(self.rect(), Qt.AlignCenter, "FFT 源通道暂无数据")
            return
        freqs, mag = fft_spectrum(wf, self.fft_window)
        if freqs.size < 2:
            return
        x0, y0, gw, gh = self._geometry()
        fh = gh
        bg = QColor("#0b111b")
        p.fillRect(self.rect(), bg)
        grid = QPen(QColor("#1E2933"), 1)
        p.setPen(grid)
        for i in range(11):
            x = x0 + i * gw / 10.0
            p.drawLine(int(x), int(y0), int(x), int(y0 + fh))
        p.setPen(QPen(QColor("#7A8B99"), 1.5))
        fmax = min(self.fft_span, float(freqs[-1])) if self.fft_span else float(freqs[-1])
        mask = freqs <= fmax
        freqs, mag = freqs[mask], mag[mask]
        upper = np.ceil(np.max(mag) / 20) * 20
        lower = upper - 100
        for i in range(6):
            yy = y0 + i * fh / 5
            p.setPen(QColor("#1E2933"))
            p.drawLine(int(x0), int(yy), int(x0 + gw), int(yy))
            p.setPen(QColor("#7A8B99"))
            p.drawText(0, int(yy) - 8, 48, 16, Qt.AlignRight, f"{upper - i * 20:g}")
        pen = QPen(QColor("#4DD0E1"), 1.5)
        p.setPen(pen)
        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QPolygonF

        base = y0 + fh
        step = max(1, int(freqs.size // (gw * 2)))
        x = lambda f: x0 + (f / fmax) * gw  # noqa: E731
        y = lambda m: base - (max(lower, m) - lower) / (upper - lower) * fh  # noqa: E731
        pts = [QPointF(x(float(f)), y(float(m))) for f, m in zip(freqs[::step], mag[::step])]
        if len(pts) > 1:
            p.drawPolyline(QPolygonF(pts))
        p.setFont(self._font)
        p.setPen(QColor("#7A8B99"))
        p.drawText(int(x0), int(y0 + fh + 14), 300, 16, Qt.AlignLeft,
                   f"FFT {wf.channel} · {self.fft_window} · span {_fmt_eng(fmax, 'Hz')}")
        p.drawText(int(x0 + gw - 120), int(y0 + fh + 14), 120, 16, Qt.AlignRight, "dBV (峰值)")
        for i in range(6):
            p.drawText(int(x0 + i * gw / 5) - 35, int(y0 + fh + 30), 70, 16,
                       Qt.AlignCenter, _fmt_eng(fmax * i / 5, "Hz"))

    def _draw_cursors(self, p: QPainter) -> None:
        x0, y0, gw, gh = self._geometry()
        for label, t in zip(("A", "B"), self.cursor_times):
            x = self._time_to_px(t)
            if x0 <= x <= x0 + gw:
                p.setPen(QPen(QColor("#d6e1ee"), 1, Qt.DashLine))
                p.drawLine(int(x), int(y0), int(x), int(y0 + gh))
                p.drawText(int(x) + 5, int(y0) + 4, 24, 20, Qt.AlignLeft, label)

    # ---------------- 交互 ----------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.fft_enabled:
            return
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        if self.local_zoom:
            new_scale = self.timebase.scale * 2 ** (-int(steps))
            self.timebaseChanged.emit(new_scale)
            return
        cur = self.timebase.scale
        idx = min(range(len(TIMEBASE_STEPS)),
                  key=lambda i: abs(TIMEBASE_STEPS[i] - cur))
        new_idx = max(0, min(len(TIMEBASE_STEPS) - 1, idx - int(steps)))
        new_scale = TIMEBASE_STEPS[new_idx]
        self.timebase = replace(self.timebase, scale=new_scale)
        self.update()
        self.timebaseChanged.emit(new_scale)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.fft_enabled:
            return
        if event.button() == Qt.LeftButton:
            if self.cursor_enabled:
                distances = [abs(self._time_to_px(t) - event.localPos().x()) for t in self.cursor_times]
                if min(distances) < 12:
                    self._cursor_drag = int(np.argmin(distances))
                    return
            x0, y0, gw, gh = self._geometry()
            x, y = event.localPos().x(), event.localPos().y()
            if self.zoom_range is not None and not event.modifiers() & Qt.AltModifier and x0 <= x <= x0+gw and y0 <= y <= y0+gh:
                a, b = self.zoom_range
                distances = [abs(self._time_to_px(t)-x) for t in (a,b)]
                mode = ("left" if distances[0] <= distances[1] else "right") if min(distances) < 10 else ("move" if a <= self._px_to_time(x) <= b else "select")
                self._zoom_drag = (mode, self._px_to_time(x), a, b)
                return
            self._drag_last_x = event.localPos().x()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._cursor_drag is not None:
            x0, _, gw, _ = self._geometry()
            self.cursor_times[self._cursor_drag] = self._px_to_time(min(x0+gw, max(x0, event.localPos().x())))
            self.update()
            self.cursorsChanged.emit(self.cursor_values())
            return
        if self._zoom_drag is not None:
            mode, anchor, a, b = self._zoom_drag
            t = self._px_to_time(event.localPos().x())
            if mode == "move":
                self._emit_zoom_range(a+t-anchor, b+t-anchor)
            elif mode == "left":
                self._emit_zoom_range(min(t,b), b)
            elif mode == "right":
                self._emit_zoom_range(a, max(t,a))
            else:
                self._emit_zoom_range(anchor, t)
            return
        if self._drag_last_x is not None:
            dx_px = event.localPos().x() - self._drag_last_x
            self._drag_last_x = event.localPos().x()
            _, _, gw, _ = self._geometry()
            dt = -dx_px / gw * self.timebase.horizontal_divisions * self.timebase.scale
            self.timebase = replace(self.timebase, position=self.timebase.position + dt)
            self.update()
            self.positionChanged.emit(self.timebase.position)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._zoom_drag is not None:
            mode, anchor, a, b = self._zoom_drag
            t = self._px_to_time(event.localPos().x())
            if mode == "select" and abs(t-anchor) < self.timebase.scale * .05:
                self._emit_zoom_range(t-(b-a)/2, t+(b-a)/2)
        self._zoom_drag = None
        self._drag_last_x = None
        self._cursor_drag = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.local_zoom or self.zoom_range is not None:
            self.zoomResetRequested.emit()
            return
        self.positionChanged.emit(0.0)
        self.timebaseChanged.emit(1e-3)
