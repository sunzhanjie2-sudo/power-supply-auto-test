import serial
import serial.tools.list_ports
from serial import PARITY_NONE, STOPBITS_ONE, EIGHTBITS
import time
import subprocess
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
        self.last_error: str = ""
        self._response_buffer: list = []  # 后台读取线程的响应缓冲区
        self._buffer_lock = threading.Lock()

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

    @staticmethod
    def _release_port(port: str):
        """释放被占用的串口端口"""
        try:
            subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass',
                 '-Command', f'$port = New-Object System.IO.Ports.SerialPort("{port}"); $port.Close()'],
                capture_output=True,
                timeout=5
            )
            time.sleep(0.5)
            return True
        except:
            return False

    @staticmethod
    def _force_release_port(port: str):
        """强制释放端口 - 尝试以其他波特率打开并关闭"""
        alt_bauds = [19200, 38400, 57600, 115200]
        for baud in alt_bauds:
            try:
                temp_ser = serial.Serial(
                    port=port,
                    baudrate=baud,
                    parity=PARITY_NONE,
                    stopbits=STOPBITS_ONE,
                    bytesize=EIGHTBITS,
                    timeout=1.0
                )
                if temp_ser.is_open:
                    temp_ser.close()
                    time.sleep(0.3)
                    return True
            except:
                pass
        return False

    def connect(self, port: str, baud_rate: int = 9600, timeout: float = 2.0) -> bool:
        """连接串口"""
        if self.ser and self.ser.is_open:
            self.ser.close()

        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=baud_rate,
                parity=PARITY_NONE,
                stopbits=STOPBITS_ONE,
                bytesize=EIGHTBITS,
                timeout=timeout,
                write_timeout=2.0,
                dsrdtr=False,
                rtscts=False
            )
            if self.ser.is_open:
                time.sleep(0.1)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                self.is_connected = True
                self._running = True
                self._start_read_thread()
                self.last_error = ""
                return True
            self.last_error = f"端口 {port} 打开后 is_open=False"
            return False
        except PermissionError:
            try:
                self._release_port(port)
                self.ser = serial.Serial(
                    port=port,
                    baudrate=baud_rate,
                    parity=PARITY_NONE,
                    stopbits=STOPBITS_ONE,
                    bytesize=EIGHTBITS,
                    timeout=timeout,
                    write_timeout=2.0,
                    dsrdtr=False,
                    rtscts=False
                )
                if self.ser.is_open:
                    time.sleep(0.1)
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                    self.is_connected = True
                    self._running = True
                    self._start_read_thread()
                    self.last_error = ""
                    return True
            except Exception:
                pass

            try:
                self._force_release_port(port)
                self.ser = serial.Serial(
                    port=port,
                    baudrate=baud_rate,
                    parity=PARITY_NONE,
                    stopbits=STOPBITS_ONE,
                    bytesize=EIGHTBITS,
                    timeout=timeout,
                    write_timeout=2.0,
                    dsrdtr=False,
                    rtscts=False
                )
                if self.ser.is_open:
                    time.sleep(0.1)
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                    self.is_connected = True
                    self._running = True
                    self._start_read_thread()
                    self.last_error = ""
                    return True
                self.last_error = f"端口 {port} 强制释放后仍无法打开"
                return False
            except Exception as e2:
                self.last_error = f"端口 {port} 强制释放失败: {e2}"
                return False
        except OSError as e:
            if "没有发挥作用" in str(e) or e.winerror == 31:
                try:
                    self._release_port(port)
                    self.ser = serial.Serial(
                        port=port,
                        baudrate=baud_rate,
                        parity=PARITY_NONE,
                        stopbits=STOPBITS_ONE,
                        bytesize=EIGHTBITS,
                        timeout=timeout,
                        write_timeout=2.0,
                        dsrdtr=False,
                        rtscts=False
                    )
                    if self.ser.is_open:
                        time.sleep(0.1)
                        self.ser.reset_input_buffer()
                        self.ser.reset_output_buffer()
                        self.is_connected = True
                        self._running = True
                        self._start_read_thread()
                        self.last_error = ""
                        return True
                except Exception:
                    pass

                try:
                    self._force_release_port(port)
                    self.ser = serial.Serial(
                        port=port,
                        baudrate=baud_rate,
                        parity=PARITY_NONE,
                        stopbits=STOPBITS_ONE,
                        bytesize=EIGHTBITS,
                        timeout=timeout,
                        write_timeout=2.0,
                        dsrdtr=False,
                        rtscts=False
                    )
                    if self.ser.is_open:
                        time.sleep(0.1)
                        self.ser.reset_input_buffer()
                        self.ser.reset_output_buffer()
                        self.is_connected = True
                        self._running = True
                        self._start_read_thread()
                        self.last_error = ""
                        return True
                    self.last_error = f"端口 {port} 强制释放后仍无法打开"
                    return False
                except Exception as e2:
                    self.last_error = f"端口 {port} 强制释放失败: {e2}"
                    return False
            self.last_error = str(e)
            return False
        except Exception as e:
            self.last_error = str(e)
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
                    if data:
                        # 存入缓冲区供 send_command 读取
                        with self._buffer_lock:
                            self._response_buffer.append(data)
                        if self.read_callback:
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
                if wait_response:
                    # 发送前清空残留缓冲区，避免误读上一次的旧数据
                    with self._buffer_lock:
                        self._response_buffer.clear()

                self.ser.write((command + '\r\n').encode('utf-8'))
                self.ser.flush()

                if wait_response:
                    start_time = time.time()
                    response_parts = []
                    # 等待响应
                    while time.time() - start_time < timeout:
                        # 检查缓冲区
                        with self._buffer_lock:
                            if self._response_buffer:
                                response_parts.extend(self._response_buffer)
                                self._response_buffer.clear()
                                break
                        # The background thread is the sole serial reader. Reading
                        # here races readline() and can turn 12.116 into 2.116.
                        time.sleep(0.02)
                    response = ''.join(response_parts).strip()
                    self.last_error = "" if response else f"响应超时: {command}"
                    return response if response else None
                self.last_error = ""
                return None
            except Exception as e:
                self.last_error = str(e)
                print(f"发送命令失败: {e}")
                return None

    def set_read_callback(self, callback: Callable[[str], None]):
        self.read_callback = callback


class InstrumentManager:
    def __init__(self):
        self.instruments: Dict[str, object] = {}
        self.instrument_info: Dict[str, dict] = {}

    def detect_instruments(self, baud_rates: list = None) -> Dict[str, dict]:
        """扫描并识别仪器，支持串口和USB-TMC设备"""
        if baud_rates is None:
            baud_rates = [115200, 9600, 19200, 38400, 57600]

        detected = {}
        tried_ports = set()

        # 扫描串口设备（跳过蓝牙虚拟串口等明显非仪器端口，显著加快扫描速度）
        all_ports = SerialComm.list_ports()
        ports = [p for p in all_ports if "BTHENUM" not in (p.get("hwid") or "").upper()]
        for baud in baud_rates:
            for port in ports:
                if port['port'] in tried_ports:
                    continue

                comm = SerialComm()
                if comm.connect(port['port'], baud_rate=baud):
                    time.sleep(0.3)
                    response = comm.send_command('*IDN?', wait_response=True, timeout=1.0)
                    if not response:
                        # 部分仪器上电/串口时序存在抖动，首次 *IDN? 可能失败，重试一次
                        time.sleep(0.2)
                        response = comm.send_command('*IDN?', wait_response=True, timeout=1.0)
                    if response:
                        detected[port['port']] = {
                            'port': port['port'],
                            'description': port['description'],
                            'idn': response.strip(),
                            'instrument_type': self._identify_instrument(response, port['vid'], port['pid']),
                            'baud_rate': baud,
                            'comm_type': 'serial'
                        }
                        tried_ports.add(port['port'])
                    comm.disconnect()

        # 扫描USB-TMC设备
        try:
            from .usbtmc_comm import UsbtmcComm
            usbtmc_devices = UsbtmcComm.list_devices()
            for dev in usbtmc_devices:
                resource = dev['resource']
                idn = dev['idn']
                detected[resource] = {
                    'port': resource,
                    'description': dev['description'],
                    'idn': idn,
                    'instrument_type': self._identify_instrument(idn),
                    'baud_rate': None,
                    'comm_type': 'usbtmc'
                }
        except Exception as e:
            print(f"USB-TMC扫描失败: {e}")

        return detected

    def _identify_instrument(self, idn_string: str, vid: int = 0, pid: int = 0) -> str:
        idn = idn_string.upper() if idn_string else ''

        # 根据IDN识别
        if 'UTL' in idn or 'LOAD' in idn:
            return 'electronic_load'
        elif 'DS1' in idn or 'DS2' in idn or 'DS3' in idn or 'SCOPE' in idn or 'OSCILLOSCOPE' in idn or 'DIGITAL STORAGE' in idn:
            return 'oscilloscope'
        elif 'SPM' in idn or 'POWER' in idn or 'PSU' in idn or 'SUPPLY' in idn:
            return 'power_supply'
        elif 'CHAMBER' in idn or 'TEMP' in idn or 'OVEN' in idn:
            return 'temp_chamber'
        # Keysight/Agilent示波器
        elif 'KEYSIGHT' in idn or 'AGILENT' in idn:
            return 'oscilloscope'
        # Siglent示波器
        elif 'SIGLENT' in idn:
            return 'oscilloscope'
        # ITECH电源
        elif 'ITECH' in idn:
            return 'power_supply'
        # OWON电源
        elif 'OWON' in idn:
            return 'power_supply'
        # Chroma电子负载
        elif 'CHROMA' in idn:
            return 'electronic_load'

        # 根据VID/PID识别（常见仪器芯片）
        if vid:
            # 优利德仪器
            if vid == 0x0483 or vid == 0x1A86:
                if 'LOAD' in idn or 'UTL' in idn:
                    return 'electronic_load'
                elif 'DS1' in idn or 'DS2' in idn:
                    return 'oscilloscope'
            # Rigol
            elif vid == 0x1AB1:
                if 'DS' in idn or 'DG' in idn:
                    return 'oscilloscope'
                elif 'DP' in idn:
                    return 'power_supply'

        return 'unknown'

    def add_instrument(self, name: str, port: str, instrument_type: str, comm_type: str = 'serial', baud_rate: int = 9600):
        """添加仪器，支持串口和USB-TMC"""
        if comm_type == 'usbtmc':
            from .usbtmc_comm import UsbtmcComm
            comm = UsbtmcComm()
            if comm.connect(port):
                self.instruments[name] = comm
                self.instrument_info[name] = {
                    'port': port,
                    'type': instrument_type,
                    'status': 'connected',
                    'comm_type': 'usbtmc'
                }
        else:
            comm = SerialComm()
            if comm.connect(port, baud_rate=baud_rate):
                self.instruments[name] = comm
                self.instrument_info[name] = {
                    'port': port,
                    'type': instrument_type,
                    'status': 'connected',
                    'comm_type': 'serial'
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

    def get_connected_instruments(self) -> dict:
        """获取所有已连接仪器的信息"""
        result = {}
        for name, info in self.instrument_info.items():
            if info.get('status') == 'connected':
                result[name] = info
        return result

    def is_connected(self, name: str) -> bool:
        """检查仪器是否已连接"""
        return name in self.instruments
