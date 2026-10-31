from enum import Enum
from typing import Optional, Callable
import time
import threading
from .results_store import TestResult, ResultsStore


class TestStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class TestExecutor:
    def __init__(self, instruments: dict, results_store: ResultsStore):
        """
        instruments: {"power_supply": PowerSupply, "electronic_load": ElectronicLoad, "oscilloscope": Oscilloscope, "temp_chamber": TempChamber}
        """
        self.instruments = instruments
        self.results_store = results_store
        self.status = TestStatus.IDLE
        self.current_step_index = 0
        self._stop_flag = False
        self._pause_flag = False
        self.callbacks: dict = {}
        self._channel_configs: dict = {}  # channel_name -> OutputChannelConfig

        # 测试执行器
        self.black_box = None
        self.white_box = None
        self.archiver = None

    def set_channel_configs(self, configs: list):
        """设置通道配置，用于iout->resistance转换"""
        self._channel_configs = {c.channel_name: c for c in configs}

    def _calc_resistance(self, step) -> float:
        """根据iout和通道标称电压计算CR模式电阻值"""
        ch_cfg = self._channel_configs.get(step.channel)
        if ch_cfg:
            vnom = ch_cfg.nominal_voltage
        else:
            vnom = 12.0  # 默认
        if step.iout > 0:
            return vnom / step.iout
        return 100.0  # 短路保护用小电阻，由fault分支处理

    def set_test_handlers(self, black_box, white_box):
        self.black_box = black_box
        self.white_box = white_box
        if self.archiver:
            if black_box:
                black_box.set_archiver(self.archiver)
            if white_box:
                white_box.set_archiver(self.archiver)

    def set_archiver(self, archiver):
        """设置波形归档器"""
        self.archiver = archiver
        if self.black_box:
            self.black_box.set_archiver(archiver)
        if self.white_box:
            self.white_box.set_archiver(archiver)

    def set_callback(self, event: str, callback: Callable):
        self.callbacks[event] = callback

    def _emit(self, event: str, **kwargs):
        if event in self.callbacks:
            self.callbacks[event](**kwargs)

    def run(self, steps: list):
        """同步执行测试步骤（在后台线程中调用）"""
        self.status = TestStatus.RUNNING
        self._stop_flag = False

        ps = self.instruments.get("power_supply")
        load = self.instruments.get("electronic_load")
        scope = self.instruments.get("oscilloscope")
        chamber = self.instruments.get("temp_chamber")

        total = len(steps)

        # 输入限流：按满载功率与本次最低输入电压推导（效率按 0.8，留 25% 裕量）。
        # 仪器残留的小限流值会把 DUT 输入钳死，必须显式覆盖；本地模式下设定被忽略，先进远程。
        if ps:
            vins = [s.vin for s in steps if getattr(s, "vin", 0)]
            v_min = min(vins) if vins else 32.0
            p_total = 0.0
            for c in self._channel_configs.values():
                p_total += c.pout_max or (c.nominal_voltage * max(c.iout_rated, c.iout_max, c.nominal_current))
            if p_total <= 0:
                p_total = 72.0
            try:
                ps.set_remote()
                time.sleep(0.1)
                ps.set_current(round(max(1.0, p_total / (v_min * 0.8) * 1.25), 2))
            except Exception:
                pass

        for i, step in enumerate(steps):
            if self._stop_flag:
                self.status = TestStatus.STOPPED
                return

            while self._pause_flag:
                time.sleep(0.1)
                if self._stop_flag:
                    self.status = TestStatus.STOPPED
                    return

            self.current_step_index = i
            step.status = "running"
            self._emit("step_start", step=step, index=i, total=total)

            try:
                # 设置工况（先设电压/限流，再使能输出）
                if ps:
                    ps.set_voltage(step.vin)
                    time.sleep(0.1)
                    ps.enable_output(True)
                    time.sleep(0.5)

                if load:
                    if step.test_mode == "fault":
                        load.set_mode("CR")
                        load.set_resistance(0.1)  # 小电阻模拟短路
                    else:
                        # CR模式下，根据iout计算电阻值
                        load.set_mode("CR")
                        resistance = self._calc_resistance(step)
                        load.set_resistance(resistance)
                    load.enable_input(True)
                    time.sleep(0.5)

                if scope:
                    scope.run()

                # 温箱（预留）
                if chamber and step.temp != 25.0:
                    chamber.set_temperature(step.temp)
                    chamber.enable()

                # 稳定延时
                time.sleep(2.0)

                # 执行测试
                if step.test_type == "black_box" and self.black_box:
                    result = self.black_box.execute_step(step, self.instruments)
                elif step.test_type == "white_box" and self.white_box:
                    result = self.white_box.execute_step(step, self.instruments)
                else:
                    result = TestResult(
                        step_id=step.step_id,
                        test_item=step.test_item,
                        test_type=step.test_type,
                        status="PASS"
                    )

                step.status = result.status
                self.results_store.add_result(result)
                self._emit("step_complete", step=step, result=result, index=i, total=total)

            except Exception as e:
                result = TestResult(
                    step_id=step.step_id,
                    test_item=step.test_item,
                    test_type=step.test_type,
                    status="ERROR",
                    error_msg=str(e)
                )
                step.status = "ERROR"
                self.results_store.add_result(result)
                self._emit("step_error", step=step, error=str(e), index=i, total=total)

            # 工况间延时
            time.sleep(0.5)

        # 测试结束安全关断所有仪器输出，避免遗留上电/带载状态
        self._shutdown_instruments()

        self.status = TestStatus.COMPLETED
        self._emit("all_complete", total=total)

    def run_async(self, steps: list):
        """异步执行"""
        thread = threading.Thread(target=self.run, args=(steps,), daemon=True)
        thread.start()
        return thread

    def stop(self):
        self._stop_flag = True
        # 紧急关闭仪器输出
        self._shutdown_instruments()

    def _shutdown_instruments(self):
        """安全关断：关闭直流源输出、断开电子负载输入"""
        ps = self.instruments.get("power_supply")
        if ps:
            try:
                ps.disable_output()
            except Exception:
                pass
        load = self.instruments.get("electronic_load")
        if load:
            try:
                load.disable_input()
            except Exception:
                pass

    def pause(self):
        self._pause_flag = True
        self.status = TestStatus.PAUSED

    def resume(self):
        self._pause_flag = False
        self.status = TestStatus.RUNNING