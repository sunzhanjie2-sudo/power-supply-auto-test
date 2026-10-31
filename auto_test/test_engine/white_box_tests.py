import time
import numpy as np
from .results_store import TestResult


class WhiteBoxTests:
    """白盒器件应力测试执行

    软起动（soft-start）判据说明（COMP 引脚）：
      软起动约 4.7ms 期间，COMP 引脚电压「并非固定」在 1.5V~3.5V，
      而是其「上限」被钳位在 1.5V~3.5V（即 COMP 斜坡上升，峰值被限制在该区间）。
      测量时应判「峰值/上限 ≤ 钳位上限（1.5~3.5V）」而非「稳态处于该区间」。
    """

    def __init__(self, config):
        self.config = config
        self.archiver = None

    def set_archiver(self, archiver):
        """设置波形归档器"""
        self.archiver = archiver

    def _iout_to_resistance(self, iout: float, channel: str = "CH1") -> float:
        """将电流值转换为CR模式电阻值"""
        if iout <= 0:
            return 100.0
        vnom = 12.0
        for ch_cfg in self.config.output_channels:
            if ch_cfg.channel_name == channel:
                vnom = ch_cfg.nominal_voltage
                break
        return vnom / iout

    def _save_waveform(self, result: TestResult, waveform):
        """保存波形文件"""
        if self.archiver and waveform is not None and len(waveform) > 0:
            data = result.data
            vin = data.get("vin", 0)
            temp = data.get("temp", 25)
            iout = data.get("iout", 0)
            channel = data.get("channel", "CH1")

            csv_path = self.archiver.save_waveform_csv(
                waveform, "white_box", result.test_item,
                vin, temp, iout, channel, result.component_ref
            )
            if csv_path:
                result.waveform_csv_path = csv_path

    def execute_step(self, step, instruments: dict) -> TestResult:
        """执行单个白盒测试步骤"""
        scope = instruments.get("oscilloscope")
        load = instruments.get("electronic_load")
        ps = instruments.get("power_supply")

        data = {
            "vin": step.vin,
            "iout": step.iout,
            "component": step.component_ref,
            "test_mode": step.test_mode,
        }

        # 查找器件配置
        component = None
        for c in self.config.components:
            if c.ref_des == step.component_ref:
                component = c
                break

        # 自动配置示波器
        if scope and component:
            scope.auto_configure_for_component(component)
            time.sleep(0.5)

        # 根据测试模式执行
        mode = step.test_mode
        if mode == "fault_overload" or mode == "fault_onboard":
            self._execute_fault(step, instruments, data)
        elif mode == "short_startup":
            self._execute_short_startup(step, instruments, data)
        elif mode == "power_on":
            self._execute_power_on(step, instruments, data)
        elif mode == "power_off":
            self._execute_power_off(step, instruments, data)
        elif mode == "dynamic":
            self._execute_dynamic_stress(step, instruments, data)
        else:
            self._execute_steady_stress(step, instruments, data)

        # 采集波形
        waveform = None
        if scope and component:
            ch = component.scope_channel
            waveform = scope.get_waveform_data(channel=ch)
            if waveform is not None and len(waveform) > 0:
                data["v_peak"] = float(np.max(waveform))
                data["v_min"] = float(np.min(waveform))
                data["v_avg"] = float(np.mean(waveform))
                data["v_rms"] = float(np.sqrt(np.mean(np.square(waveform))))
                data["waveform_points"] = len(waveform)

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            test_type="white_box",
            component_ref=step.component_ref,
            data=data,
        )

        # 应力判据
        if "v_peak" in data and component:
            # 使用器件耐压作为参考
            voltage_rating = component.voltage_rating if component.voltage_rating > 0 else (step.vin * 1.5)
            stress_ratio = data["v_peak"] / voltage_rating
            data["stress_ratio"] = stress_ratio
            data["voltage_rating"] = voltage_rating

            # 优先使用配置的判据
            if component.stress_criteria:
                max_stress_ratio = component.stress_criteria.get("max_stress_ratio", 1.2)
                result.deviation = stress_ratio
                result.status = "PASS" if stress_ratio < max_stress_ratio else "FAIL"
            else:
                result.deviation = stress_ratio
                result.status = "PASS" if stress_ratio < 1.2 else "FAIL"

        # 保存波形
        self._save_waveform(result, waveform)

        return result

    def _execute_steady_stress(self, step, instruments, data):
        """稳态应力采集"""
        time.sleep(1.0)

    def _execute_dynamic_stress(self, step, instruments, data):
        """动态应力采集"""
        load = instruments.get("electronic_load")
        if load:
            i_min = self._iout_to_resistance(self.config.boundary.iout_max, step.channel)
            i_max = self._iout_to_resistance(self.config.boundary.iout_min, step.channel)
            load.set_dynamic_params(i_min, i_max, period=0.01, duty_cycle=0.5)
            load.start_dynamic()
            time.sleep(1.0)
            load.stop_dynamic()

    def _execute_fault(self, step, instruments, data):
        """故障应力采集（过载短路/板载短路）"""
        load = instruments.get("electronic_load")
        if load:
            load.set_mode("CR")
            load.set_resistance(0.05)
            load.enable_input(True)
            time.sleep(0.5)
            load.disable_input()
            data["fault_triggered"] = True

    def _execute_short_startup(self, step, instruments, data):
        """短路启机：CR最小电阻，记录尝试启机波形"""
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        if load:
            load.set_mode("CR")
            load.set_resistance(0.05)
            load.enable_input(True)
        if ps:
            ps.enable_output(True)
        time.sleep(1.0)
        if ps:
            ps.enable_output(False)
        if load:
            load.disable_input()
        data["short_startup"] = True

    def _execute_power_on(self, step, instruments, data):
        """上电波形：输出从关闭到启动"""
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        if load:
            load.set_mode("CR")
            resistance = self._iout_to_resistance(step.iout, step.channel)
            load.set_resistance(resistance)
            load.enable_input(True)
        if ps:
            ps.enable_output(False)
            time.sleep(0.5)
            ps.enable_output(True)
            time.sleep(1.0)
        data["power_on"] = True

    def _execute_power_off(self, step, instruments, data):
        """下电波形：输出从启动到关闭"""
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        if load:
            load.set_mode("CR")
            resistance = self._iout_to_resistance(step.iout, step.channel)
            load.set_resistance(resistance)
            load.enable_input(True)
        if ps:
            ps.enable_output(True)
            time.sleep(1.0)
            ps.enable_output(False)
        if load:
            load.disable_input()
        data["power_off"] = True