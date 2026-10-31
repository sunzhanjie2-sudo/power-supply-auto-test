from .base_instrument import InstrumentBase
from typing import Optional
import re
import numpy as np
import time
from datetime import datetime

from ..waveforms.model import ChannelSettings, Coupling, TimebaseSettings, TriggerSettings, Waveform
from ..waveforms.record import WaveformRecord


class Oscilloscope(InstrumentBase):
    # DS1152E 实测：USB-TMC 连续快速写入会丢命令，强制设置类命令最小间隔
    _MIN_CMD_INTERVAL = 0.15

    def __init__(self, comm=None):
        super().__init__(comm)
        self._model = None
        self._channels = []
        self._last_cmd_time = 0.0
        self.last_waveform_info = {}
        self.last_record = None
        self.last_record_error = ""
        self._identity = ""

    def _is_ds1000e_family(self) -> bool:
        """DS1000E/DS1000D 系列命令集与 DS1000Z 等差异较大，按型号区分。"""
        return bool(self._model and re.search(r"DS\d{4}[ED]", self._model.upper()))

    def connect(self) -> bool:
        if self.comm and self.comm.is_connected:
            self.connected = True
            idn = self.get_idn()
            if idn:
                self._identity = idn
                self._model = idn.split(',')[1] if ',' in idn else idn
                self._detect_channels()
            return True
        return False

    def disconnect(self):
        self.connected = False
        if self.comm:
            self.comm.disconnect()

    def get_idn(self) -> Optional[str]:
        return self.query('*IDN?')

    def _detect_channels(self):
        # 不存在的通道查询会超时，用短超时探测，首次失败即停止
        for ch in [1, 2, 3, 4]:
            resp = self.send_command(f':CHAN{ch}:DISP?', wait_response=True, timeout=1.0)
            if resp is None:
                break
            self._channels.append(ch)

    def _send(self, command: str) -> bool:
        """发送设置命令（仪器无应答，写入成功即认为生效；是否正确由回读验证）。

        内置最小命令间隔，规避 DS1000E 系列 USB-TMC 连续快速写入丢命令的问题。
        """
        gap = self._MIN_CMD_INTERVAL - (time.time() - self._last_cmd_time)
        if gap > 0:
            time.sleep(gap)
        try:
            self.send_command(command, wait_response=False)
            self._last_cmd_time = time.time()
            return True
        except Exception:
            return False

    def set_channel_enable(self, channel: int, enable: bool = True) -> bool:
        state = 'ON' if enable else 'OFF'
        return self._send(f':CHAN{channel}:DISP {state}')

    def set_channel_scale(self, channel: int, scale: float) -> bool:
        return self._send(f':CHAN{channel}:SCAL {scale}')

    def set_channel_offset(self, channel: int, offset: float) -> bool:
        return self._send(f':CHAN{channel}:OFFS {offset}')

    def get_channel_scale(self, channel: int) -> Optional[float]:
        response = self.query(f':CHAN{channel}:SCAL?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def get_channel_offset(self, channel: int) -> Optional[float]:
        response = self.query(f':CHAN{channel}:OFFS?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def set_timebase_scale(self, scale: float) -> bool:
        return self._send(f':TIM:SCAL {scale}')

    def get_timebase_scale(self) -> Optional[float]:
        response = self.query(':TIM:SCAL?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def set_trigger_mode(self, mode: str) -> bool:
        """设置触发类型；AUTO/SINGLE 为扫描语义，分别映射为 :RUN / :SING。"""
        mode_upper = (mode or "").upper()
        if mode_upper in ('AUTO', 'NORMAL', 'NORM'):
            if self._is_ds1000e_family():
                return self._send(f':TRIG:EDGE:SWE {"AUTO" if mode_upper == "AUTO" else "NORM"}')
            return self._send(':RUN')
        if mode_upper == 'SINGLE':
            return self.single()
        valid_modes = ['EDGE', 'PULSE', 'SLOPE', 'VIDEO', 'PATTERN', 'DURATION', 'ALTERNATION']
        if mode_upper not in valid_modes:
            return False
        return self._send(f':TRIG:MODE {mode_upper}')

    def set_trigger_source(self, source: str) -> bool:
        # DS1000E 触发源挂在边沿触发子树下：:TRIG:EDGE:SOUR（:TRIG:SOUR 不被识别）
        src = str(source).strip().upper()
        if src in ('CH1', '1'):
            src = 'CHAN1'
        elif src in ('CH2', '2'):
            src = 'CHAN2'
        elif src in ('CH3', '3'):
            src = 'CHAN3'
        elif src in ('CH4', '4'):
            src = 'CHAN4'
        return self._send(f':TRIG:EDGE:SOUR {src}')

    def set_trigger_level(self, level: float) -> bool:
        return self._send(f':TRIG:EDGE:LEV {level}')

    def set_trigger_slope(self, slope: str) -> bool:
        """设置边沿触发斜率（RISING/FALLING），下电波形捕获需要 FALLING。"""
        s = str(slope).strip().upper()
        if s in ('RISING', 'FALLING'):
            if self._is_ds1000e_family():
                s = 'POS' if s == 'RISING' else 'NEG'
            return self._send(f':TRIG:EDGE:SLOP {s}')
        return False

    def get_trigger_level(self) -> Optional[float]:
        response = self.query(':TRIG:EDGE:LEV?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def set_acquisition_mode(self, mode: str) -> bool:
        """设置采集类型。

        DS1000E 系列命令为 :ACQ:TYPE NORM|AVER|PEAK|HRES（注意不是 :ACQ:MODE）。
        """
        valid_modes = ['NORM', 'PEAK', 'HRES', 'AVER']
        mode_upper = (mode or "").upper()
        if mode_upper not in valid_modes:
            return False
        return self._send(f':ACQ:TYPE {mode_upper}')

    def get_acquisition_mode(self) -> Optional[str]:
        response = self.query(':ACQ:TYPE?')
        if response:
            resp = response.strip().upper()
            for m in ('NORM', 'AVER', 'PEAK', 'HRES'):
                if m in resp:
                    return m
        return None

    def set_sample_rate(self, rate: float) -> bool:
        return self._send(f':ACQ:SRAT {rate}')

    def get_sample_rate(self) -> Optional[float]:
        response = self.query(':ACQ:SRAT?')
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def set_bandwidth(self, channel: int, bandwidth: str) -> bool:
        # DS1000E 为 :CHANn:BWL {ON|OFF}（20MHz 带宽限制开关，"20M" 对应 ON）
        bw = str(bandwidth).strip().upper()
        if bw in ('20M', '20MHZ', 'ON'):
            bw = 'ON'
        elif bw in ('FULL', 'OFF', ''):
            bw = 'OFF'
        return self._send(f':CHAN{channel}:BWL {bw}')

    def set_coupling(self, channel: int, coupling: str) -> bool:
        valid_coupling = ['AC', 'DC', 'GND']
        if coupling not in valid_coupling:
            return False
        return self._send(f':CHAN{channel}:COUP {coupling}')

    def set_probe_ratio(self, channel: int, ratio: float) -> bool:
        return self._send(f':CHAN{channel}:PROB {ratio}')

    def apply_config(self, config: dict) -> bool:
        """按结构化配置一键设置示波器（电压档位/耦合/时基/触发/采集/带宽）。

        config 字段（可选）：
          channel(int), voltage_scale(float,V/div), coupling(str:AC/DC),
          timebase(float,s/div), trigger_source(str), trigger_level(float),
          trigger_mode(str:EDGE/AUTO/SINGLE...), acq_mode(str:NORM/PEAK/AVER/HRES),
          bandwidth(str:FULL/20M), probe_ratio(float)
        """
        if not config:
            return False
        ch = int(config.get("channel", 1))
        ok = True
        try:
            if config.get("voltage_scale"):
                ok &= self.set_channel_scale(ch, float(config["voltage_scale"]))
            if config.get("offset") is not None:
                ok &= self.set_channel_offset(ch, float(config["offset"]))
            if config.get("coupling"):
                ok &= self.set_coupling(ch, str(config["coupling"]))
            if config.get("timebase"):
                ok &= self.set_timebase_scale(float(config["timebase"]))
            if config.get("trigger_mode"):
                ok &= self.set_trigger_mode(str(config["trigger_mode"]))
            if config.get("trigger_source"):
                ok &= self.set_trigger_source(str(config["trigger_source"]))
            if config.get("trigger_level") is not None:
                ok &= self.set_trigger_level(float(config["trigger_level"]))
            if config.get("acq_mode"):
                ok &= self.set_acquisition_mode(str(config["acq_mode"]))
            if config.get("bandwidth"):
                ok &= self.set_bandwidth(ch, str(config["bandwidth"]))
            if config.get("probe_ratio"):
                ok &= self.set_probe_ratio(ch, float(config["probe_ratio"]))
        except Exception:
            return False
        return ok

    def get_waveform_data(self, channel: int = 1) -> Optional[np.ndarray]:
        """读取指定通道的波形原始数据（8bit ADC 计数值）。

        DS1000E 系列仅支持 :WAV:POIN:MODE 与 :WAV:DATA? [source] 两条波形命令
        （不支持 :WAV:SOUR/:WAV:FORM/:WAV:MODE），NORM 模式下 CHx 返回 600 点。
        USB-TMC / VISA 通道使用二进制读取，正确处理 IEEE488.2 块头；
        串口等无二进制能力的通道回退为字符串解析。
        """
        self._send(':WAV:POIN:MODE NORM')
        time.sleep(0.05)

        # 优先二进制读取
        query_binary = getattr(self.comm, 'query_binary', None) if self.comm else None
        if callable(query_binary):
            raw = query_binary(f':WAV:DATA? CHAN{channel}')
            if raw:
                return np.frombuffer(raw, dtype=np.uint8).astype(np.float64)
            return None

        # 回退：字符串读取
        response = self.query(f':WAV:DATA? CHAN{channel}')
        if response:
            try:
                if response.startswith('#'):
                    header_len = int(response[1]) + 2
                    raw_data = response[header_len:]
                else:
                    raw_data = response
                return np.array([ord(c) for c in raw_data], dtype=np.float64)
            except (ValueError, IndexError):
                return None
        return None

    def get_waveform_data_volts(self, channel: int = 1) -> Optional[np.ndarray]:
        """读取波形并转换为电压值 (V)。

        DS1000E 的波形字节随正向电压升高而减小，约 25 码/格。
        使用示波器自身的平均值锚定直流电平，避免显示偏置造成误读。
        """
        self.last_record = None
        self.last_record_error = ""
        self.last_waveform_info = {}
        resume = False
        if self.comm and self.connected:
            resume = self.get_trigger_status() != "STOP"
            self.stop()
            time.sleep(0.15)
        try:
            volts = self._read_volts(channel)
            if volts is not None and self.comm and self.connected:
                try:
                    self.last_record = self._snapshot_record(channel, volts)
                except Exception as exc:
                    self.last_record_error = str(exc)
            return volts
        finally:
            if resume:
                self.run()

    def _read_volts(self, channel):
        raw = self.get_waveform_data(channel)
        if raw is None or len(raw) == 0:
            return None
        self._last_raw = raw.copy()
        scale = self.get_channel_scale(channel)
        if scale is None or scale <= 0:
            scale = 1.0
        if self._is_ds1000e_family():
            offset = self.get_channel_offset(channel)
            if offset is None:
                return None
            volts = (125.0 - raw) * (scale / 25.0) - offset
            self.last_waveform_info = {"scale": scale, "offset": offset,
                                       "raw_min": float(np.min(raw)), "raw_max": float(np.max(raw)),
                                       "scope_vmin": self.get_measurement('VMIN', f'CHAN{channel}'),
                                       "scope_vmax": self.get_measurement('VMAX', f'CHAN{channel}'),
                                       "scope_vpp": self.get_measurement('VPP', f'CHAN{channel}')}
            # Anchor to the same frozen acquisition's measured average, only for
            # a steady waveform. Transition records must keep their zero level.
            if np.ptp(volts) < 2 * scale:
                average = self.get_measurement('VAV', f'CHAN{channel}')
                if average is not None and np.isfinite(average) and abs(average) < 1e10:
                    correction = average - float(np.mean(volts))
                    self.last_waveform_info["dc_anchor_shift"] = correction
                    volts += correction
            return volts
        volts_per_count = scale * 8.0 / 256.0
        return (raw - 128.0) * volts_per_count

    def get_waveform_capture(self, channel: int = 1) -> WaveformRecord:
        """Capture data and all display settings while the same acquisition is stopped."""
        values = self.get_waveform_data_volts(channel)
        if values is None or self.last_record is None:
            raise RuntimeError(self.last_record_error or "未读到完整波形记录")
        return self.last_record

    def _snapshot_record(self, channel, volts):
        def number(command, default=None):
            response = self.query(command)
            try:
                value = float(response)
                return value if np.isfinite(value) else default
            except (TypeError, ValueError):
                return default

        scale = self.last_waveform_info.get("scale") or self.get_channel_scale(channel)
        offset = self.last_waveform_info.get("offset")
        if offset is None:
            offset = self.get_channel_offset(channel)
        timebase = self.get_timebase_scale()
        position = number(':TIM:OFFS?')
        coupling = (self.query(f':CHAN{channel}:COUP?') or '').strip().upper()
        if not scale or offset is None or not timebase or position is None or coupling not in ('AC', 'DC', 'GND'):
            raise ValueError("同帧波形的量程、偏移、耦合或时间轴回读不完整")
        name = f"CH{channel}"
        divisions = 12 if self._is_ds1000e_family() else 10
        interval = timebase * divisions / len(volts)
        source = (self.query(':TRIG:EDGE:SOUR?') or name).strip().upper().replace('CHAN', 'CH')
        slope = (self.query(':TRIG:EDGE:SLOP?') or '').strip().upper()
        sweep = (self.query(':TRIG:EDGE:SWE?') or '').strip().upper()
        trigger = TriggerSettings(source=source, level=number(':TRIG:EDGE:LEV?', 0.),
                                  slope='FALL' if slope in ('NEG', 'FALL', 'FALLING') else 'RISE', mode=sweep)
        channel_settings = ChannelSettings(number=channel, scale=float(scale), offset=float(offset),
                                            coupling=Coupling(coupling), offset_polarity=1)
        tb = TimebaseSettings(scale=float(timebase), position=position, sample_rate=1/interval,
                              record_length=len(volts), horizontal_divisions=divisions)
        wf = Waveform(name, volts.copy(), position-divisions*timebase/2, interval,
                      raw=self._last_raw.astype(np.uint8), source_encoding="BYTE",
                      decode_note="DS1000E documented conversion; steady frames anchored to frozen VAV" if self._is_ds1000e_family() else "legacy conversion")
        info = {**self.last_waveform_info, "timebase": timebase, "time_offset": position,
                "coupling": coupling, "probe_ratio": number(f':CHAN{channel}:PROB?'),
                "bandwidth": (self.query(f':CHAN{channel}:BWL?') or '').strip(),
                "sample_interval": interval, "points": len(volts),
                "captured_at": datetime.now().isoformat(timespec='milliseconds')}
        self.last_waveform_info = info
        return WaveformRecord({name: wf}, {"channels": {name: channel_settings}, "timebase": tb,
                               "trigger": trigger}, self._identity, {"scope": info}).validate()

    def get_waveform_preamble(self) -> Optional[dict]:
        """获取波形前导参数。

        DS1000E/DS1000D 系列不支持 :WAV:PRE?，改由时基与垂直档位推导：
        屏幕横向 12 格 / 600 点（NORM），纵向约 25 码/格。
        其它型号先尝试 :WAV:PRE?，失败后再推导。
        """
        if not self._is_ds1000e_family():
            response = self.query(':WAV:PRE?', timeout=2.0)
            if response:
                try:
                    parts = response.split(',')
                    if len(parts) >= 10:
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
                    pass

        timebase = self.get_timebase_scale()
        scale = self.get_channel_scale(1)
        if timebase is None or timebase <= 0:
            return None
        points = 600
        return {
            'format': 0,          # BYTE
            'type': 0,            # NORM
            'points': points,
            'count': 1,
            'xincrement': timebase * 12.0 / points,
            'xorigin': 0.0,
            'xreference': 0.0,
            'yincrement': -(scale or 1.0) / 25.0,
            'yorigin': 0.0,
            'yreference': 128.0
        }

    def save_waveform(self, filename: str, channel: int = 1) -> bool:
        return self._send(f':SAVE:WAV {filename}')

    def run(self) -> bool:
        if self._is_ds1000e_family():
            self._send(':TRIG:EDGE:SWE AUTO')
        return self._send(':RUN')

    def stop(self) -> bool:
        return self._send(':STOP')

    def single(self) -> bool:
        if self._is_ds1000e_family():
            # DS1000E has no :SING command. Arm its edge single sweep explicitly.
            return self._send(':TRIG:EDGE:SWE SINGLE') and self._send(':RUN')
        return self._send(':SING')

    def get_trigger_status(self) -> Optional[str]:
        response = self.query(':TRIG:STAT?')
        return response.strip().upper() if response else None

    def wait_for_single(self, timeout=5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_trigger_status() == 'STOP':
                return True
            time.sleep(0.1)
        return False

    def reset(self) -> bool:
        return self._send('*RST')

    def clear(self) -> bool:
        return self._send('*CLS')

    def wait(self) -> bool:
        # *WAI 无应答，写入成功即可
        return self._send('*WAI')

    def get_status(self) -> Optional[str]:
        return self.query('*STB?')

    def auto_setup(self) -> bool:
        return self._send(':AUT')

    def set_measurement(self, measurement: str, source: str) -> bool:
        return self._send(f':MEAS:{measurement} {source}')

    def get_measurement(self, measurement: str, source: str = '') -> Optional[float]:
        cmd = f':MEAS:{measurement}? {source}' if source else f':MEAS:{measurement}?'
        response = self.query(cmd)
        if response:
            try:
                return float(response.strip())
            except ValueError:
                return None
        return None

    def auto_configure_for_component(self, component) -> bool:
        if not component:
            return False
        ch = component.scope_channel
        self.set_channel_enable(ch, True)
        self.set_channel_scale(ch, component.voltage_scale)
        self.set_channel_offset(ch, component.dc_offset)
        self.set_timebase_scale(component.timebase_scale)
        self.set_trigger_source(component.trigger_source)
        self.set_trigger_level(component.trigger_level)
        if component.bandwidth:
            self.set_bandwidth(ch, component.bandwidth)
        if component.sample_rate:
            self.set_sample_rate(component.sample_rate)
        return True

    def get_screenshot(self) -> Optional[bytes]:
        # DS1000E/DS1000D 系列不支持 :DISP:DATA? 屏幕抓取，直接跳过避免长超时
        if self._is_ds1000e_family():
            return None
        try:
            response = self.query(':DISP:DATA? ON,OFF,PNG', timeout=6.0)
        except Exception:
            return None
        if response:
            try:
                match = re.search(rb'(\x89PNG.*)', response.encode('latin-1'))
                if match:
                    return match.group(1)
            except Exception:
                pass
        return None

    def auto_configure_for_test(self, test_item: str, voltage_rating: float, switching_freq: float) -> dict:
        """
        根据测试项自动配置示波器参数
        :param test_item: 测试项名称
        :param voltage_rating: 器件耐压等级
        :param switching_freq: 开关频率
        :return: 配置结果字典
        """
        result = {
            'vertical_range': [],
            'attenuation': [],
            'time_base': 0.0,
            'trigger_source': 'CHAN1',
            'trigger_level': 0.0,
            'success': True
        }

        vertical_range = voltage_rating / 8.0
        standard_ranges = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                           1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
        selected_range = min(standard_ranges, key=lambda x: abs(x - vertical_range))
        if vertical_range > max(standard_ranges):
            selected_range = max(standard_ranges)

        if voltage_rating <= 50:
            attenuation = 1
        else:
            attenuation = 10

        time_base = 1.0 / switching_freq
        standard_timebases = [0.00000001, 0.00000002, 0.00000005, 0.0000001, 0.0000002,
                              0.0000005, 0.000001, 0.000002, 0.000005, 0.00001,
                              0.00002, 0.00005, 0.0001, 0.0002, 0.0005, 0.001,
                              0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
        selected_timebase = min(standard_timebases, key=lambda x: abs(x - time_base))

        for ch in range(1, 3):
            self.set_channel_enable(ch, True)
            self.set_channel_scale(ch, selected_range)
            self.set_probe_ratio(ch, attenuation)
            result['vertical_range'].append(selected_range)
            result['attenuation'].append(attenuation)

        self.set_timebase_scale(selected_timebase)
        self.set_trigger_source('CHAN1')
        self.set_trigger_level(voltage_rating * 0.5)
        self.run()

        result['time_base'] = selected_timebase
        return result
