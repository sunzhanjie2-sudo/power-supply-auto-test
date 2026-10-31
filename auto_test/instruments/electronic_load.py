from .base_instrument import InstrumentBase
from typing import Optional
import time
import threading


class ElectronicLoad(InstrumentBase):
    """UNI-T UTL8212 电子负载驱动（依据《UTL8200系列编程手册 REV.3》）。

    实测固件特性（真机联调确认）：
    1. FUNC? 返回模式码：0=CC, 1=CV, 2=CR, 3=CP, 4=DYN。
    2. 模式切换要求输入关闭。
    3. CR/CC 等设定值在「输入开启」状态下发送才立即生效；输入关闭时发送仅被
       存储、不会在下次开输入时应用。因此开输入后需重发当前模式设定值。
    4. SYST:REM 会把模式重置回 CC，驱动内部绝不发送该命令。
    5. 动态模式为电流动态（DYN:HIGH/LOW，单位 A），由 INP ON 启动。
    """

    # FUNC? 返回码 <-> 模式名
    MODE_CODES = {'CC': 0.0, 'CV': 1.0, 'CR': 2.0, 'CP': 3.0, 'DYN': 4.0}
    # FUNC 命令参数（SCPI 短格式）
    FUNC_PARAMS = {'CC': 'CURR', 'CV': 'VOLT', 'CR': 'RES', 'CP': 'POW', 'DYN': 'DYN'}
    # 各模式设定值命令
    SETPOINT_CMDS = {'CC': 'CURR', 'CV': 'VOLT', 'CR': 'RES', 'CP': 'POW'}

    def __init__(self, comm=None):
        super().__init__(comm)
        self._setpoints = {}          # 模式 -> 最近一次设定的设定值
        self._dyn_params = None       # 最近一次动态模式参数
        self._verify_retries = 3
        self.last_input_trace = []
        self.last_input_reply = None
        self._command_lock = threading.RLock()
        self._last_command_completed = 0.0

    def send_command(self, command, wait_response=False, timeout=None):
        """Leave processing time between serial commands, including after queries."""
        with self._command_lock:
            gap = .15 - (time.monotonic() - self._last_command_completed)
            if gap > 0:
                time.sleep(gap)
            try:
                return super().send_command(command, wait_response, timeout)
            finally:
                self._last_command_completed = time.monotonic()

    def connect(self) -> bool:
        if self.comm and self.comm.is_connected:
            self.connected = True
            self.set_mode('CR')  # 用户要求：连接后进入 CR 模式
            return True
        return False

    def disconnect(self):
        self.connected = False
        if self.comm:
            self.comm.disconnect()

    def get_idn(self) -> Optional[str]:
        return self.query('*IDN?')

    # ---------- 模式控制 ----------

    def get_mode(self) -> Optional[str]:
        """查询当前工作模式（CC/CV/CR/CP/DYN）"""
        resp = self.query('FUNC?')
        if resp:
            try:
                val = float(resp.strip())
                for name, code in self.MODE_CODES.items():
                    if abs(val - code) < 0.5:
                        return name
            except ValueError:
                pass
        return None

    def set_mode(self, mode: str) -> bool:
        """切换工作模式（带回读验证；已是目标模式则直接返回，不扰动输入状态）。"""
        if mode not in self.FUNC_PARAMS:
            return False
        for _ in range(self._verify_retries):
            if self.get_mode() == mode:
                return True
            # 模式切换要求输入关闭
            self.send_command('INP OFF', wait_response=False)
            time.sleep(0.15)
            self.send_command(f'FUNC {self.FUNC_PARAMS[mode]}', wait_response=False)
            time.sleep(0.5)
        return self.get_mode() == mode

    # ---------- 设定值（设置 + 回读验证） ----------

    def set_current(self, current: float) -> bool:
        """设置 CC 模式电流（自动切换到 CC 模式）"""
        return self._apply_setpoint('CC', current, self.get_current)

    def set_voltage(self, voltage: float) -> bool:
        """设置 CV 模式电压（自动切换到 CV 模式）"""
        return self._apply_setpoint('CV', voltage, self.get_voltage)

    def set_resistance(self, resistance: float) -> bool:
        """设置 CR 模式电阻（自动切换到 CR 模式）"""
        return self._apply_setpoint('CR', resistance, self.get_resistance)

    def set_power(self, power: float) -> bool:
        """设置 CP 模式功率（自动切换到 CP 模式）"""
        return self._apply_setpoint('CP', power, self.get_power)

    def _apply_setpoint(self, mode: str, value: float, getter) -> bool:
        if not self.set_mode(mode):
            return False
        cmd = self.SETPOINT_CMDS[mode]
        tol = max(0.05, abs(value) * 0.005)
        stored = False
        for _ in range(self._verify_retries):
            self.send_command(f'{cmd} {value}', wait_response=False)
            time.sleep(0.15)
            got = getter()
            if got is not None and abs(got - value) <= tol:
                stored = True
                break
        self._setpoints[mode] = value
        if not stored:
            return False
        # 输入开启时，设定值还需「实际生效」而不仅是被存储（模式切换/输入
        # 接通瞬态期发送的设定值可能不生效），用实测电流闭环确认
        if self.get_input_state() is True:
            return self._ensure_applied(mode, value)
        return True

    def _ensure_applied(self, mode: str, value: float) -> bool:
        """闭环确认设定值已在输入端实际生效。

        策略分级：先直接重发（输入已开启且稳定时立即生效）；
        无效（常见于刚发生过模式切换，固件时序敏感）则用
        「关输入→设值→开输入」完整循环强制应用。
        """
        cmd = self.SETPOINT_CMDS[mode]
        for attempt in range(2):
            if self._setpoint_applied(mode, value):
                return True
            self.send_command(f'{cmd} {value}', wait_response=False)
            time.sleep(0.3 + 0.2 * attempt)
        if self._setpoint_applied(mode, value):
            return True
        for _ in range(2):
            self.send_command('INP OFF', wait_response=False)
            time.sleep(0.3)
            self.send_command(f'{cmd} {value}', wait_response=False)
            time.sleep(0.2)
            self.send_command('INP ON', wait_response=False)
            time.sleep(0.4)
            if self._setpoint_applied(mode, value):
                return True
        return self._setpoint_applied(mode, value)

    def _setpoint_applied(self, mode: str, value: float) -> bool:
        """用实测电压/电流判断设定值是否已生效；无法物理判断时返回 True（不阻塞）。"""
        v = self.measure_voltage()
        if v is None or v < 1.0:
            # 输入端无有效电压（DUT 未启动/输出被拉垮），无法物理验证
            return True
        i = self.measure_current()
        if i is None:
            return True
        if mode == 'CR':
            if value <= 0:
                return True
            expected_i = v / value
            return abs(i - expected_i) <= max(0.02, expected_i * 0.1)
        if mode == 'CC':
            return abs(i - value) <= max(0.02, value * 0.1)
        # CV/CP 物理判定依赖工况，回读存储已验证，直接认为生效
        return True

    def _reapply_setpoint(self):
        """输入开启后确认当前模式的设定值已实际生效（闭环物理验证，未生效则重发）。

        仅适用于四个基本模式；DYN 模式参数在输入关闭时设置、开输入时自动生效，
        且输入接通瞬态期重发会打断动态发生器，故跳过。
        """
        mode = self.get_mode()
        if not mode or mode not in self.SETPOINT_CMDS:
            return
        value = self._setpoints.get(mode)
        if value is None:
            return
        time.sleep(0.2)  # 等输入接通稳定
        self._ensure_applied(mode, value)

    # ---------- 输入控制 ----------

    def enable_input(self, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        self.last_input_trace = []
        # Poll a full settling window before resending an unacknowledged command.
        for attempt in range(self._verify_retries):
            self.send_command(f'INP {state}', wait_response=False)
            for poll in range(3):
                time.sleep(0.2 * (poll+1))
                actual = self.get_input_state()
                self.last_input_trace.append({"attempt": attempt+1, "poll": poll+1, "requested": state,
                    "state": actual, "reply": self.last_input_reply,
                    "error": getattr(self.comm, "last_error", "")})
                if actual == enable:
                    if enable:
                        self._reapply_setpoint()
                    return True
            status = self.query('STAT:QUES:COND?')
            self.last_input_trace[-1]["questionable_status"] = status
            # Do not restart a protected load. OFF commands may still be retried.
            if enable and self._to_float(status) not in (None, 0.):
                return False
        return False

    def disable_input(self) -> bool:
        return self.enable_input(False)

    def get_input_state(self) -> Optional[bool]:
        """查询输入状态 True=ON, False=OFF, None=查询失败"""
        resp = self.query('INP?')
        self.last_input_reply = resp
        if resp is None:
            return None
        resp = resp.strip().upper()
        if resp in ('1', 'ON'):
            return True
        if resp in ('0', 'OFF'):
            return False
        if not resp:
            return None
        try:
            return float(resp) > 0
        except ValueError:
            return None

    # ---------- 回读 ----------

    def get_voltage(self) -> Optional[float]:
        """读取设定电压档位（CV 模式设定值），实测电压请用 measure_voltage()"""
        return self._to_float(self.query('VOLT?'))

    def get_current(self) -> Optional[float]:
        """读取设定电流档位（CC 模式设定值），实测电流请用 measure_current()"""
        return self._to_float(self.query('CURR?'))

    def get_resistance(self) -> Optional[float]:
        return self._to_float(self.query('RES?'))

    def get_power(self) -> Optional[float]:
        return self._to_float(self.query('POW?'))

    def measure_voltage(self) -> Optional[float]:
        """读取负载输入端实测电压（DUT 输出电压）"""
        return self._to_float(self.query('MEAS:VOLT?'))

    def measure_current(self) -> Optional[float]:
        """读取负载输入端实测电流（DUT 输出电流）"""
        return self._to_float(self.query('MEAS:CURR?'))

    def measure_power(self) -> Optional[float]:
        """读取负载输入端实测功率"""
        return self._to_float(self.query('MEAS:POW?'))

    @staticmethod
    def _to_float(response) -> Optional[float]:
        if response is None:
            return None
        try:
            return float(str(response).strip())
        except (ValueError, TypeError):
            return None

    # ---------- 动态模式（DYN，电流动态） ----------

    def set_dynamic_params(self, high_current: float, low_current: float,
                           dwell_high_ms: float = 5.0, dwell_low_ms: float = 5.0,
                           mode: str = 'CONT') -> bool:
        """配置动态电流模式参数。

        :param high_current: 高电平拉载电流 (A)
        :param low_current: 低电平拉载电流 (A)
        :param dwell_high_ms: 高电平持续时间 (ms)
        :param dwell_low_ms: 低电平持续时间 (ms)
        :param mode: CONT(连续) | PULS(脉冲) | TOGG(翻转)
        """
        if not self.set_mode('DYN'):
            return False
        ok = self._send_dyn_params(high_current, low_current,
                                   dwell_high_ms, dwell_low_ms, mode)
        if ok:
            self._dyn_params = {
                'high_current': high_current, 'low_current': low_current,
                'dwell_high_ms': dwell_high_ms, 'dwell_low_ms': dwell_low_ms,
                'mode': mode,
            }
        return ok

    def _send_dyn_params(self, high_current: float, low_current: float,
                         dwell_high_ms: float, dwell_low_ms: float, mode: str) -> bool:
        self.send_command(f'DYN:HIGH {high_current}', wait_response=False)
        time.sleep(0.05)
        self.send_command(f'DYN:LOW {low_current}', wait_response=False)
        time.sleep(0.05)
        self.send_command(f'DYN:HIGH:DWEL {dwell_high_ms}', wait_response=False)
        time.sleep(0.05)
        self.send_command(f'DYN:LOW:DWEL {dwell_low_ms}', wait_response=False)
        time.sleep(0.05)
        self.send_command(f'DYN:MODE {mode}', wait_response=False)
        time.sleep(0.1)
        self.send_command('DYN:SLEW:RISE MAX', wait_response=False)
        time.sleep(0.1)
        self.send_command('DYN:SLEW:FALL MAX', wait_response=False)
        time.sleep(0.1)
        # 回读验证高/低电平
        high = self._to_float(self.query('DYN:HIGH?'))
        low = self._to_float(self.query('DYN:LOW?'))
        high_dwell = self._to_float(self.query('DYN:HIGH:DWEL?'))
        low_dwell = self._to_float(self.query('DYN:LOW:DWEL?'))
        return (high is not None and abs(high - high_current) < 0.01
                and low is not None and abs(low - low_current) < 0.01
                and high_dwell is not None and abs(high_dwell - dwell_high_ms) <= max(.01, dwell_high_ms * .001)
                and low_dwell is not None and abs(low_dwell - dwell_low_ms) <= max(.01, dwell_low_ms * .001))

    def start_dynamic(self) -> bool:
        """启动动态拉载。

        DYN 参数须在输入关闭时设置（set_dynamic_params 已保证），
        INP ON 后即按参数连续运行；输入接通瞬态期不可重发参数，否则会打断发生器。
        """
        if not self.set_mode('DYN'):
            return False
        return self.enable_input(True)

    def stop_dynamic(self) -> bool:
        """停止动态拉载"""
        return self.enable_input(False)

    # ---------- 其它 ----------

    def set_remote_sense(self, enable: bool = True) -> bool:
        """远端补偿（手册命令为 SYST:SENS，注意不是 SENS:REM）"""
        state = 'ON' if enable else 'OFF'
        self.send_command(f'SYST:SENS {state}', wait_response=False)
        return True

    def set_short(self, enable: bool = True) -> bool:
        """输入短路（手册命令为 INP:SHOR，需在基本模式下已拉载时生效）"""
        state = 'ON' if enable else 'OFF'
        self.send_command(f'INP:SHOR {state}', wait_response=False)
        return True

    def reset(self) -> bool:
        self.send_command('*RST', wait_response=False)
        self._setpoints.clear()
        self._dyn_params = None
        return True

    def get_status(self) -> Optional[str]:
        return self.query('STAT:OPER:COND?')
