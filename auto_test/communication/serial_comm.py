import serial
import serial.tools.list_ports
from serial import PARITY_NONE, STOPBITS_ONE, EIGHTBITS
import time
import threading
from typing import Optional, Callable, Dict


class SerialComm:
    def __init__(self):
        self.ser = None
        self.is_connected = False
        self.lock = threading.Lock()
        self.read_callback: Optional[Callable[[str], None]] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False

    @staticmethod
    def list_ports() -> list:
        ports = serial.tools.list_ports.comports()
        port_info = []
        for port in ports:
            port_info.append({
                'port': port.device,
                'description': port.description,
                'hwid': port.hwid,
                'vid': port.vid,
                'pid': port.pid
            })
        return port_info

    def connect(self, port: str, baud_rate: int = 9600, timeout: float = 2.0) -> bool:
        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=baud_rate,
                parity=PARITY_NONE,
                stopbits=STOPBITS_ONE,
                bytesize=EIGHTBITS,
                timeout=timeout
            )
            if self.ser.is_open:
                self.is_connected = True
                self._running = True
                self._start_read_thread()
                return True
            return False
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def disconnect(self):
        self._running = False
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.is_connected = False

    def _start_read_thread(self):
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

    def _read_loop(self):
        while self._running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if data and self.read_callback:
                        self.read_callback(data)
                time.sleep(0.01)
            except Exception as e:
                print(f"读取错误: {e}")
                break

    def send_command(self, command: str, wait_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        if not self.is_connected or not self.ser:
            return None

        with self.lock:
            try:
                self.ser.write((command + '\n').encode('utf-8'))
                self.ser.flush()

                if wait_response:
                    start_time = time.time()
                    response = ""
                    while time.time() - start_time < timeout:
                        if self.ser.in_waiting > 0:
                            response += self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                            if '\n' in response or '\r' in response:
                                break
                        time.sleep(0.01)
                    return response.strip()
                return None
            except Exception as e:
                print(f"发送命令失败: {e}")
                return None

    def set_read_callback(self, callback: Callable[[str], None]):
        self.read_callback = callback


class InstrumentManager:
    def __init__(self):
        self.instruments: Dict[str, SerialComm] = {}
        self.instrument_info: Dict[str, dict] = {}

    def detect_instruments(self) -> Dict[str, dict]:
        ports = SerialComm.list_ports()
        detected = {}

        for port in ports:
            comm = SerialComm()
            if comm.connect(port['port']):
                time.sleep(0.5)
                response = comm.send_command('*IDN?', wait_response=True)
                if response:
                    detected[port['port']] = {
                        'port': port['port'],
                        'description': port['description'],
                        'idn': response.strip(),
                        'instrument_type': self._identify_instrument(response)
                    }
                comm.disconnect()

        return detected

    def _identify_instrument(self, idn_string: str) -> str:
        idn = idn_string.upper()
        if 'SPM' in idn or 'POWER' in idn:
            return 'power_supply'
        elif 'UTL' in idn or 'LOAD' in idn:
            return 'electronic_load'
        elif 'DS1' in idn or 'SCOPE' in idn or 'OSCILLOSCOPE' in idn:
            return 'oscilloscope'
        return 'unknown'

    def add_instrument(self, name: str, port: str, instrument_type: str):
        comm = SerialComm()
        if comm.connect(port):
            self.instruments[name] = comm
            self.instrument_info[name] = {
                'port': port,
                'type': instrument_type,
                'status': 'connected'
            }

    def remove_instrument(self, name: str):
        if name in self.instruments:
            self.instruments[name].disconnect()
            del self.instruments[name]
            del self.instrument_info[name]

    def get_instrument(self, name: str) -> Optional[SerialComm]:
        return self.instruments.get(name)

    def send_to_instrument(self, name: str, command: str, wait_response: bool = False) -> Optional[str]:
        comm = self.instruments.get(name)
        if comm:
            return comm.send_command(command, wait_response)
        return None

    def close_all(self):
        for comm in self.instruments.values():
            comm.disconnect()
        self.instruments.clear()
        self.instrument_info.clear()