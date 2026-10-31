from .base_instrument import InstrumentBase
from typing import Optional
import time


class PowerSupply(InstrumentBase):
    """OWON SPM 系列直流源驱动。

    与其它仪器一致，直接持有一个通信对象（SerialComm / UsbtmcComm / VisaComm），
    命令遵循 OWON SPM 编程手册。
    """

    def __init__(self, comm=None):
        super().__init__(comm)
        self._last_command = 0.0

    def send_command(self, command, wait_response=False, timeout=None):
        # SPM6103 silently drops back-to-back settings (VOLT followed by CURR).
        gap = 0.2 - (time.monotonic() - self._last_command)
        if gap > 0:
            time.sleep(gap)
        result = super().send_command(command, wait_response, timeout)
        self._last_command = time.monotonic()
        return result

    def connect(self) -> bool:
        if self.comm and self.comm.is_connected:
            self.connected = True
            return True
        return False

    def disconnect(self):
        self.connected = False
        if self.comm:
            self.comm.disconnect()

    def get_idn(self) -> Optional[str]:
        return self.query("*IDN?")

    def reset(self) -> bool:
        self.send_command("*RST")
        return True

    def set_voltage(self, voltage: float):
        """设置输出电压 (OWON: VOLT <value>)"""
        self.send_command(f"VOLT {voltage:.3f}")

    def get_voltage(self) -> float:
        """获取设置的电压值"""
        return self._to_float(self.query("VOLT?"))

    def set_current(self, current: float):
        """设置输出电流 (OWON: CURR <value>)"""
        self.send_command(f"CURR {current:.3f}")

    def get_current(self) -> float:
        """获取设置的电流值"""
        return self._to_float(self.query("CURR?"))

    def set_current_limit(self, limit: float):
        """设置过流保护值 (OWON: CURR:LIM <value>)"""
        self.send_command(f"CURR:LIM {limit:.3f}")

    def get_current_limit(self) -> float:
        """获取过流保护值"""
        return self._to_float(self.query("CURR:LIM?"))

    def set_voltage_limit(self, limit: float):
        """设置过压保护值 (OWON: VOLT:LIM <value>)"""
        self.send_command(f"VOLT:LIM {limit:.3f}")

    def get_voltage_limit(self) -> float:
        """获取过压保护值"""
        return self._to_float(self.query("VOLT:LIM?"))

    def enable_output(self, enable: bool):
        """开启/关闭输出 (OWON: OUTP ON|OFF)

        SPM 在本地模式（SYST:LOC 或前面板操作后）会忽略 OUTP ON，
        开输出前先进入远程模式。
        """
        if enable:
            self.set_remote()
            time.sleep(0.1)
        self.send_command("OUTP ON" if enable else "OUTP OFF")

    def disable_output(self):
        """关闭输出（enable_output(False) 的语义化别名）"""
        self.enable_output(False)

    def get_output_state(self) -> Optional[bool]:
        """查询输出状态"""
        resp = self.query("OUTP?")
        if resp is None:
            return None
        state = resp.strip().upper()
        if state in ("1", "ON"):
            return True
        if state in ("0", "OFF"):
            return False
        return None

    def measure_voltage(self) -> float:
        """测量实际输出电压 (OWON: MEAS:VOLT?)"""
        return self._to_float(self.query("MEAS:VOLT?"))

    def measure_current(self) -> float:
        """测量实际输出电流 (OWON: MEAS:CURR?)"""
        return self._to_float(self.query("MEAS:CURR?"))

    def measure_power(self) -> float:
        """测量实际输出功率 (OWON: MEAS:POW?)"""
        return self._to_float(self.query("MEAS:POW?"))

    def measure_all(self) -> dict:
        """测量电压、电流、功率 (OWON: MEAS:ALL?)

        兼容空格或逗号分隔的返回格式。
        """
        resp = self.query("MEAS:ALL?")
        if resp:
            import re
            parts = [p for p in re.split(r"[\s,]+", resp.strip()) if p]
            if len(parts) >= 3:
                try:
                    return {
                        'voltage': float(parts[0]),
                        'current': float(parts[1]),
                        'power': float(parts[2])
                    }
                except ValueError:
                    pass
        return {'voltage': 0.0, 'current': 0.0, 'power': 0.0}

    def set_remote(self):
        """设置为远程控制模式 (OWON: SYST:REM)"""
        self.send_command("SYST:REM")

    def set_local(self):
        """设置为本地控制模式 (OWON: SYST:LOC)"""
        self.send_command("SYST:LOC")

    def initialize(self, voltage: float = 0, current: float = 0):
        """初始化电源：进入远程、关输出、配置电压/电流与保护限值"""
        self.set_remote()
        time.sleep(0.1)
        self.enable_output(False)
        time.sleep(0.1)
        self.set_voltage(voltage)
        time.sleep(0.1)
        self.set_current(current)
        time.sleep(0.1)
        if voltage > 0:
            self.set_voltage_limit(voltage * 1.2)
            time.sleep(0.1)
        if current > 0:
            self.set_current_limit(current * 1.1)

    def shutdown(self):
        """关闭电源输出并回到本地模式"""
        self.enable_output(False)
        self.set_local()

    @staticmethod
    def _to_float(value: Optional[str]) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
