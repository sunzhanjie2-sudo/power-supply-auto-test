"""USB-TMC通信模块，支持示波器等USB仪器"""
import time
import threading
from typing import Optional, Callable


class UsbtmcComm:
    def __init__(self):
        self.rm = None
        self.instrument = None
        self.is_connected = False
        self.lock = threading.Lock()
        self.read_callback: Optional[Callable[[str], None]] = None
        self.last_error: str = ""

    @staticmethod
    def list_devices() -> list:
        """列出所有USB-TMC设备"""
        devices = []
        try:
            import pyvisa
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            for resource in resources:
                if 'USB' in resource:
                    try:
                        inst = rm.open_resource(resource)
                        inst.timeout = 2000
                        idn = inst.query('*IDN?').strip()
                        devices.append({
                            'resource': resource,
                            'idn': idn,
                            'description': f'USB-TMC: {idn.split(",")[0] if "," in idn else idn}'
                        })
                        inst.close()
                    except Exception:
                        devices.append({
                            'resource': resource,
                            'idn': '',
                            'description': f'USB-TMC: {resource}'
                        })
            rm.close()
        except Exception as e:
            print(f"USB-TMC扫描失败: {e}")
        return devices

    def connect(self, resource: str) -> bool:
        """连接USB-TMC设备"""
        try:
            import pyvisa
            self.rm = pyvisa.ResourceManager()
            self.instrument = self.rm.open_resource(resource)
            self.instrument.timeout = 3000
            # Rigol DS1000E 等 USB-TMC 设备以 EOM 结束消息，显式设置 read_termination
            # 会触发 "doesn't end with termination characters" 告警，置为 None 更稳妥。
            self.instrument.read_termination = None
            self.instrument.write_termination = '\n'
            self.instrument.chunk_size = 2048
            self.is_connected = True
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def disconnect(self):
        """断开连接"""
        if self.instrument:
            try:
                self.instrument.close()
            except:
                pass
        if self.rm:
            try:
                self.rm.close()
            except:
                pass
        self.instrument = None
        self.rm = None
        self.is_connected = False

    def send_command(self, command: str, wait_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """发送命令"""
        if not self.is_connected or not self.instrument:
            return None

        with self.lock:
            try:
                if wait_response:
                    self.instrument.timeout = int(timeout * 1000)
                    response = self.instrument.query(command).strip()
                    if self.read_callback:
                        self.read_callback(response)
                    return response
                self.instrument.write(command)
                return None
            except Exception as e:
                self.last_error = str(e)
                return None

    def query(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """查询命令（发送后等待响应）"""
        return self.send_command(command, wait_response=True, timeout=timeout)

    def query_binary(self, command: str, timeout: float = 4.0) -> Optional[bytes]:
        """二进制读取（如示波器 :WAV:DATA?），返回原始字节。

        使用 pyvisa 的 query_binary_values 正确处理 IEEE488.2 块头（#9000000600...），
        避免二进制数据中的 0x0A 被误判为终止符。
        """
        if not self.is_connected or not self.instrument:
            return None
        with self.lock:
            try:
                self.instrument.timeout = int(timeout * 1000)
                values = self.instrument.query_binary_values(
                    command, datatype='B', is_big_endian=False, header_fmt='ieee'
                )
                return bytes(values)
            except Exception as e:
                self.last_error = str(e)
                return None

    def set_read_callback(self, callback: Callable[[str], None]):
        self.read_callback = callback

    def get_idn(self) -> Optional[str]:
        return self.query('*IDN?')