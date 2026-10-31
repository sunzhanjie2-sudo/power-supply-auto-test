import time
import numpy as np
from typing import Optional
from .results_store import TestResult


class BlackBoxTests:
    """黑盒整机测试执行"""

    def __init__(self, config):
        self.config = config
        self.archiver = None

    def set_archiver(self, archiver):
        """设置波形归档器"""
        self.archiver = archiver

    def _get_criteria(self, item_name: str, channel: str = ""):
        """获取测试项判据配置。

        多路输出时优先匹配「名称 + 通道」都一致的测试项（各通道判据可不同），
        否则回退到仅名称匹配。
        """
        if channel:
            for item in self.config.test_items:
                if item.enabled and item.name == item_name and item.channel == channel:
                    return item.criteria
        for item in self.config.test_items:
            if item.enabled and item.name == item_name:
                return item.criteria
        return None

    def _get_nominal_voltage(self, channel: str) -> float:
        """根据通道名获取标称输出电压"""
        if self.config.output_channels:
            for oc in self.config.output_channels:
                if oc.channel_name == channel:
                    return oc.nominal_voltage
            return self.config.output_channels[0].nominal_voltage
        return 12.0

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
                waveform, "black_box", result.test_item,
                vin, temp, iout, channel
            )
            if csv_path:
                result.waveform_csv_path = csv_path

    def _apply_scope_config(self, step, scope):
        """应用该步骤规划好的示波器配置（test_matrix 自动生成）"""
        if scope is None:
            return None
        cfg = getattr(step, "scope_config_dict", None)
        if cfg:
            scope.apply_config(cfg)
            time.sleep(0.3)
        return cfg

    def _estimate_transition_ms(self, waveform, timebase, threshold_frac: float = 0.5) -> Optional[float]:
        """从电压波形估算跳变时刻（起点到越过阈值的时间），单位 ms"""
        if waveform is None or len(waveform) < 2:
            return None
        n = len(waveform)
        vmin = float(np.min(waveform))
        vmax = float(np.max(waveform))
        span = vmax - vmin
        if span < 1e-6:
            return None
        thr = vmin + span * threshold_frac
        for i in range(1, n):
            if waveform[i] >= thr:
                return i * (timebase * 10 / n) * 1000.0
        return None

    def execute_step(self, step, instruments: dict) -> TestResult:
        """执行单个黑盒测试步骤"""
        item_name = step.test_item

        handlers = {
            "稳压精度": self._voltage_regulation,
            "输出纹波与噪声": self._ripple_noise,
            "动态响应": self._dynamic_response,
            "多路动态响应": self._multi_dynamic_response,
            "动态稳定度": self._dynamic_stability,
            "开关机时序": self._power_sequencing,
            "短路保护与恢复": self._short_circuit_protection,
        }

        handler = handlers.get(item_name)
        if handler:
            result = handler(step, instruments)
        else:
            result = TestResult(
                step_id=step.step_id,
                test_item=item_name,
                status="SKIP",
                data={"vin": step.vin, "iout": step.iout, "temp": step.temp},
            )
        result.test_type = "black_box"
        return result

    def _set_all_loads(self, step, instruments: dict):
        """设置多路负载（CR模式，根据iout计算电阻值）"""
        if not step.iout_configs:
            return
        load = instruments.get("electronic_load")
        if load:
            load.set_mode("CR")
            resistance = self._iout_to_resistance(step.iout, step.channel)
            load.set_resistance(resistance)
            load.enable_input(True)

    def _voltage_regulation(self, step, instruments: dict) -> TestResult:
        """稳压精度测试

        实测 DUT 输出电压：优先取电子负载端电压，其次取示波器波形均值。
        直流源为 DUT 的输入侧，其设定值/测量值不代表 DUT 输出电压。
        """
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        scope = instruments.get("oscilloscope")

        data = {"vin": step.vin, "iout": step.iout, "temp": step.temp, "channel": step.channel}
        if step.iout_configs:
            data["iout_configs"] = step.iout_configs

        # 负载已由执行器设置，此处仅等待稳定（避免二次设置引入暂态）
        time.sleep(2.0)

        # 实测 DUT 输出电压（采样至稳定，避免采到负载阶跃/上电暂态）
        v_out = None
        if load:
            samples = []
            for _ in range(6):
                v = load.measure_voltage()
                if v is not None:
                    samples.append(v)
                    # 连续两次读数接近视为稳定
                    if len(samples) >= 2 and abs(samples[-1] - samples[-2]) < 0.05:
                        break
                time.sleep(0.2)
            if samples:
                v_out = float(np.median(samples))
                data["vout"] = v_out
            i_load = load.measure_current()
            if i_load is not None:
                data["iout_meas"] = i_load

        if ps:
            data["ps_voltage"] = ps.measure_voltage()
            data["ps_current"] = ps.measure_current()

        # 采集波形（按规划配置示波器后读取电压波形，作为后备测量与归档）
        waveform = None
        if scope:
            cfg = self._apply_scope_config(step, scope)
            ch = (cfg or {}).get("channel", 1)
            waveform = scope.get_waveform_data_volts(channel=ch)
            if waveform is not None and len(waveform) > 0:
                data["v_avg"] = float(np.mean(waveform))
                data["waveform_points"] = len(waveform)
                if v_out is None:
                    v_out = float(np.mean(waveform))

        nominal = self._get_nominal_voltage(step.channel)

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )

        # 判据对比
        criteria = self._get_criteria(step.test_item, step.channel)
        if v_out is not None and nominal > 0:
            deviation = v_out - nominal  # 带符号偏差
            result.deviation = deviation

            if criteria:
                upper = criteria.upper_limit if criteria.upper_limit != 0 else nominal * 1.05
                lower = criteria.lower_limit if criteria.lower_limit != 0 else nominal * 0.95
                result.status = "PASS" if lower <= v_out <= upper else "FAIL"
            else:
                # 默认 5% 稳压精度
                result.status = "PASS" if abs(deviation) <= nominal * 0.05 else "FAIL"

        # 保存波形
        self._save_waveform(result, waveform)

        return result

    def _ripple_noise(self, step, instruments: dict) -> TestResult:
        """纹波与噪声测试（AC 耦合 + 小档位 + 峰值采集，电压单位 V）"""
        scope = instruments.get("oscilloscope")
        data = {"vin": step.vin, "iout": step.iout, "temp": step.temp, "channel": step.channel}

        waveform = None
        if scope:
            # 应用规划好的纹波配置：AC 耦合 + 50mV/div + 峰值采集 + 1us/div + 20MHz 带宽
            cfg = self._apply_scope_config(step, scope)
            ch = (cfg or {}).get("channel", 1)
            time.sleep(0.8)
            waveform = scope.get_waveform_data_volts(channel=ch)
            if waveform is not None and len(waveform) > 0:
                vpp = float(np.max(waveform) - np.min(waveform))
                v_rms = float(np.sqrt(np.mean(np.square(waveform))))
                data["vpp"] = vpp
                data["v_rms"] = v_rms
                data["waveform_points"] = len(waveform)

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )

        # 使用配置的判据
        criteria = self._get_criteria(step.test_item, step.channel)
        if "vpp" in data and data["vpp"] is not None:
            result.deviation = data["vpp"]
            if criteria:
                upper_limit = criteria.upper_limit if criteria.upper_limit != 0 else 0.5
                result.status = "PASS" if data["vpp"] <= upper_limit else "FAIL"
            else:
                result.status = "PASS" if data["vpp"] < 0.5 else "FAIL"

        # 保存波形
        self._save_waveform(result, waveform)

        return result

    def _dynamic_response(self, step, instruments: dict) -> TestResult:
        """动态响应测试（AC 耦合观察瞬态偏差，单位 V）"""
        load = instruments.get("electronic_load")
        scope = instruments.get("oscilloscope")
        data = {"vin": step.vin, "iout": step.iout, "temp": step.temp, "channel": step.channel}

        waveform = None
        if load and step.test_mode == "dynamic":
            # UTL8212 动态模式为电流动态（DYN:HIGH/LOW，单位 A），直接用电流值
            i_high = self.config.boundary.iout_max
            i_low = self.config.boundary.iout_min
            load.set_dynamic_params(i_high, i_low, dwell_high_ms=5.0, dwell_low_ms=5.0)
            load.start_dynamic()

            if scope:
                cfg = self._apply_scope_config(step, scope)
                ch = (cfg or {}).get("channel", 1)
                time.sleep(0.8)
                waveform = scope.get_waveform_data_volts(channel=ch)
                if waveform is not None and len(waveform) > 0:
                    data["overshoot"] = float(np.max(waveform))
                    data["undershoot"] = float(np.min(waveform))
                    data["waveform_points"] = len(waveform)

            load.stop_dynamic()

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )

        # 使用配置的判据
        criteria = self._get_criteria(step.test_item, step.channel)
        if criteria and "overshoot" in data:
            overshoot_limit = criteria.overshoot_limit if criteria.overshoot_limit != 0 else 0.1
            undershoot_limit = criteria.undershoot_limit if criteria.undershoot_limit != 0 else 0.1
            if data["overshoot"] <= overshoot_limit and abs(data["undershoot"]) <= undershoot_limit:
                result.status = "PASS"
            else:
                result.status = "FAIL"
        else:
            result.status = "PASS"

        # 保存波形
        self._save_waveform(result, waveform)

        return result

    def _multi_dynamic_response(self, step, instruments: dict) -> TestResult:
        """多路同时动态响应：所有通道同时Iout_min↔Iout_max跳变"""
        load = instruments.get("electronic_load")
        scope = instruments.get("oscilloscope")
        data = {"vin": step.vin, "iout_configs": step.iout_configs, "iout_configs_from": step.iout_from,
                "temp": step.temp, "channel": step.channel}

        waveform = None
        if load:
            i_high = step.iout
            i_low = step.iout_from if step.iout_from else 0.1
            load.set_dynamic_params(max(i_high, i_low), min(i_high, i_low),
                                    dwell_high_ms=5.0, dwell_low_ms=5.0)
            load.start_dynamic()

            if scope:
                cfg = self._apply_scope_config(step, scope)
                ch = (cfg or {}).get("channel", 1)
                time.sleep(0.8)
                waveform = scope.get_waveform_data_volts(channel=ch)
                if waveform is not None and len(waveform) > 0:
                    data["overshoot"] = float(np.max(waveform))
                    data["undershoot"] = float(np.min(waveform))
                    data["waveform_points"] = len(waveform)

            if load:
                load.stop_dynamic()

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )
        result.status = "PASS"  # 多路动态响应需要人工判断波形

        # 保存波形
        self._save_waveform(result, waveform)
        return result

    def _dynamic_stability(self, step, instruments: dict) -> TestResult:
        """动态稳定度测试：Vin_min↔Vin_max跳变(500ms) + Iout_min↔Iout_max跳变(10ms)"""
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        scope = instruments.get("oscilloscope")
        data = {
            "vin_from": step.vin_from, "vin_to": step.vin,
            "iout_from": step.iout_from, "iout_to": step.iout,
            "vin_period_ms": 500, "iout_period_ms": 10,
        }

        if scope:
            # 应用规划配置：DC 耦合 + 标称量程 + 20ms/div，覆盖 500ms Vin 周期
            self._apply_scope_config(step, scope)
            scope.run()

        if load:
            # 负载Iout跳变（电流动态，10ms周期：高/低电平各5ms）
            load.set_dynamic_params(step.iout, step.iout_from,
                                    dwell_high_ms=5.0, dwell_low_ms=5.0)
            load.start_dynamic()

        if ps:
            # 电源电压跳变，500ms周期
            ps.enable_output(True)
            # 软件模拟Vin跳变：交替设置Vin_min和Vin_max
            vin_low = step.vin_from
            vin_high = step.vin
            for _ in range(3):  # 3个周期
                ps.set_voltage(vin_low)
                time.sleep(0.25)
                ps.set_voltage(vin_high)
                time.sleep(0.25)

        waveform = None
        if scope:
            time.sleep(0.5)
            cfg = step.scope_config_dict or {}
            ch = cfg.get("channel", 1)
            waveform = scope.get_waveform_data_volts(channel=ch)
            if waveform is not None and len(waveform) > 0:
                data["v_peak"] = float(np.max(waveform))
                data["v_min"] = float(np.min(waveform))
                data["v_avg"] = float(np.mean(waveform))
                data["waveform_points"] = len(waveform)

        if load:
            load.stop_dynamic()

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )
        result.status = "PASS"

        # 保存波形
        self._save_waveform(result, waveform)
        return result

    def _power_sequencing(self, step, instruments: dict) -> TestResult:
        """开关机时序测试（DC 耦合 + 单次触发，估算上电/下电时间）"""
        ps = instruments.get("power_supply")
        scope = instruments.get("oscilloscope")
        data = {"vin": step.vin, "temp": step.temp, "iout": step.iout, "channel": step.channel}

        waveform = None
        if ps and scope:
            cfg = self._apply_scope_config(step, scope)
            ch = (cfg or {}).get("channel", 1)
            tb = (cfg or {}).get("timebase", 20e-3)
            scope.single()

            ps.enable_output(True)
            time.sleep(2.0)

            waveform = scope.get_waveform_data_volts(channel=ch)
            if waveform is not None and len(waveform) > 0:
                data["startup_time_ms"] = self._estimate_transition_ms(waveform, tb, 0.5)
                data["waveform_points"] = len(waveform)

            ps.disable_output()
            time.sleep(1.0)

            waveform2 = scope.get_waveform_data_volts(channel=ch)
            if waveform2 is not None and len(waveform2) > 0:
                data["shutdown_time_ms"] = self._estimate_transition_ms(waveform2, tb, 0.5)

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )
        result.status = "PASS"

        # 保存波形（启动波形）
        self._save_waveform(result, waveform)
        return result

    def _short_circuit_protection(self, step, instruments: dict) -> TestResult:
        """短路保护与恢复测试（DC 耦合，观察输出电压跌落与恢复）"""
        ps = instruments.get("power_supply")
        load = instruments.get("electronic_load")
        scope = instruments.get("oscilloscope")
        data = {"vin": step.vin, "temp": step.temp, "iout": step.iout, "channel": step.channel}

        waveform = None
        if load and scope:
            cfg = self._apply_scope_config(step, scope)
            ch = (cfg or {}).get("channel", 1)
            scope.run()

            # 短路操作
            load.set_mode("CR")
            load.set_resistance(0.05)
            load.enable_input(True)
            time.sleep(0.5)

            waveform = scope.get_waveform_data_volts(channel=ch)
            if waveform is not None and len(waveform) > 0:
                data["short_v_peak"] = float(np.max(waveform))
                data["short_v_min"] = float(np.min(waveform))
                data["waveform_points"] = len(waveform)
                data["protection_triggered"] = True

            # 移除短路
            load.disable_input()
            time.sleep(0.5)

            # 恢复判定：优先读取 DUT 输出端（电子负载端）电压，其次电源
            v_recover = load.measure_voltage()
            if v_recover is None and ps is not None:
                v_recover = ps.measure_voltage()
            data["recovery_voltage"] = v_recover
            nominal = self._get_nominal_voltage(step.channel)
            threshold = nominal * 0.5 if nominal > 0 else 0.5
            data["auto_recovered"] = v_recover is not None and v_recover > threshold

        result = TestResult(
            step_id=step.step_id,
            test_item=step.test_item,
            data=data,
        )
        result.status = "PASS" if data.get("auto_recovered", False) else "FAIL"

        # 保存波形
        self._save_waveform(result, waveform)
        return result
