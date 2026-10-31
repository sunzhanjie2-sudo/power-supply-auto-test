# -*- coding: utf-8 -*-
"""黑盒测试用例执行器：按用例工况逐项执行，自动回填数据与波形到 Excel。

要点：
  - 温箱流程已移除：环温由用户输入，build_tasks() 按 temp 只生成该环温块的任务；
    用例 Excel 仍含全部环温块，换环温后可再次执行回填其他块。
  - 当前台架为单路 Buck（单通道负载+单探头）：n=1 全自动无人工干预；
    n>1 保留逐通道顺序执行，切换通道前经 on_confirm 请求人工确认（多路同时加载暂不支持）。
  - 必需波形、测量值或归档缺失时标记 ERROR，逐工况保存同帧采样和设置。
  - 每完成一个工况即把内存工作簿保存到磁盘，中途停止/异常不丢已完成数据。
  - 判定：稳压精度/动态包络取 Vout min/max 限值；纹波取 Vout_typ×纹波%；
    启机关机只判上冲（max vs Vout max），下电时 min 自然归 0 不参与判定。
"""
import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter

from .test_case_generator import (
    PowerSpec, TestCaseGenerator, TestCaseLayout, _cn, ripple_plan, writable_cell,
)
from ..reporting.waveform_archiver import WaveformArchiver
from ..reporting.case_report import CaseReport


KIND_SHEET = {
    "ripple": "纹波与稳压精度测试",
    "dynamic": "动态响应测试",
    "stability": "动态稳定度测试",
    "startup": "启机关机测试",
}
KIND_NAME = {
    "ripple": "纹波与稳压精度",
    "dynamic": "动态响应",
    "stability": "动态稳定度",
    "startup": "启机关机",
}
RESULT_COLS_ATTR = {
    "纹波与稳压精度测试": "ripple_result_cols",
    "动态响应测试": "dynamic_result_cols",
    "动态稳定度测试": "stability_result_cols",
    "启机关机测试": "startup_result_cols",
}

# 示波器垂直档位（1-2-5 序列）
_STD_SCALES = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50]
# 实际采集时基：需覆盖 10ms 级负载跳变与 500ms 级 Vin 跳变（模板要求的刻度为文字描述）
DYNAMIC_TIMEBASE = 5e-3     # 动态响应：窗口约 60ms
STABILITY_TIMEBASE = 5e-1   # 动态稳定度：A/B 段各 500ms，窗口约 6s
STARTUP_TIMEBASE = 1e-2     # 启机关机：模板要求 10ms/div
SETTLE_STEADY = 1.5         # 稳态建立等待(s)
TEMP_MATCH_TOL = 0.5        # 环温匹配容差(℃)


# ============ 任务模型 ============

@dataclass
class CaseTask:
    kind: str            # ripple / dynamic / stability / startup
    sheet: str
    row: int             # Excel 数据行（该工况结果列所在行）
    channel: int         # 被测通道（0 基）
    temp: float          # 环温(℃)
    name: str            # 工况名
    vin: float           # 输入电压（稳定度工况为显示值，实际按 Vin_min↔Vin_max 跳变）
    currents: tuple      # 各路静态电流设定(A)
    i_lo: float = 0.0    # 动态/稳定度 轻载电流(A)
    i_hi: float = 0.0    # 动态/稳定度 满载电流(A)
    label: str = ""      # 启机子项（轻载上电/轻载下电/过载下电）
    limit_lo: float = 0.0   # 判据下限：Vout_min(V)
    limit_hi: float = 0.0   # 判据上限：Vout_max(V)
    ripple_limit: float = 0.0  # 纹波判据(Vpp)

    @property
    def test_item(self) -> str:
        return f"{KIND_NAME[self.kind]}-{self.label}" if self.label else KIND_NAME[self.kind]


def build_tasks(spec: PowerSpec, kinds=("ripple", "dynamic", "stability", "startup"),
                temp: Optional[float] = None) -> List[CaseTask]:
    """生成执行任务清单。

    :param temp: 用户输入的环温；None=全部环温块，否则只生成匹配块（容差 TEMP_MATCH_TOL）。
    行号与 TestCaseGenerator 的布局严格对应，回填前须用同一 spec 生成用例。
    """
    def _hit(t: float) -> bool:
        return temp is None or abs(t - temp) <= TEMP_MATCH_TOL

    n, outs = spec.n, spec.outputs
    tasks: List[CaseTask] = []

    if "ripple" in kinds:
        plan, _ = ripple_plan(spec)
        for (t, name, ctype, cur, row) in plan:
            if not _hit(t):
                continue
            for ch in range(n):
                o = outs[ch]
                tasks.append(CaseTask("ripple", KIND_SHEET["ripple"], row, ch, t, name,
                                      spec.vin_typ, tuple(cur),
                                      limit_lo=o.vmin(), limit_hi=o.vmax(),
                                      ripple_limit=o.ripple()))

    def _dyn_rows():
        rows, r = [], 13
        for t in spec.temperatures():
            for vi in range(3):
                rows.append((t, vi, r))
                r += 2
        return rows

    vins = (spec.vin_min, spec.vin_typ, spec.vin_max)
    vin_label = ("最小", "典型", "最大")

    if "dynamic" in kinds:
        for (t, vi, row) in _dyn_rows():
            if not _hit(t):
                continue
            name = f"{_cn(n)}路同时轻载满载跳变，Vin{vin_label[vi]}"
            for ch in range(n):
                o = outs[ch]
                tasks.append(CaseTask(
                    "dynamic", KIND_SHEET["dynamic"], row, ch, t, name, vins[vi],
                    tuple(round(o.iout("typ"), 4) for o in outs),
                    i_lo=o.iout("min"), i_hi=o.iout("max"),
                    limit_lo=o.vmin(), limit_hi=o.vmax(), ripple_limit=o.ripple()))

    if "stability" in kinds:
        for (t, vi, row) in _dyn_rows():
            if not _hit(t):
                continue
            name = f"{_cn(n)}路同时轻载满载跳变，Vin{vin_label[vi]}"
            for ch in range(n):
                o = outs[ch]
                tasks.append(CaseTask(
                    "stability", KIND_SHEET["stability"], row, ch, t, name, vins[vi],
                    tuple(round(o.iout("typ"), 4) for o in outs),
                    i_lo=o.iout("min"), i_hi=o.iout("max"),
                    limit_lo=o.vmin(), limit_hi=o.vmax(), ripple_limit=o.ripple()))

    if "startup" in kinds:
        labels = ("轻载上电", "轻载下电", "满载下电")
        for (t, vi, row) in _dyn_rows():
            if not _hit(t):
                continue
            lab = labels[vi]
            curs = [o.iout("max") if lab == "满载下电" else o.iout("min") for o in outs]
            for ch in range(n):
                o = outs[ch]
                tasks.append(CaseTask(
                    "startup", KIND_SHEET["startup"], row, ch, t, lab, vins[vi],
                    tuple(round(c, 4) for c in curs), label=lab,
                    limit_lo=o.vmin(), limit_hi=o.vmax(), ripple_limit=o.ripple()))
    return tasks


def available_temps(spec: PowerSpec) -> List[float]:
    """用例中存在的环温块列表（去重保序）。"""
    temps = []
    for t in (spec.temp_min, spec.temp_typ, spec.temp_max):
        if not any(abs(t - x) <= TEMP_MATCH_TOL for x in temps):
            temps.append(t)
    return temps


# ============ 执行器 ============

class CaseExecutor:
    """用例执行器（后台线程）。

    回调均在工作线程触发，GUI 需经信号桥投递到主线程：
      on_task_start(task, index, total)
      on_task_done(task, result, index, total)   result: {status,vmin,vmax,ripple,png,note}
      on_confirm(message) -> bool                需人工接线时询问（可阻塞等待用户）
      on_error(message)                          非致命错误（如 Excel 被占用）
      on_finished()                              全部结束（含停止/异常）
    """

    def __init__(self, spec: PowerSpec, instruments: dict, wb, tasks: List[CaseTask],
                 output_path: str, archiver_dir: str = None,
                 on_task_start=None, on_task_done=None, on_confirm=None,
                 on_error=None, on_finished=None):
        self.spec = spec
        self.instruments = instruments or {}
        self.wb = wb
        self.tasks = tasks
        self.output_path = output_path
        self.archiver = WaveformArchiver(archiver_dir) if archiver_dir else None
        self.on_task_start = on_task_start
        self.on_task_done = on_task_done
        self.on_confirm = on_confirm
        self.on_error = on_error
        self.on_finished = on_finished
        # 输入限流：按满载功率与最低输入电压推导（效率按 0.8，留 25% 裕量）。
        # 仪器里残留的小限流值会把 DUT 输入钳死导致全线 FAIL，必须显式覆盖。
        p_total = sum(o.pout_max for o in spec.outputs)
        self.iin_limit = round(max(1.0, p_total / (spec.vin_min * 0.8) * 1.25), 2)

        self._pause_evt = threading.Event()
        self._stop_flag = False
        self._thread: Optional[threading.Thread] = None
        self._last_channel_key = None
        self.error_msg = ""      # 致命错误
        self.save_error = ""     # 最后一次保存失败原因（文件被占用等）
        self.was_stopped = False
        self.results = []
        self._capture = None
        self._archive_paths = {}
        self.report = CaseReport(wb, spec, tasks, os.path.dirname(output_path)) if wb is not None else None

    @property
    def counts(self):
        from collections import Counter
        return Counter(result["status"] for _, result in self.results)

    @property
    def all_passed(self):
        return bool(self.tasks) and len(self.results) == len(self.tasks) and self.counts["PASS"] == len(self.tasks) and not (self.error_msg or self.was_stopped or self.save_error)

    def outcome(self):
        if self.error_msg:
            return f"异常终止：{self.error_msg}"
        if self.was_stopped:
            return "已停止，保留已完成数据"
        if self.save_error:
            return "报告保存失败"
        if self.all_passed:
            return "全部通过"
        return f"未全部通过：PASS {self.counts['PASS']}，FAIL {self.counts['FAIL']}，ERROR {self.counts['ERROR']}，SKIP {self.counts['SKIP']}"

    # ---- 控制接口 ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag = False
        self.error_msg = ""
        self.save_error = ""
        self.was_stopped = False
        self.results = []
        self._last_channel_key = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def run_blocking(self):
        """同步执行（CLI 使用）。"""
        self._run()

    def pause(self):
        self._pause_evt.set()

    def resume(self):
        self._pause_evt.clear()

    def stop(self):
        self._stop_flag = True
        self._pause_evt.clear()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- 主流程 ----
    def _run(self):
        try:
            if self.report:
                self.report.ws["B2"] = "执行中"
            total = len(self.tasks)
            for idx, task in enumerate(self.tasks):
                if self._stop_flag:
                    break
                while self._pause_evt.is_set() and not self._stop_flag:
                    time.sleep(0.2)
                if self._stop_flag:
                    break
                # Never ask an operator to move probes or loads with the DUT powered.
                self._shutdown()
                self._emit(self.on_task_start, task, idx, total)
                if not self._confirm_channel(task):
                    self._stop_flag = True
                    break
                try:
                    self._capture = None
                    self._archive_paths = {}
                    result = self._execute(task)
                except Exception as e:
                    result = {"status": "ERROR", "vmin": None, "vmax": None,
                              "ripple": None, "png": None, "note": str(e)}
                # Power down before saving/plotting or waiting for the next task.
                self._shutdown()
                result.update(self._archive_paths)
                if result.get("png") and self._scope():
                    import json
                    result["scope"] = dict(self._scope().last_waveform_info)
                    metadata_path = os.path.splitext(result["png"])[0] + ".json"
                    with open(metadata_path, encoding="utf-8") as meta:
                        details = json.load(meta)
                    details.update({"result": result, "task": task.__dict__})
                    with open(metadata_path, "w", encoding="utf-8") as meta:
                        json.dump(details, meta, ensure_ascii=False, indent=2)
                self.results.append((task, result))
                if self.report:
                    self.report.record(idx, result)
                try:
                    self._fill(task, result)
                    self._save()
                except Exception as e:
                    self.save_error = str(e)
                    self._emit(self.on_error, f"回填/保存 Excel 失败: {e}")
                self._emit(self.on_task_done, task, result, idx, total)
        except Exception as e:
            self.error_msg = str(e) or repr(e)
        finally:
            self._shutdown()
            self.was_stopped = self._stop_flag
            if self.report:
                self.report.finish(self.outcome())
            try:
                self._save()
            except Exception:
                pass
            self._emit(self.on_finished)

    def _emit(self, fn, *args):
        if fn:
            try:
                fn(*args)
            except Exception:
                pass

    def _confirm_channel(self, task: CaseTask):
        """多路输出切换被测通道前请求人工确认（单路直接跳过）。"""
        if self.spec.n <= 1:
            return True
        if not self.on_confirm:
            return False
        key = (task.sheet, task.channel)
        if key == self._last_channel_key:
            return True
        self._last_channel_key = key
        msg = (f"请将电子负载与示波器探头接至 第{task.channel + 1}路输出，\n"
               f"并按工况「{task.name}」接好其余各路负载。\n确认后继续。")
        try:
            return bool(self.on_confirm(msg))
        except Exception:
            return False

    # ---- 仪器操作 ----
    def _ps(self):
        return self.instruments.get("power_supply")

    def _load(self):
        return self.instruments.get("electronic_load")

    def _scope(self):
        return self.instruments.get("oscilloscope")

    def _require(self, *names):
        label = {"power_supply": "直流源", "electronic_load": "电子负载",
                 "oscilloscope": "示波器"}
        return [label[x] for x in names if not self.instruments.get(x)]

    def _set_source(self, vin: float, enable: bool = True):
        ps = self._ps()
        if not ps:
            return
        if not self.spec.vin_min <= vin <= self.spec.vin_max:
            raise ValueError(f"输入电压 {vin:g}V 超出工程边界")
        ps.enable_output(False)
        # OWON 本地模式会静默忽略设定命令，必须先进远程模式再设电压/限流
        try:
            ps.set_remote()
        except Exception:
            pass
        time.sleep(0.1)
        ps.set_voltage_limit(self.spec.vin_max * 1.1)
        ps.set_current_limit(self.iin_limit * 1.1)
        ps.set_voltage(vin)
        ps.set_current(self.iin_limit)
        actual = current = 0.0
        for _ in range(8):
            time.sleep(0.2)
            actual = ps.get_voltage()
            current = ps.get_current()
            if (abs(actual - vin) <= max(0.2, vin * 0.01)
                    and abs(current - self.iin_limit) <= max(0.1, self.iin_limit * 0.05)):
                break
            ps.set_voltage(vin)
            ps.set_current(self.iin_limit)
        if abs(actual - vin) > max(0.2, vin * 0.01):
            raise RuntimeError(f"直流源电压设定回读异常：目标 {vin:g}V，回读 {actual:g}V")
        if abs(current - self.iin_limit) > max(0.1, self.iin_limit * 0.05):
            raise RuntimeError(f"直流源限流设定回读异常：目标 {self.iin_limit:g}A，回读 {current:g}A")
        if not np.isfinite(actual) or not np.isfinite(current):
            raise RuntimeError("直流源设定回读不是有限数值")
        if enable:
            ps.enable_output(True)
            time.sleep(0.4)
            if ps.get_output_state() is not True:
                raise RuntimeError("直流源未能开启输出（请检查保护状态）")

    def _set_load_cr(self, channel: int, iout: float):
        """CR 模式拉载（电阻=Vout_typ/Iout）；iout≈0 用 2kΩ 近似空载。"""
        load = self._load()
        if not load:
            return
        o = self.spec.outputs[channel]
        r = o.vout_typ / iout if iout > 1e-9 else 2000.0
        if not load.set_mode("CR") or not load.set_resistance(r) or not load.enable_input(True):
            raise RuntimeError("电子负载 CR 模式/电阻/输入未能确认")

    def _shutdown(self):
        load, ps = self._load(), self._ps()
        if load:
            try:
                load.disable_input()
            except Exception:
                pass
        if ps:
            try:
                ps.enable_output(False)
            except Exception:
                pass

    # ---- 测量 ----
    def _measure_vout_range(self, samples: int = 5):
        """负载端电压多次采样，返回 (min, max)。"""
        load = self._load()
        if not load:
            return None, None
        vals = []
        for _ in range(samples):
            try:
                v = load.measure_voltage()
            except Exception:
                v = None
            if v is not None and np.isfinite(v):
                vals.append(v)
            time.sleep(0.15)
        if not vals:
            return None, None
        return round(float(min(vals)), 4), round(float(max(vals)), 4)

    def _read_waveform(self):
        scope = self._scope()
        if not scope:
            return None
        self._capture = scope.get_waveform_capture(channel=1)
        w = self._capture.waveforms["CH1"].y
        return w if w is not None and len(w) and np.all(np.isfinite(w)) else None

    def _scope_apply(self, config: dict) -> bool:
        """Apply coupling, scale and the matching explicit vertical offset."""
        scope = self._scope()
        if not scope:
            return False
        return scope.apply_config(config)

    @staticmethod
    def _wave_stats(w):
        if w is None or not len(w):
            return None, None
        return round(float(np.min(w)), 4), round(float(np.max(w)), 4)

    def _dc_scope_config(self, channel: int, timebase: float, trigger_mode: str = "EDGE",
                         trigger_level: float = None, acq_mode: str = "NORM",
                         bandwidth: str = "20M", full_swing: bool = False) -> dict:
        o = self.spec.outputs[channel]
        # Center dynamic signals at nominal voltage for useful ADC resolution;
        # startup captures need the complete 0-to-output swing.
        need = (o.vmax() * 1.1 / 8.0 if full_swing else
                max((o.vmax() - o.vmin()) * 2.0 / 8.0, o.vout_typ * 0.02))
        scale = min([s for s in _STD_SCALES if s >= need], default=50.0)
        lvl = trigger_level if trigger_level is not None else o.vout_typ * 0.5
        return {"channel": 1, "coupling": "DC", "voltage_scale": scale,
                "timebase": timebase, "trigger_source": "CH1", "trigger_level": lvl,
                "trigger_mode": trigger_mode, "acq_mode": acq_mode,
                "bandwidth": bandwidth, "offset": -o.vout_typ / 2 if full_swing else -o.vout_typ,
                "probe_ratio": 1.0}

    def _ripple_scope_config(self, channel: int) -> dict:
        """纹波测量配置：AC 耦合、20M 带宽、100us/div（模板要求）、峰值检测。"""
        o = self.spec.outputs[channel]
        scale = min([s for s in _STD_SCALES if s >= o.ripple() / 7.0], default=10.0)
        return {"channel": 1, "coupling": "AC", "voltage_scale": scale,
                "timebase": 1e-4, "acq_mode": "PEAK", "bandwidth": "20M",
                "trigger_mode": "AUTO", "offset": 0.0}

    def _archive_waveform(self, task: CaseTask, iout: float, w=None):
        """Archive the measured frozen frame; a failed archive is an execution error."""
        if not self.archiver:
            return None
        if w is None:
            w = self._read_waveform()
        if w is None or self._capture is None:
            raise RuntimeError("没有可归档的同帧波形")
        ch_name = self.spec.outputs[task.channel].name
        self._archive_paths = self.archiver.save_capture(
            self._capture, "black_box", task.test_item, task.vin, task.temp, iout, ch_name,
            context={"task": task.__dict__, "output_name": ch_name,
                     "criteria": {"vmin": task.limit_lo, "vmax": task.limit_hi, "ripple": task.ripple_limit}})
        return self._archive_paths["png"]

    # ---- 判定 ----
    def _judge(self, task: CaseTask, vmin, vmax, ripple) -> str:
        required = [vmin, vmax] + ([ripple] if task.kind == "ripple" else [])
        if any(v is None or not np.isfinite(v) for v in required):
            return "ERROR"
        ok = True
        # 启机关机：下电时电压自然归 0，min 不参与判定
        if vmin is not None and task.kind != "startup" and vmin < task.limit_lo:
            ok = False
        if vmax is not None and vmax > task.limit_hi:
            ok = False
        if task.kind == "ripple" and ripple is not None and ripple > task.ripple_limit:
            ok = False
        return "PASS" if ok else "FAIL"

    # ---- 各测试项 ----
    def _execute(self, task: CaseTask) -> dict:
        return {
            "ripple": self._run_ripple,
            "dynamic": self._run_dynamic,
            "stability": self._run_stability,
            "startup": self._run_startup,
        }[task.kind](task)

    def _wave_sanity(self, task: CaseTask, vmin, vmax) -> str:
        """波形合理性检查：负载端为正电压时，探头读出负值/远低于标称即为接线异常。"""
        if vmax is None:
            return "示波器取数失败"
        o = self.spec.outputs[task.channel]
        if vmax < 0.5 * o.vout_typ or vmin is not None and vmin < -0.5 * o.vout_typ:
            return "探头读数异常（请检查探头正负接线/衰减比设置）"
        return ""

    @staticmethod
    def _result(status, vmin=None, vmax=None, ripple=None, png=None, note=""):
        return {"status": status, "vmin": vmin, "vmax": vmax,
                "ripple": ripple, "png": png, "note": note,
                "csv": os.path.splitext(png)[0] + ".csv" if png else None}

    def _run_ripple(self, task: CaseTask) -> dict:
        missing = self._require("power_supply", "electronic_load", "oscilloscope")
        if missing:
            return self._result("SKIP", note="未连接" + "、".join(missing))
        scope = self._scope()
        self._set_source(self.spec.vin_typ)
        self._set_load_cr(task.channel, task.currents[task.channel])
        time.sleep(SETTLE_STEADY)
        vmin, vmax = self._measure_vout_range()
        ripple, note, w = None, "", None
        if scope:
            if not self._scope_apply(self._ripple_scope_config(task.channel)):
                raise RuntimeError("示波器纹波配置失败")
            scope.run()
            time.sleep(0.8)
            w = self._read_waveform()
            if w is not None:
                ripple = round(float(np.max(w) - np.min(w)), 4)
        else:
            note = "示波器未连接，无纹波数据"
        if w is None:
            note = "示波器取数失败，无纹波数据"
        png = self._archive_waveform(task, task.currents[task.channel], w) if w is not None else None
        status = self._judge(task, vmin, vmax, ripple)
        return self._result(status, vmin, vmax, ripple, png, note)

    def _run_dynamic(self, task: CaseTask) -> dict:
        missing = self._require("power_supply", "electronic_load", "oscilloscope")
        if missing:
            return self._result("SKIP", note="未连接" + "、".join(missing))
        load, scope = self._load(), self._scope()
        self._set_source(task.vin)
        # 模板要求：第一路 A/B 段 10ms，其后每路递增 1ms
        dwell = 10.0 + 1.0 * task.channel
        note = ""
        if not load.set_dynamic_params(task.i_hi, task.i_lo,
                                       dwell_high_ms=dwell, dwell_low_ms=dwell):
            raise RuntimeError("电子负载动态参数回读失败")
        if not load.start_dynamic():
            raise RuntimeError(f"电子负载动态输入开启失败：{load.last_input_trace}")
        self._scope_apply(self._dc_scope_config(task.channel, DYNAMIC_TIMEBASE))
        scope.run()
        time.sleep(SETTLE_STEADY)
        w = self._read_waveform()
        load.stop_dynamic()
        vmin, vmax = self._wave_stats(w)
        png = self._archive_waveform(task, task.i_hi, w)
        note = self._wave_sanity(task, vmin, vmax)
        if note:
            status = "ERROR"
        else:
            status = self._judge(task, vmin, vmax, None)
        return self._result(status, vmin, vmax, None, png, note)

    def _run_stability(self, task: CaseTask) -> dict:
        missing = self._require("power_supply", "electronic_load", "oscilloscope")
        if missing:
            return self._result("SKIP", note="未连接" + "、".join(missing))
        ps, load, scope = self._ps(), self._load(), self._scope()
        self._set_source(task.vin)
        note = ""
        # 负载轻↔满跳变（A/B 段各 500ms），与输入跳变同步进行
        if not load.set_dynamic_params(task.i_hi, task.i_lo,
                                       dwell_high_ms=500.0, dwell_low_ms=500.0):
            raise RuntimeError("电子负载动态参数回读失败")
        if not load.start_dynamic():
            raise RuntimeError(f"电子负载动态输入开启失败：{load.last_input_trace}")
        self._scope_apply(self._dc_scope_config(task.channel, STABILITY_TIMEBASE, full_swing=True))
        scope.run()
        time.sleep(0.3)
        for _ in range(2):
            ps.set_voltage(self.spec.vin_min)
            time.sleep(0.5)
            ps.set_voltage(self.spec.vin_max)
            time.sleep(0.5)
        ps.set_voltage(self.spec.vin_typ)
        time.sleep(0.3)
        w = self._read_waveform()
        load.stop_dynamic()
        vmin, vmax = self._wave_stats(w)
        png = self._archive_waveform(task, task.i_hi, w)
        note = self._wave_sanity(task, vmin, vmax)
        if note:
            status = "ERROR"
        else:
            status = self._judge(task, vmin, vmax, None)
        return self._result(status, vmin, vmax, None, png, note)

    def _run_startup(self, task: CaseTask) -> dict:
        missing = self._require("power_supply", "electronic_load", "oscilloscope")
        if missing:
            return self._result("SKIP", note="未连接" + "、".join(missing))
        ps, load, scope = self._ps(), self._load(), self._scope()
        o = self.spec.outputs[task.channel]
        self._set_load_cr(task.channel, task.currents[task.channel])
        rising = task.label == "轻载上电"
        if scope:
            self._scope_apply(self._dc_scope_config(task.channel, STARTUP_TIMEBASE, full_swing=True))
            try:
                scope.set_trigger_slope("RISING" if rising else "FALLING")
            except Exception:
                pass
        if rising:
            ps.enable_output(False)
            time.sleep(0.5)
            self._set_source(task.vin, enable=False)
            time.sleep(0.2)
            if scope:
                scope.single()
            time.sleep(0.3)
            ps.enable_output(True)
        else:
            self._set_source(task.vin)
            time.sleep(SETTLE_STEADY)
            if scope:
                scope.single()
            time.sleep(0.3)
            ps.enable_output(False)
        time.sleep(1.5)
        if not scope.wait_for_single():
            scope.run()
            return self._result("ERROR", note="示波器单次触发未完成，未捕获上/下电边沿")
        w = self._read_waveform()
        if scope:
            scope.run()
        vmin, vmax = self._wave_stats(w)
        png = self._archive_waveform(task, task.currents[task.channel], w)
        note = "" if w is not None else "示波器取数失败"
        # 波形有效性护栏：上电应冲到接近标称、下电前有稳态平台；
        # 峰值远低于标称说明探头无信号/DUT 未输出，不能据此外推 pass
        if vmax is None or vmax < 0.5 * o.vout_typ or vmin is None or vmin > 0.3 * o.vout_typ:
            status = "ERROR"
            note = (note + " " if note else "") + "未捕获到有效上/下电波形（需同时包含低电平和输出平台）"
        else:
            status = self._judge(task, vmin, vmax, None)
        return self._result(status, vmin, vmax, None, png, note)

    # ---- 回填与保存 ----
    def _fill(self, task: CaseTask, result: dict):
        layout = TestCaseLayout(self.spec.n)
        ws = self.wb[task.sheet]
        cols = getattr(layout, RESULT_COLS_ATTR[task.sheet])(task.channel)
        row = task.row
        if result.get("vmin") is not None:
            wr, wc = writable_cell(ws, row, cols[0])
            ws.cell(row=wr, column=wc, value=float(result["vmin"]))
        if result.get("vmax") is not None:
            wr, wc = writable_cell(ws, row, cols[1])
            ws.cell(row=wr, column=wc, value=float(result["vmax"]))
        if len(cols) >= 4 and result.get("ripple") is not None:
            wr, wc = writable_cell(ws, row, cols[2])
            ws.cell(row=wr, column=wc, value=float(result["ripple"]))
        img_col = cols[3] if len(cols) >= 4 else cols[2]
        png = result.get("png")
        if png and os.path.exists(png):
            try:
                img = XLImage(png)
                img.width = 240
                img.height = 120
                wr, wc = writable_cell(ws, row, img_col)
                ws.row_dimensions[wr].height = 48
                ws.row_dimensions[wr + 1].height = 48
                ws.add_image(img, f"{get_column_letter(wc)}{wr}")
            except Exception:
                pass
        note = result.get("note", "")
        if note and task.sheet == "纹波与稳压精度测试":
            wr, wc = writable_cell(ws, row, layout.ripple_remark_col())
            ws.cell(row=wr, column=wc, value=note)

    def _save(self):
        os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
        temp = self.output_path + ".tmp.xlsx"
        try:
            self.wb.save(temp)
            os.replace(temp, self.output_path)
            self.save_error = ""
        except Exception as exc:
            self.save_error = str(exc)
            self._emit(self.on_error, f"保存 Excel 失败: {exc}")
            raise
        finally:
            if os.path.isfile(temp):
                os.remove(temp)


# ============ 命令行兼容入口 ============

class TestCaseRunner:
    """生成用例 → 执行 → 回填（run_test_case.py 使用）。

    temp_filter: None=全部环温块；数值=只执行匹配块。
    """

    def __init__(self, spec: PowerSpec, instruments: dict, output_dir: str = None,
                 temp_filter: Optional[float] = 25.0,
                 test_case_filename: str = "黑盒测试用例.xlsx"):
        self.spec = spec
        self.instruments = instruments or {}
        self.output_dir = output_dir or os.path.join(os.getcwd(), "test_reports", "test_case_out")
        self.temp_filter = temp_filter
        self.test_case_filename = test_case_filename

    def run(self, sheets=("ripple", "dynamic", "stability", "startup")) -> str:
        if self.spec.n > 1:
            raise RuntimeError("多路输出需要人工换线确认，请在上位机 GUI 中执行测试")
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, self.test_case_filename)
        wb = TestCaseGenerator(self.spec).build_workbook()
        wb.save(path)
        tasks = build_tasks(self.spec, sheets, self.temp_filter)
        executor = CaseExecutor(self.spec, self.instruments, wb, tasks, path,
                                archiver_dir=self.output_dir)
        executor.run_blocking()
        return path
