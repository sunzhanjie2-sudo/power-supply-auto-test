from .base_instrument import BaseInstrument
from typing import Optional


class ElectronicLoad(BaseInstrument):
    def __init__(self, comm):
        super().__init__(comm)

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
        return self.query('*IDN?')

    def set_mode(self, mode: str) -> bool:
        valid_modes = ['CC', 'CV', 'CR', 'CP']
        if mode not in valid_modes:
            return False
        response = self.send_command(f':SOUR:FUNC {mode}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_current(self, current: float) -> bool:
        response = self.send_command(f':SOUR:CURR {current}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_voltage(self, voltage: float) -> bool:
        response = self.send_command(f':SOUR:VOLT {voltage}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_resistance(self, resistance: float) -> bool:
        response = self.send_command(f':SOUR:RES {resistance}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_power(self, power: float) -> bool:
        response = self.send_command(f':SOUR:POW {power}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def get_voltage(self) -> Optional[float]:
        response = self.query(':MEAS:VOLT?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def get_current(self) -> Optional[float]:
        response = self.query(':MEAS:CURR?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def get_power(self) -> Optional[float]:
        response = self.query(':MEAS:POW?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def enable_input(self, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        response = self.send_command(f':INP {state}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def disable_input(self) -> bool:
        return self.enable_input(False)

    def set_dynamic_params(self, level_a: float, level_b: float, period: float, duty_cycle: float) -> bool:
        response = self.send_command(f':SOUR:DYN:LEV {level_a},{level_b}', wait_response=True)
        if not (response and 'OK' in response.upper()):
            return False
        response = self.send_command(f':SOUR:DYN:PER {period}', wait_response=True)
        if not (response and 'OK' in response.upper()):
            return False
        response = self.send_command(f':SOUR:DYN:DUTY {duty_cycle}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def start_dynamic(self) -> bool:
        response = self.send_command(':SOUR:DYN:STAR', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def stop_dynamic(self) -> bool:
        response = self.send_command(':SOUR:DYN:STOP', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_remote_sense(self, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        response = self.send_command(f':SENS:REM {state}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def reset(self) -> bool:
        response = self.send_command('*RST', wait_response=True)
        return response is not None and 'OK' in response.upper()