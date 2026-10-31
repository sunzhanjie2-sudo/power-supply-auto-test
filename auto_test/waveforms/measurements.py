"""测量计算：波形统计 + 频率估计 + FFT 频谱。纯函数，可单测。"""
from __future__ import annotations

import numpy as np

from .model import Measurement, Waveform


def _estimate_frequency(x: np.ndarray, y: np.ndarray) -> float:
    """上升沿过零法粗估频率（Hz）。"""
    if len(y) < 3 or np.ptp(y) <= 1e-12:
        return 0.0
    low, high = np.percentile(y, [5, 95])
    threshold = (low + high) / 2
    hysteresis = (high - low) * 0.05
    candidates = np.flatnonzero((y[:-1] < threshold) & (y[1:] >= threshold))
    crossings = []
    previous = 0
    for j, i in enumerate(candidates):
        if not np.any(y[previous:i + 1] < threshold - hysteresis):
            continue
        end = int(candidates[j + 1]) if j + 1 < len(candidates) else len(y) - 1
        if not np.any(y[i + 1:end + 1] > threshold + hysteresis):
            continue
        t = x[i] + (threshold - y[i]) / (y[i + 1] - y[i]) * (x[i + 1] - x[i])
        crossings.append(t)
        previous = i + 1
    if len(crossings) < 2:
        return 0.0
    periods = np.diff(crossings)
    period = float(np.median(periods))
    # 极少采样点的周期或间隔散乱的噪声，不能给出可信频率。
    if period < 8 * float(np.median(np.diff(x))) or np.std(periods) > 0.2 * period:
        return 0.0
    return 1 / period


def measure(wf: Waveform) -> list[Measurement]:
    """对单条波形计算常用测量项。"""
    y = wf.y
    if wf.points < 2 or not np.all(np.isfinite(y)):
        return []
    freq = _estimate_frequency(wf.x, y)
    if wf.raw is not None and np.issubdtype(wf.raw.dtype, np.integer) and np.ptp(wf.raw.astype(float)) <= 3:
        # 只有几个量化码的变化，保留电压统计但不宣称存在周期信号。
        freq = 0.0
    duty = 0.0
    if freq:
        threshold = (np.percentile(y, 5) + np.percentile(y, 95)) / 2
        rise = np.flatnonzero((y[:-1] < threshold) & (y[1:] >= threshold))
        fall = np.flatnonzero((y[:-1] >= threshold) & (y[1:] < threshold))
        ratios = []
        for left, right in zip(rise[:-1], rise[1:]):
            falling = fall[(fall > left) & (fall < right)]
            if falling.size == 1:
                ratios.append((falling[0] - left) / (right - left))
        if ratios:
            duty = float(np.median(ratios) * 100)
    out = [
        Measurement("Vpp", float(np.ptp(y)), "V"),
        Measurement("Vmax", float(np.max(y)), "V"),
        Measurement("Vmin", float(np.min(y)), "V"),
        Measurement("Vavg", float(np.mean(y)), "V"),
        Measurement("Vrms", float(np.sqrt(np.mean(y**2))), "V"),
        Measurement("AC RMS", float(np.std(y)), "V"),
        Measurement("Freq", freq, "Hz"),
        Measurement("Period", 1.0 / freq if freq > 0 else 0.0, "s"),
        Measurement("Duty", duty, "%"),
    ]
    return out


def fft_spectrum(wf: Waveform, window: str = "hann") -> tuple[np.ndarray, np.ndarray]:
    """单边峰值频谱 (Hz, dBV)，去直流，校正窗函数的相干增益。"""
    n = wf.points
    if n < 8 or wf.x_incr <= 0:
        return np.zeros(0), np.zeros(0)
    windows = {"hann": np.hanning, "hamming": np.hamming, "blackman": np.blackman,
               "rectangular": np.ones}
    if window not in windows:
        raise ValueError(f"未知 FFT 窗函数：{window}")
    win = windows[window](n)
    y = (wf.y - float(np.mean(wf.y))) * win
    spec = np.fft.rfft(y)
    mag = np.abs(spec) * 2.0 / np.sum(win)
    freqs = np.fft.rfftfreq(n, d=wf.x_incr)
    # 0Hz 分量不乘 2
    if mag.size > 0:
        mag[0] *= 0.5
    if n % 2 == 0:
        mag[-1] *= 0.5
    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-12))
    return freqs, mag_db
