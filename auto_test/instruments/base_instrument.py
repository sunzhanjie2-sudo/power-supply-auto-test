from abc import ABC, abstractmethod
from typing import Optional


class InstrumentBase(ABC):
    def __init__(self, comm=None):
        self.comm = comm
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def get_idn(self) -> Optional[str]:
        pass

    def send_command(self, command: str, wait_response: bool = False, timeout=None) -> Optional[str]:
        if self.comm and self.connected:
            if timeout is not None:
                return self.comm.send_command(command, wait_response, timeout)
            return self.comm.send_command(command, wait_response)
        return None

    def query(self, command: str, timeout=None) -> Optional[str]:
        return self.send_command(command, wait_response=True, timeout=timeout)

    def reset(self) -> bool:
        # *RST 为无应答命令，写入成功即视为已执行
        if not (self.comm and self.connected):
            return False
        self.send_command('*RST')
        return True