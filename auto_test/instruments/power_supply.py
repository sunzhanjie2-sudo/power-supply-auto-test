from .base_instrument import BaseInstrument
from typing import Optional


class PowerSupply(BaseInstrument):
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

    def set_voltage(self, voltage: float) -> bool:
        response = self.send_command(f':SOUR:VOLT {voltage}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_current(self, current: float) -> bool:
        response = self.send_command(f':SOUR:CURR {current}', wait_response=True)
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

    def enable_output(self, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        response = self.send_command(f':OUTP {state}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def disable_output(self) -> bool:
        return self.enable_output(False)

    def set_overvoltage_protection(self, voltage: float) -> bool:
        response = self.send_command(f':SOUR:VOLT:PROT {voltage}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_overcurrent_protection(self, current: float) -> bool:
        response = self.send_command(f':SOUR:CURR:PROT {current}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def reset(self) -> bool:
        response = self.send_command('*RST', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def save_settings(self, memory_slot: int = 1) -> bool:
        response = self.send_command(f':SYST:SAVE {memory_slot}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def recall_settings(self, memory_slot: int = 1) -> bool:
        response = self.send_command(f':SYST:RCL {memory_slot}', wait_response=True)
        return response is not None and 'OK' in response.upper()