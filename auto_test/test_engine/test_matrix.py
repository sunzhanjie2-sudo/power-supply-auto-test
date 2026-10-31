from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import itertools


@dataclass
class TestStep:
    step_id: int = 0
    test_type: str = ""  # "black_box" or "white_box"
    test_item: str = ""  # 测试项名称
    test_mode: str = ""  # "steady", "dynamic", "fault"
    vin: float = 0.0
    vin_from: float = 0.0  # 输入电压跳变起始值
    temp: float = 25.0
    iout: float = 0.0
    iout_from: float = 0.0  # 动态跳变起始值
    iout_configs: dict = field(default_factory=dict)  # 多路输出电流配置 {"CH1":0.1,"CH2":5.0}
    channel: str = "CH1"
    component_ref: str = ""  # 白盒器件位号
    criteria_key: str = ""  # 判据键名
    scope_config: str = ""  # 示波器配置摘要（显示用）
    scope_config_dict: dict = field(default_factory=dict)  # 结构化示波器配置（应用用）
    status: str = "pending"
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "test_type": self.test_type,
            "test_item": self.test_item,
            "test_mode": self.test_mode,
            "vin": self.vin,
            "vin_from": self.vin_from,
            "temp": self.temp,
            "iout": self.iout,
            "iout_from": self.iout_from,
            "iout_configs": self.iout_configs,
            "channel": self.channel,
            "component_ref": self.component_ref,
            "criteria_key": self.criteria_key,
            "scope_config": self.scope_config,
        }


class TestMatrix:
    """测试矩阵生成器，按工况边界生成全组合测试步骤列表"""

    # 白盒测试模式由 generate() 内部显式生成

    def __init__(self, config):
        self.config = config
        self.steps: list = []

    def generate(self) -> list:
        """生成全部测试步骤"""
        self.steps = []
        step_id = 0

        # 去重边界值（如 GUI 中 temp 三值全为 25 时，不应重复跑 3 次）
        def _dedupe(seq):
            seen, out = set(), []
            for v in seq:
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            return out

        vin_list = _dedupe(self.config.boundary.vin_list)
        temp_list = _dedupe(self.config.boundary.temp_list)
        vin_min = self.config.boundary.vin_min
        vin_max = self.config.boundary.vin_max

        # 收集黑盒测试项
        black_box_items = [
            item_cfg for item_cfg in self.config.test_items
            if item_cfg.test_type == "black_box" and item_cfg.enabled
        ]

        # ---- 黑盒测试：每通道独立分块 ----
        output_channels = self.config.output_channels
        if len(output_channels) == 1:
            # 单路：正常遍历
            ch_cfg = output_channels[0]
            ch = ch_cfg.channel_name
            iout_min = ch_cfg.iout_min
            iout_half = ch_cfg.iout_half
            iout_rated = ch_cfg.iout_rated
            iout_max = ch_cfg.iout_max
            iout_list = [iout_min, iout_half, iout_rated, iout_max]

            for temp in temp_list:
                for vin in vin_list:
                    # 稳态遍历
                    for iout in iout_list:
                        for item_cfg in black_box_items:
                            step_id += 1
                            iout_configs = {ch: iout}
                            step = TestStep(
                                step_id=step_id,
                                test_type="black_box",
                                test_item=item_cfg.name,
                                test_mode="steady",
                                vin=vin, temp=temp, iout=iout,
                                iout_configs=iout_configs,
                                channel=ch,
                                criteria_key=item_cfg.name,
                            )
                            self.steps.append(step)

                    # 动态响应（Iout_min↔Iout_max跳变）
                    step_id += 1
                    iout_configs = {ch: iout_max}
                    step = TestStep(
                        step_id=step_id,
                        test_type="black_box",
                        test_item="动态响应",
                        test_mode="dynamic",
                        vin=vin, temp=temp,
                        iout=iout_max,
                        iout_from=iout_min,
                        iout_configs=iout_configs,
                        channel=ch,
                        criteria_key="动态响应",
                    )
                    self.steps.append(step)

                # 动态稳定度（Vin_min↔Vin_max跳变）
                step_id += 1
                iout_configs = {ch: iout_max}
                step = TestStep(
                    step_id=step_id,
                    test_type="black_box",
                    test_item="动态稳定度",
                    test_mode="vin_dynamic",
                    vin=vin_max, vin_from=vin_min,
                    temp=temp,
                    iout=iout_max, iout_from=iout_min,
                    iout_configs=iout_configs,
                    channel=ch,
                    criteria_key="动态稳定度",
                )
                self.steps.append(step)

                for vin in vin_list:
                    # 短路保护测试
                    step_id += 1
                    iout_configs = {ch: 0}
                    step = TestStep(
                        step_id=step_id,
                        test_type="black_box",
                        test_item="短路保护与恢复",
                        test_mode="fault",
                        vin=vin, temp=temp, iout=0,
                        iout_configs=iout_configs,
                        channel=ch,
                        criteria_key="短路保护",
                    )
                    self.steps.append(step)

        else:
            # 多路输出：包含交叉调整率两种极端工况
            ch_names = [c.channel_name for c in output_channels]
            ch_iout_min = {c.channel_name: c.iout_min for c in output_channels}
            ch_iout_max = {c.channel_name: c.iout_max for c in output_channels}

            for temp in temp_list:
                for vin in vin_list:
                    # 工况1: 某路过载，其他路满载
                    for target_ch in ch_names:
                        iouts = {}
                        for cn in ch_names:
                            iouts[cn] = ch_iout_max[cn] if cn == target_ch else (ch_iout_max[cn] * 0.85)
                        for item_cfg in black_box_items:
                            step_id += 1
                            step = TestStep(
                                step_id=step_id,
                                test_type="black_box",
                                test_item=item_cfg.name,
                                test_mode="steady",
                                vin=vin, temp=temp,
                                iout=iouts[target_ch],
                                iout_configs=iouts,
                                channel=target_ch,
                                criteria_key=item_cfg.name,
                            )
                            self.steps.append(step)

                    # 工况2: 某路轻载，其他路过载
                    for target_ch in ch_names:
                        iouts = {}
                        for cn in ch_names:
                            iouts[cn] = ch_iout_min[cn] if cn == target_ch else ch_iout_max[cn]
                        for item_cfg in black_box_items:
                            step_id += 1
                            step = TestStep(
                                step_id=step_id,
                                test_type="black_box",
                                test_item=item_cfg.name,
                                test_mode="steady",
                                vin=vin, temp=temp,
                                iout=iouts[target_ch],
                                iout_configs=iouts,
                                channel=target_ch,
                                criteria_key=item_cfg.name,
                            )
                            self.steps.append(step)

                    # 每通道动态响应（Iout_min↔Iout_max跳变）
                    for target_ch in ch_names:
                        step_id += 1
                        iouts = {cn: ch_iout_max[cn] for cn in ch_names}
                        step = TestStep(
                            step_id=step_id,
                            test_type="black_box",
                            test_item="动态响应",
                            test_mode="dynamic",
                            vin=vin, temp=temp,
                            iout=ch_iout_max[target_ch],
                            iout_from=ch_iout_min[target_ch],
                            iout_configs=iouts,
                            channel=target_ch,
                            criteria_key="动态响应",
                        )
                        self.steps.append(step)

                # 每通道动态稳定度
                for target_ch in ch_names:
                    step_id += 1
                    iouts = {cn: ch_iout_max[cn] for cn in ch_names}
                    step = TestStep(
                        step_id=step_id,
                        test_type="black_box",
                        test_item="动态稳定度",
                        test_mode="vin_dynamic",
                        vin=vin_max, vin_from=vin_min,
                        temp=temp,
                        iout=ch_iout_max[target_ch],
                        iout_from=ch_iout_min[target_ch],
                        iout_configs=iouts,
                        channel=target_ch,
                        criteria_key="动态稳定度",
                    )
                    self.steps.append(step)

                for vin in vin_list:
                    # 每通道短路保护
                    for target_ch in ch_names:
                        step_id += 1
                        iouts = {cn: ch_iout_max[cn] for cn in ch_names}
                        iouts[target_ch] = 0
                        step = TestStep(
                            step_id=step_id,
                            test_type="black_box",
                            test_item="短路保护与恢复",
                            test_mode="fault",
                            vin=vin, temp=temp, iout=0,
                            iout_configs=iouts,
                            channel=target_ch,
                            criteria_key="短路保护",
                        )
                        self.steps.append(step)

            # 多路动态响应（所有通道同时跳变）
            for temp in temp_list:
                for vin in vin_list:
                    step_id += 1
                    iouts = {cn: ch_iout_max[cn] for cn in ch_names}
                    iouts_from = {cn: ch_iout_min[cn] for cn in ch_names}
                    step = TestStep(
                        step_id=step_id,
                        test_type="black_box",
                        test_item="多路动态响应",
                        test_mode="multi_dynamic",
                        vin=vin, temp=temp,
                        iout=iouts[ch_names[0]],
                        iout_from=iouts_from[ch_names[0]],
                        iout_configs=iouts,
                        criteria_key="动态响应",
                    )
                    self.steps.append(step)

        # ---- 白盒测试 ----
        if self.config.output_channels:
            first_ch = self.config.output_channels[0]
            ch = first_ch.channel_name
            iout_min = first_ch.iout_min
            iout_half = first_ch.iout_half
            iout_rated = first_ch.iout_rated
            iout_max = first_ch.iout_max
            iout_list = [iout_min, iout_half, iout_rated, iout_max]
        else:
            ch = "CH1"
            iout_min = self.config.boundary.iout_min
            iout_half = self.config.boundary.iout_half
            iout_rated = self.config.boundary.iout_rated
            iout_max = self.config.boundary.iout_max
            iout_list = [iout_min, iout_half, iout_rated, iout_max]

        for comp in self.config.components:
            ref = comp.ref_des
            name = comp.device_name

            for vin in vin_list:
                # 稳态应力
                for iout in iout_list:
                    step_id += 1
                    step = TestStep(
                        step_id=step_id,
                        test_type="white_box",
                        test_item=f"{name}_{ref}",
                        test_mode="steady",
                        vin=vin, temp=25.0, iout=iout,
                        channel=ch,
                        component_ref=ref,
                        criteria_key=f"{ref}_steady",
                    )
                    self.steps.append(step)

                # 动态应力（Iout_min↔Iout_max跳变）
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="dynamic",
                    vin=vin, temp=25.0,
                    iout=iout_max, iout_from=iout_min,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_dynamic",
                )
                self.steps.append(step)

            for vin in vin_list:
                # 过载短路（Iout_max时短路）
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="fault_overload",
                    vin=vin, temp=25.0, iout=iout_max,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_fault_overload",
                )
                self.steps.append(step)

                # 板载短路（Iout_min时短路）
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="fault_onboard",
                    vin=vin, temp=25.0, iout=iout_min,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_fault_onboard",
                )
                self.steps.append(step)

                # 短路启机（CR最小电阻，记录启机波形）
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="short_startup",
                    vin=vin, temp=25.0, iout=0,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_short_startup",
                )
                self.steps.append(step)

                # 上电波形
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="power_on",
                    vin=vin, temp=25.0, iout=iout_min,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_power_on",
                )
                self.steps.append(step)

                # 下电波形
                step_id += 1
                step = TestStep(
                    step_id=step_id,
                    test_type="white_box",
                    test_item=f"{name}_{ref}",
                    test_mode="power_off",
                    vin=vin, temp=25.0, iout=iout_min,
                    channel=ch,
                    component_ref=ref,
                    criteria_key=f"{ref}_power_off",
                )
                self.steps.append(step)

        # 为所有步骤自动生成示波器配置（结构化 dict + 显示字符串）
        for step in self.steps:
            cfg = self._compute_scope_config(step)
            step.scope_config_dict = cfg
            step.scope_config = self._format_scope_config(cfg)

        return self.steps

    def get_step_count(self) -> int:
        return len(self.steps)

    def get_progress(self, current_step: int) -> float:
        if not self.steps:
            return 0.0
        return (current_step / len(self.steps)) * 100

    # 标准示波器电压档位与时基（1-2-5 序列）
    STD_SCALES = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                  1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
    STD_TIMEBASES = [1e-9, 2e-9, 5e-9, 1e-8, 2e-8, 5e-8, 1e-7, 2e-7, 5e-7,
                     1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4,
                     1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0]

    @staticmethod
    def _round_scale(value: float) -> float:
        """向上取最近的标准电压档位"""
        if value <= 0:
            return 0.05
        for s in TestMatrix.STD_SCALES:
            if value <= s:
                return s
        return TestMatrix.STD_SCALES[-1]

    @staticmethod
    def _round_timebase(value: float) -> float:
        """向上取最近的标准时基"""
        if value <= 0:
            return 1e-5
        for t in TestMatrix.STD_TIMEBASES:
            if value <= t:
                return t
        return TestMatrix.STD_TIMEBASES[-1]

    def _compute_scope_config(self, step: TestStep) -> dict:
        """根据测试项/工况自动规划示波器配置（结构化），确保测量最准确。

        设计原则：
          - 电压档位：被测信号幅度约占屏幕 4 格（量程 = 幅度/4，向上取标准档）
          - 时基：稳态/纹波按开关频率（10 个周期占满 10 格）；动态/时序按事件周期
          - 纹波：AC 耦合 + 小档位 + 峰值采集 + 20MHz 带宽限制
          - 动态响应：AC 耦合去除直流，观察瞬态偏差
          - 开关机/短路：DC 耦合 + 单次/边沿触发，时基覆盖事件过程
        """
        item = step.test_item
        mode = step.test_mode
        boundary = self.config.boundary
        switch_period = 1.0 / boundary.switch_freq if boundary.switch_freq > 0 else 1e-5

        # 被测信号幅度：黑盒测 DUT 输出（标称电压），白盒按器件耐压
        nominal = 12.0
        for oc in self.config.output_channels:
            if oc.channel_name == step.channel:
                nominal = oc.nominal_voltage
                break
        amplitude = nominal
        probe = 1.0
        ch = 1
        if step.component_ref:
            for comp in self.config.components:
                if comp.ref_des == step.component_ref:
                    amplitude = comp.voltage_rating
                    probe = 10.0 if comp.voltage_rating > 50 else 1.0
                    ch = comp.scope_channel
                    break

        # 电压档位：幅度约占屏幕 6~7 格（留 1~2 格余量），向上取标准档
        v_scale = self._round_scale(amplitude / 7.0)
        tb = self._round_timebase(switch_period)

        cfg = {
            "channel": ch,
            "coupling": "DC",
            "voltage_scale": v_scale,
            "timebase": tb,
            "trigger_source": f"CH{ch}",
            "trigger_level": nominal * 0.5,
            "trigger_mode": "EDGE",
            "acq_mode": "NORM",
            "bandwidth": "FULL",
            "probe_ratio": probe,
        }

        if item == "输出纹波与噪声":
            cfg.update(coupling="AC", voltage_scale=0.05, timebase=1e-6,
                       acq_mode="PEAK", bandwidth="20M", trigger_mode="AUTO",
                       trigger_level=0.0)
        elif item == "动态响应":
            cfg.update(coupling="AC", voltage_scale=0.2, timebase=500e-6,
                       trigger_mode="EDGE", acq_mode="NORM", bandwidth="FULL",
                       trigger_level=0.0)
        elif item == "动态稳定度":
            cfg.update(coupling="DC", voltage_scale=v_scale, timebase=20e-3,
                       trigger_mode="EDGE", acq_mode="NORM", bandwidth="FULL")
        elif item == "开关机时序":
            cfg.update(coupling="DC", voltage_scale=v_scale, timebase=20e-3,
                       trigger_mode="SINGLE", acq_mode="NORM", bandwidth="FULL")
        elif item == "短路保护与恢复":
            cfg.update(coupling="DC", voltage_scale=v_scale, timebase=2e-3,
                       trigger_mode="EDGE", acq_mode="NORM", bandwidth="FULL")
        elif mode in ("power_on", "power_off", "short_startup"):
            cfg.update(coupling="DC", voltage_scale=v_scale, timebase=20e-3,
                       trigger_mode="SINGLE", acq_mode="NORM", bandwidth="FULL")
        elif mode in ("fault_overload", "fault_onboard"):
            cfg.update(coupling="DC", voltage_scale=v_scale, timebase=1e-3,
                       trigger_mode="EDGE", acq_mode="NORM", bandwidth="FULL")
        elif mode == "dynamic":
            cfg.update(coupling="AC", voltage_scale=0.2, timebase=500e-6,
                       trigger_mode="EDGE", acq_mode="NORM", bandwidth="FULL",
                       trigger_level=0.0)
        elif step.component_ref:
            # 白盒稳态应力：按器件自身配置
            for comp in self.config.components:
                if comp.ref_des == step.component_ref:
                    cfg.update(coupling="DC", voltage_scale=comp.voltage_scale,
                               timebase=comp.timebase_scale,
                               trigger_source=comp.trigger_source,
                               trigger_level=comp.trigger_level,
                               bandwidth=comp.bandwidth, channel=comp.scope_channel)
                    break

        return cfg

    @staticmethod
    def _format_scope_config(cfg: dict) -> str:
        """将结构化示波器配置格式化为摘要字符串"""
        probe = f"{cfg.get('probe_ratio', 1.0):g}X"
        coup = cfg.get("coupling", "DC")
        vs = cfg.get("voltage_scale", 1.0)
        vs_str = f"{vs * 1000:.0f}mV/div" if vs < 1 else f"{vs:g}V/div"
        tb = cfg.get("timebase", 1e-5)
        tb_str = f"{tb * 1e3:.0f}ms/div" if tb >= 1e-3 else f"{tb * 1e6:.0f}us/div"
        trig = cfg.get("trigger_mode", "EDGE")
        bw = cfg.get("bandwidth", "FULL")
        acq = cfg.get("acq_mode", "NORM")
        return f"{probe} {coup} {vs_str} {tb_str} {trig} {bw} {acq}"