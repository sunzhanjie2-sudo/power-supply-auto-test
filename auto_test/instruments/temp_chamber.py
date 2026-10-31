from .base_instrument import InstrumentBase
from typing import Optional
import time


class TempChamber(InstrumentBase):
    """高低温箱 - 预留接口，温箱型号待定"""

    def __init__(self, comm=None):
        super().__init__(comm)
        self._target_temp = 25.0
        self._current_temp = 25.0

    def connect(self) -> bool:
        """预留接口"""
        if self.comm and self.comm.is_connected:
            self.connected = True
            return True
        return False

    def disconnect(self):
        """预留接口"""
        self.connected = False
        if self.comm:
            self.comm.disconnect()

    def get_idn(self) -> Optional[str]:
        """预留接口"""
        return self.query('*IDN?')

    def set_temperature(self, temperature: float) -> bool:
        """设置目标温度 - 预留"""
        self._target_temp = temperature
        if self.connected:
            response = self.send_command(f':TEMP:SET {temperature}', wait_response=True)
            return response is not None and 'OK' in response.upper()
        return True

    def get_temperature(self) -> Optional[float]:
        """获取当前温度 - 预留"""
        if self.connected:
            response = self.query(':TEMP:CURR?')
            if response:
                try:
                    return float(response.strip())
                except ValueError:
                    pass
        return self._current_temp

    def wait_for_stable(self, tolerance: float = 0.5, timeout: float = 600) -> bool:
        """等待温度稳定 - 预留"""
        if not self.connected:
            return True
        start = time.time()
        while time.time() - start < timeout:
            current = self.get_temperature()
            if current and abs(current - self._target_temp) <= tolerance:
                return True
            time.sleep(5)
        return False

    def enable(self) -> bool:
        """启用温箱 - 预留"""
        if self.connected:
            response = self.send_command(':TEMP:ENAB ON', wait_response=True)
            return response is not None and 'OK' in response.upper()
        return True

    def disable(self) -> bool:
        """禁用温箱 - 预留"""
        if self.connected:
            response = self.send_command(':TEMP:ENAB OFF', wait_response=True)
            return response is not None and 'OK' in response.upper()
        return True

    def reset(self) -> bool:
        if self.connected:
            response = self.send_command('*RST', wait_response=True)
            return response is not None and 'OK' in response.upper()
        return True