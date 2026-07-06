from abc import ABC, abstractmethod
from typing import Optional


class BaseInstrument(ABC):
    def __init__(self, comm):
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

    def send_command(self, command: str, wait_response: bool = False) -> Optional[str]:
        if self.comm and self.connected:
            return self.comm.send_command(command, wait_response)
        return None

    def query(self, command: str) -> Optional[str]:
        return self.send_command(command, wait_response=True)