from typing import List, Dict, Optional
from .timing_engine import TimingSequence, TimingStep


class PowerSupplyParams:
    def __init__(self, vin_min: float, vin_typ: float, vin_max: float, 
                 iout_board: float, iout_full: float, iout_overload: float):
        self.vin_min = vin_min
        self.vin_typ = vin_typ
        self.vin_max = vin_max
        self.iout_board = iout_board
        self.iout_full = iout_full
        self.iout_overload = iout_overload


class TestGenerator:
    def __init__(self, power_params: PowerSupplyParams):
        self.params = power_params

    def generate_regulation_test(self) -> TimingSequence:
        sequence = TimingSequence(name="稳压精度测试")

        step_id = 1
        for vin in [self.params.vin_min, self.params.vin_typ, self.params.vin_max]:
            for iout_name, iout_value in [
                ("板载", self.params.iout_board),
                ("满载", self.params.iout_full),
                ("过载", self.params.iout_overload)
            ]:
                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="set_voltage",
                    parameters={"voltage": vin},
                    delay=0.5,
                    description=f"设置输入电压 {vin}V"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="set_current",
                    parameters={"current": iout_value},
                    delay=0.5,
                    description=f"设置负载电流 {iout_value}A ({iout_name})"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="enable_output",
                    parameters={"enable": True},
                    delay=1.0,
                    description="开启电源输出"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": True},
                    delay=2.0,
                    description="开启负载输入"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="oscilloscope",
                    command="save_waveform",
                    parameters={"filename": f"regulation_{vin}V_{iout_name}", "channel": 1},
                    delay=0.5,
                    description=f"保存波形: {vin}V_{iout_name}"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": False},
                    delay=0.5,
                    description="关闭负载输入"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="enable_output",
                    parameters={"enable": False},
                    delay=0.5,
                    description="关闭电源输出"
                ))
                step_id += 1

        return sequence

    def generate_power_cycle_test(self) -> TimingSequence:
        sequence = TimingSequence(name="上下电测试")

        step_id = 1
        for vin in [self.params.vin_min, self.params.vin_typ, self.params.vin_max]:
            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="set_voltage",
                parameters={"voltage": vin},
                delay=0.5,
                description=f"设置输入电压 {vin}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="set_current",
                parameters={"current": self.params.iout_board},
                delay=0.5,
                description="设置板载负载"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": True},
                delay=2.0,
                description="上电 - 开启电源输出"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="enable_input",
                parameters={"enable": True},
                delay=3.0,
                description="上电 - 开启负载"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="oscilloscope",
                command="save_waveform",
                parameters={"filename": f"poweron_{vin}V", "channel": 1},
                delay=0.5,
                description=f"保存上电波形: {vin}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="enable_input",
                parameters={"enable": False},
                delay=0.5,
                description="下电 - 关闭负载"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": False},
                delay=0.5,
                description="下电 - 关闭电源输出"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="oscilloscope",
                command="save_waveform",
                parameters={"filename": f"poweroff_{vin}V", "channel": 1},
                delay=0.5,
                description=f"保存下电波形: {vin}V"
            ))
            step_id += 1

        return sequence

    def generate_ripple_test(self) -> TimingSequence:
        sequence = TimingSequence(name="纹波测试")

        step_id = 1
        for vin in [self.params.vin_min, self.params.vin_typ, self.params.vin_max]:
            for iout_name, iout_value in [
                ("板载", self.params.iout_board),
                ("满载", self.params.iout_full),
                ("过载", self.params.iout_overload)
            ]:
                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="set_voltage",
                    parameters={"voltage": vin},
                    delay=0.5,
                    description=f"设置输入电压 {vin}V"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="set_current",
                    parameters={"current": iout_value},
                    delay=0.5,
                    description=f"设置负载电流 {iout_value}A ({iout_name})"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="oscilloscope",
                    command="set_acquisition_mode",
                    parameters={"mode": "PEAK"},
                    delay=0.5,
                    description="设置示波器峰值检测模式"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="enable_output",
                    parameters={"enable": True},
                    delay=1.0,
                    description="开启电源输出"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": True},
                    delay=2.0,
                    description="开启负载输入"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="oscilloscope",
                    command="save_waveform",
                    parameters={"filename": f"ripple_{vin}V_{iout_name}", "channel": 1},
                    delay=0.5,
                    description=f"保存纹波波形: {vin}V_{iout_name}"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": False},
                    delay=0.5,
                    description="关闭负载输入"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="power_supply",
                    command="enable_output",
                    parameters={"enable": False},
                    delay=0.5,
                    description="关闭电源输出"
                ))
                step_id += 1

        return sequence

    def generate_dynamic_load_test(self, transition_slope: float = 1.0, period: float = 0.01) -> TimingSequence:
        sequence = TimingSequence(name=f"动态负载测试 (斜率={transition_slope}A/ms, 周期={period*1000}ms)")

        step_id = 1
        for vin in [self.params.vin_min, self.params.vin_typ, self.params.vin_max]:
            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="set_voltage",
                parameters={"voltage": vin},
                delay=0.5,
                description=f"设置输入电压 {vin}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="set_mode",
                parameters={"mode": "CC"},
                delay=0.5,
                description="设置负载CC模式"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="set_dynamic_params",
                parameters={
                    "level_a": self.params.iout_board,
                    "level_b": self.params.iout_overload,
                    "period": period,
                    "duty_cycle": 0.5
                },
                delay=0.5,
                description="设置动态负载参数"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": True},
                delay=1.0,
                description="开启电源输出"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="enable_input",
                parameters={"enable": True},
                delay=0.5,
                description="开启负载输入"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="start_dynamic",
                parameters={},
                delay=5.0,
                description="开始动态负载跳变"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="oscilloscope",
                command="save_waveform",
                parameters={"filename": f"dynamic_{vin}V", "channel": 1},
                delay=0.5,
                description=f"保存动态响应波形: {vin}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="stop_dynamic",
                parameters={},
                delay=0.5,
                description="停止动态负载"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="enable_input",
                parameters={"enable": False},
                delay=0.5,
                description="关闭负载输入"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": False},
                delay=0.5,
                description="关闭电源输出"
            ))
            step_id += 1

        return sequence

    def generate_dynamic_stability_test(self, period: float = 1.0) -> TimingSequence:
        sequence = TimingSequence(name=f"动态稳定度测试 (周期={period}s)")

        step_id = 1
        sequence.add_step(TimingStep(
            step_id=step_id,
            instrument="electronic_load",
            command="set_current",
            parameters={"current": self.params.iout_full},
            delay=0.5,
            description="设置满载负载"
        ))
        step_id += 1

        for _ in range(5):
            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="set_voltage",
                parameters={"voltage": self.params.vin_min},
                delay=period,
                description=f"设置输入电压 {self.params.vin_min}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="oscilloscope",
                command="save_waveform",
                parameters={"filename": f"stability_min_{_}", "channel": 1},
                delay=0.5,
                description=f"保存波形: Vin_min"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="set_voltage",
                parameters={"voltage": self.params.vin_max},
                delay=period,
                description=f"设置输入电压 {self.params.vin_max}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="oscilloscope",
                command="save_waveform",
                parameters={"filename": f"stability_max_{_}", "channel": 1},
                delay=0.5,
                description=f"保存波形: Vin_max"
            ))
            step_id += 1

        return sequence

    def generate_short_protection_test(self, duration: float = 600.0) -> TimingSequence:
        sequence = TimingSequence(name=f"短路保护测试 (持续{duration/60}分钟)")

        step_id = 1
        for vin in [self.params.vin_min, self.params.vin_typ, self.params.vin_max]:
            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="set_voltage",
                parameters={"voltage": vin},
                delay=0.5,
                description=f"设置输入电压 {vin}V"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="set_mode",
                parameters={"mode": "CR"},
                delay=0.5,
                description="设置负载CR模式"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="electronic_load",
                command="set_resistance",
                parameters={"resistance": 0.1},
                delay=0.5,
                description="设置小电阻(0.1ohm)"
            ))
            step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": True},
                delay=1.0,
                description="开启电源输出"
            ))
            step_id += 1

            cycles = int(duration / 10)
            for cycle in range(cycles):
                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": True},
                    delay=10.0,
                    description=f"短路 {cycle+1}/{cycles}"
                ))
                step_id += 1

                sequence.add_step(TimingStep(
                    step_id=step_id,
                    instrument="electronic_load",
                    command="enable_input",
                    parameters={"enable": False},
                    delay=0.5,
                    description="断开短路"
                ))
                step_id += 1

            sequence.add_step(TimingStep(
                step_id=step_id,
                instrument="power_supply",
                command="enable_output",
                parameters={"enable": False},
                delay=0.5,
                description="关闭电源输出"
            ))
            step_id += 1

        return sequence

    def generate_all_tests(self) -> List[TimingSequence]:
        tests = [
            self.generate_regulation_test(),
            self.generate_power_cycle_test(),
            self.generate_ripple_test(),
            self.generate_dynamic_load_test(),
            self.generate_dynamic_stability_test(),
            self.generate_short_protection_test()
        ]
        return tests

    def generate_region_tests(self, region: str) -> List[TimingSequence]:
        if region == "额定区":
            return [self.generate_regulation_test()]
        elif region == "一区":
            return [
                self.generate_dynamic_load_test(),
                self.generate_dynamic_stability_test()
            ]
        elif region == "二区":
            return [
                self.generate_power_cycle_test(),
                self.generate_short_protection_test()
            ]
        return []