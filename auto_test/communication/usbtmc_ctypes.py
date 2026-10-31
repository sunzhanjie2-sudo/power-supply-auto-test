"""使用ctypes直接调用libusb实现USB-TMC通信"""
import ctypes
import ctypes.util
import os
import time
import threading
from typing import Optional, Callable


def _find_libusb_dll() -> str:
    """定位 libusb-1.0 动态库，返回可加载的绝对路径。

    优先使用 libusb_package 打包的库，其次尝试系统搜索路径，最后回退到常见安装位置。
    """
    # 1) libusb_package（自带 libusb-1.0.dll，可跨机器使用）
    try:
        import libusb_package
        pkg_dir = os.path.dirname(libusb_package.__file__)
        candidate = os.path.join(pkg_dir, "libusb-1.0.dll")
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    # 2) 系统搜索路径
    for name in ("usb-1.0", "libusb-1.0", "libusb-1.0.dll"):
        try:
            found = ctypes.util.find_library(name)
        except Exception:
            found = None
        if found and os.path.exists(found):
            return found

    # 3) 常见安装位置（含旧版硬编码路径）
    candidates = [
        r"C:\Users\ASUS\AppData\Local\Programs\Python\Python313\Lib\site-packages\libusb_package\libusb-1.0.dll",
        r"C:\Windows\System32\libusb-1.0.dll",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError("未找到 libusb-1.0.dll，请安装 libusb_package (pip install libusb-package)")


class UsbtmcCtypes:
    def __init__(self):
        self.libusb = None
        self.ctx = ctypes.c_void_p()
        self.handle = ctypes.c_void_p()
        self.is_connected = False
        self.out_ep = 0x02
        self.in_ep = 0x81
        self.lock = threading.Lock()
        self.read_callback: Optional[Callable[[str], None]] = None
        self.last_error: str = ""

    def _load_libusb(self) -> bool:
        """加载libusb库"""
        try:
            libusb_path = _find_libusb_dll()
            self.libusb = ctypes.CDLL(libusb_path)

            self.libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            self.libusb.libusb_init.restype = ctypes.c_int

            self.libusb.libusb_exit.argtypes = [ctypes.c_void_p]

            self.libusb.libusb_get_device_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
            self.libusb.libusb_get_device_list.restype = ctypes.c_int

            self.libusb.libusb_free_device_list.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]

            self.libusb.libusb_get_device_descriptor.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8)]
            self.libusb.libusb_get_device_descriptor.restype = ctypes.c_int

            self.libusb.libusb_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            self.libusb.libusb_open.restype = ctypes.c_int

            self.libusb.libusb_close.argtypes = [ctypes.c_void_p]

            self.libusb.libusb_get_string_descriptor_ascii.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int]
            self.libusb.libusb_get_string_descriptor_ascii.restype = ctypes.c_int

            self.libusb.libusb_set_configuration.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.libusb.libusb_set_configuration.restype = ctypes.c_int

            self.libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.libusb.libusb_claim_interface.restype = ctypes.c_int

            self.libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.libusb.libusb_release_interface.restype = ctypes.c_int

            self.libusb.libusb_bulk_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
            self.libusb.libusb_bulk_transfer.restype = ctypes.c_int

            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    @staticmethod
    def list_devices() -> list:
        """列出所有USB设备"""
        devices = []
        try:
            libusb = ctypes.CDLL(_find_libusb_dll())

            libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            libusb.libusb_init.restype = ctypes.c_int

            libusb.libusb_exit.argtypes = [ctypes.c_void_p]

            libusb.libusb_get_device_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
            libusb.libusb_get_device_list.restype = ctypes.c_int

            libusb.libusb_free_device_list.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]

            libusb.libusb_get_device_descriptor.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8)]
            libusb.libusb_get_device_descriptor.restype = ctypes.c_int

            libusb.libusb_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            libusb.libusb_open.restype = ctypes.c_int

            libusb.libusb_close.argtypes = [ctypes.c_void_p]

            libusb.libusb_get_string_descriptor_ascii.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int]
            libusb.libusb_get_string_descriptor_ascii.restype = ctypes.c_int

            ctx = ctypes.c_void_p()
            libusb.libusb_init(ctypes.byref(ctx))

            devs = ctypes.POINTER(ctypes.c_void_p)()
            count = libusb.libusb_get_device_list(ctx, ctypes.byref(devs))

            for i in range(count):
                dev = devs[i]
                desc = (ctypes.c_uint8 * 18)()
                if libusb.libusb_get_device_descriptor(dev, desc) == 0:
                    vid = (desc[8] << 8) | desc[9]
                    pid = (desc[10] << 8) | desc[11]

                    handle = ctypes.c_void_p()
                    if libusb.libusb_open(dev, ctypes.byref(handle)) == 0:
                        str_buf = ctypes.create_string_buffer(256)
                        libusb.libusb_get_string_descriptor_ascii(handle, 1, str_buf, 256)
                        mfr = str_buf.value.decode('utf-8', errors='ignore')

                        libusb.libusb_get_string_descriptor_ascii(handle, 2, str_buf, 256)
                        prod = str_buf.value.decode('utf-8', errors='ignore')

                        libusb.libusb_get_string_descriptor_ascii(handle, 3, str_buf, 256)
                        sn = str_buf.value.decode('utf-8', errors='ignore')

                        devices.append({
                            'vid': vid,
                            'pid': pid,
                            'manufacturer': mfr,
                            'product': prod,
                            'serial_number': sn,
                            'resource': f'USB0::{vid:04X}::{pid:04X}::{sn}::INSTR'
                        })

                        libusb.libusb_close(handle)

            libusb.libusb_free_device_list(devs, 1)
            libusb.libusb_exit(ctx)

        except Exception as e:
            print(f'扫描失败: {e}')

        return devices

    def connect(self, vid: int = 0x1AB1, pid: int = 0x0588) -> bool:
        """连接指定VID/PID的设备"""
        if not self._load_libusb():
            return False

        result = self.libusb.libusb_init(ctypes.byref(self.ctx))
        if result != 0:
            self.last_error = f'初始化失败: {result}'
            return False

        devs = ctypes.POINTER(ctypes.c_void_p)()
        count = self.libusb.libusb_get_device_list(self.ctx, ctypes.byref(devs))

        target_dev = None
        for i in range(count):
            dev = devs[i]
            desc = (ctypes.c_uint8 * 18)()
            if self.libusb.libusb_get_device_descriptor(dev, desc) == 0:
                dev_vid = (desc[8] << 8) | desc[9]
                dev_pid = (desc[10] << 8) | desc[11]
                if dev_vid == vid and dev_pid == pid:
                    target_dev = dev
                    break

        if not target_dev:
            self.libusb.libusb_free_device_list(devs, 1)
            self.libusb.libusb_exit(self.ctx)
            self.last_error = f'未找到设备 VID=0x{vid:04X}, PID=0x{pid:04X}'
            return False

        result = self.libusb.libusb_open(target_dev, ctypes.byref(self.handle))
        self.libusb.libusb_free_device_list(devs, 1)

        if result != 0:
            self.libusb.libusb_exit(self.ctx)
            self.last_error = f'打开设备失败: {result}'
            return False

        result = self.libusb.libusb_set_configuration(self.handle, 1)
        if result != 0:
            self.libusb.libusb_close(self.handle)
            self.libusb.libusb_exit(self.ctx)
            self.last_error = f'设置配置失败: {result}'
            return False

        result = self.libusb.libusb_claim_interface(self.handle, 0)
        if result != 0:
            self.libusb.libusb_close(self.handle)
            self.libusb.libusb_exit(self.ctx)
            self.last_error = f'声明接口失败: {result}'
            return False

        self.is_connected = True
        return True

    def disconnect(self):
        """断开连接"""
        if self.handle and self.is_connected:
            self.libusb.libusb_release_interface(self.handle, 0)
            self.libusb.libusb_close(self.handle)
        if self.ctx:
            self.libusb.libusb_exit(self.ctx)
        self.is_connected = False
        self.handle = ctypes.c_void_p()
        self.ctx = ctypes.c_void_p()

    def send_command(self, command: str, wait_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """发送命令"""
        if not self.is_connected or not self.libusb:
            return None

        with self.lock:
            try:
                cmd_bytes = command.encode('utf-8') if isinstance(command, str) else command
                if not cmd_bytes.endswith(b'\n'):
                    cmd_bytes += b'\n'

                transferred = ctypes.c_int()
                result = self.libusb.libusb_bulk_transfer(
                    self.handle,
                    self.out_ep,
                    cmd_bytes, len(cmd_bytes),
                    ctypes.byref(transferred),
                    int(timeout * 1000)
                )

                if result != 0:
                    self.last_error = f'发送失败: {result}'
                    return None

                if wait_response:
                    time.sleep(0.3)
                    resp_buf = ctypes.create_string_buffer(1024)
                    result = self.libusb.libusb_bulk_transfer(
                        self.handle,
                        self.in_ep,
                        resp_buf, 1024,
                        ctypes.byref(transferred),
                        int(timeout * 1000)
                    )

                    if result != 0:
                        self.last_error = f'读取失败: {result}'
                        return None

                    response = resp_buf.value[:transferred.value].decode('utf-8', errors='ignore').strip()
                    if self.read_callback:
                        self.read_callback(response)
                    return response

                return None

            except Exception as e:
                self.last_error = str(e)
                return None

    def query(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """查询命令"""
        return self.send_command(command, wait_response=True, timeout=timeout)

    def set_read_callback(self, callback: Callable[[str], None]):
        self.read_callback = callback

    def get_idn(self) -> Optional[str]:
        return self.query('*IDN?')