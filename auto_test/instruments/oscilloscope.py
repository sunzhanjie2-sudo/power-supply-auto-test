from .base_instrument import BaseInstrument
from typing import Optional
import numpy as np


class Oscilloscope(BaseInstrument):
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

    def set_channel_enable(self, channel: int, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        response = self.send_command(f':CHAN{channel}:DISP {state}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_channel_scale(self, channel: int, scale: float) -> bool:
        response = self.send_command(f':CHAN{channel}:SCAL {scale}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_channel_offset(self, channel: int, offset: float) -> bool:
        response = self.send_command(f':CHAN{channel}:OFFS {offset}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_timebase_scale(self, scale: float) -> bool:
        response = self.send_command(f':TIM:SCAL {scale}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_trigger_mode(self, mode: str) -> bool:
        valid_modes = ['EDGE', 'PULSE', 'SLOPE', 'VIDEO', 'PATTERN']
        if mode not in valid_modes:
            return False
        response = self.send_command(f':TRIG:MODE {mode}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_trigger_source(self, source: str) -> bool:
        response = self.send_command(f':TRIG:SOUR {source}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_trigger_level(self, level: float) -> bool:
        response = self.send_command(f':TRIG:LEV {level}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_acquisition_mode(self, mode: str) -> bool:
        valid_modes = ['NORM', 'PEAK', 'HRES', 'AVER']
        if mode not in valid_modes:
            return False
        response = self.send_command(f':ACQ:MODE {mode}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_sample_rate(self, rate: float) -> bool:
        response = self.send_command(f':ACQ:SRAT {rate}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_bandwidth(self, channel: int, bandwidth: str) -> bool:
        response = self.send_command(f':CHAN{channel}:BW {bandwidth}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def set_dc_offset(self, channel: int, offset: float) -> bool:
        response = self.send_command(f':CHAN{channel}:OFFS {offset}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def get_waveform_data(self, channel: int = 1) -> Optional[np.ndarray]:
        self.send_command(f':WAV:SOUR CHAN{channel}')
        self.send_command(':WAV:FORM BYTE')
        self.send_command(':WAV:MODE NORM')

        response = self.query(':WAV:DATA?')
        if response:
            try:
                header_len = int(response[1]) + 2
                raw_data = response[header_len:]
                data = np.array([ord(c) for c in raw_data])
                return data
            except (ValueError, IndexError):
                return None
        return None

    def get_waveform_preamble(self) -> Optional[dict]:
        response = self.query(':WAV:PRE?')
        if response:
            try:
                parts = response.split(',')
                return {
                    'format': int(parts[0]),
                    'type': int(parts[1]),
                    'points': int(parts[2]),
                    'count': int(parts[3]),
                    'xincrement': float(parts[4]),
                    'xorigin': float(parts[5]),
                    'xreference': float(parts[6]),
                    'yincrement': float(parts[7]),
                    'yorigin': float(parts[8]),
                    'yreference': float(parts[9])
                }
            except (ValueError, IndexError):
                return None
        return None

    def save_waveform(self, filename: str, channel: int = 1) -> bool:
        self.send_command(f':WAV:SOUR CHAN{channel}')
        response = self.send_command(f':SAVE:WAV {filename}', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def run(self) -> bool:
        response = self.send_command(':RUN', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def stop(self) -> bool:
        response = self.send_command(':STOP', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def single(self) -> bool:
        response = self.send_command(':SING', wait_response=True)
        return response is not None and 'OK' in response.upper()

    def reset(self) -> bool:
        response = self.send_command('*RST', wait_response=True)
        return response is not None and 'OK' in response.upper()