"""使用pyvisa实现VISA通信"""
import pyvisa
from typing import Optional, Callable


class VisaComm:
    def __init__(self):
        self.rm = None
        self.inst = None
        self.is_connected = False
        self.last_error = ""
        self.read_callback: Optional[Callable[[str], None]] = None

    @staticmethod
    def list_devices() -> list:
        """列出所有 VISA USB 设备（跳过 ASRL 串口，串口由 SerialComm 单独扫描，避免抢占串口）"""
        devices = []
        try:
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            for resource in resources:
                # 仅扫描 USB 资源，串口(ASRL)交给 SerialComm 处理，
                # 否则 VISA 后台扫描会打开 CH340 等串口，与串口检测互相干扰
                if not resource.upper().startswith("USB"):
                    continue
                try:
                    inst = rm.open_resource(resource)
                    inst.timeout = 2000
                    idn = inst.query('*IDN?').strip()
                    inst.close()
                    devices.append({
                        'resource': resource,
                        'idn': idn,
                        'description': idn
                    })
                except Exception:
                    devices.append({
                        'resource': resource,
                        'idn': '',
                        'description': resource
                    })
            rm.close()
        except Exception:
            pass
        return devices

    def connect(self, resource: str) -> bool:
        """连接指定VISA资源"""
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(resource)
            self.inst.timeout = 2000
            self.is_connected = True
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def disconnect(self):
        """断开连接"""
        if self.inst:
            try:
                self.inst.close()
            except:
                pass
            self.inst = None
        if self.rm:
            try:
                self.rm.close()
            except:
                pass
            self.rm = None
        self.is_connected = False

    def send_command(self, command: str, wait_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """发送命令"""
        if not self.is_connected or not self.inst:
            return None

        try:
            self.inst.timeout = int(timeout * 1000)

            if wait_response:
                response = self.inst.query(command)
                response = response.strip()
                if self.read_callback:
                    self.read_callback(response)
                return response
            else:
                self.inst.write(command)
                return None
        except Exception as e:
            self.last_error = str(e)
            return None

    def query(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """查询命令"""
        return self.send_command(command, wait_response=True, timeout=timeout)

    def query_binary(self, command: str, timeout: float = 4.0) -> Optional[bytes]:
        """二进制读取（如示波器 :WAV:DATA?），返回原始字节。"""
        if not self.is_connected or not self.inst:
            return None
        try:
            self.inst.timeout = int(timeout * 1000)
            values = self.inst.query_binary_values(
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