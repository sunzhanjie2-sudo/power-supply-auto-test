import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


def _coerce_enum(enum_cls, value, default):
    """将字符串/枚举值安全转换为枚举成员，失败时返回默认值。"""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


class TopologyType(Enum):
    BUCK = "Buck"
    SINGLE_FLYBACK = "单路反激"
    FLYBACK_2OUT = "2路反激"
    FLYBACK_3OUT = "3路反激"
    FLYBACK_4OUT = "4路反激"
    FLYBACK_5OUT = "5路反激"


class OutputType(Enum):
    SINGLE = "1路输出"
    DUAL = "2路输出"
    TRIPLE = "3路输出"
    QUAD = "4路输出"
    QUINT = "5路输出"
    HEXA = "6路输出"
    SEPTA = "7路输出"


@dataclass
class OutputChannelConfig:
    channel_name: str = "CH1"
    nominal_voltage: float = 12.0  # Vout_typ（典型输出电压）
    nominal_current: float = 2.5
    # —— 黑盒测试用例扩展字段（多路输出规格）——
    vout_min: float = 0.0   # 输出电压下限（0=未设置，按 ±5% 推导）
    vout_max: float = 0.0   # 输出电压上限
    pout_min: float = 1.2   # 输出功率下限(W)
    pout_typ: float = 15.0  # 输出功率典型值(W)
    pout_max: float = 30.0  # 输出功率上限(W)
    ripple_percent: float = 3.0  # 纹波（占 Vout_typ 的百分比）
    iout_min: float = 0.1
    iout_half: float = 1.25
    iout_rated: float = 2.5
    iout_max: float = 2.5

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutputChannelConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    # —— 规格推导辅助 ——
    def get_vout_min(self) -> float:
        return self.vout_min if self.vout_min else self.nominal_voltage * 0.95

    def get_vout_max(self) -> float:
        return self.vout_max if self.vout_max else self.nominal_voltage * 1.05

    def get_ripple(self) -> float:
        """纹波判据（V），默认 Vout_typ × ripple_percent%"""
        return self.ripple_percent / 100.0 * self.nominal_voltage

    def get_iout_min(self) -> float:
        """轻载电流 = Pout_min / Vout_typ"""
        if self.pout_min:
            return self.pout_min / self.nominal_voltage
        return self.iout_min

    def get_iout_typ(self) -> float:
        """典型载电流 = Pout_typ / Vout_typ"""
        if self.pout_typ:
            return self.pout_typ / self.nominal_voltage
        return self.iout_rated

    def get_iout_max(self) -> float:
        """满载电流 = Pout_max / Vout_typ"""
        if self.pout_max:
            return self.pout_max / self.nominal_voltage
        return self.iout_max


@dataclass
class BoundaryParams:
    vin_list: list = field(default_factory=lambda: [36.0, 42.0, 48.0])
    vin_min: float = 36.0
    vin_rated: float = 42.0
    vin_max: float = 48.0
    temp_list: list = field(default_factory=lambda: [25.0])
    temp_min: float = 25.0
    temp_rated: float = 25.0
    temp_max: float = 25.0
    iout_configs: dict = field(default_factory=dict)
    iout_min: float = 0.1
    iout_half: float = 1.25
    iout_rated: float = 2.5
    iout_max: float = 2.5
    switch_freq: float = 100e3  # 开关频率 (Hz)

    def get_iout_list(self, channel: str = "CH1", iout_min: float = None, iout_max: float = None) -> list:
        if iout_min is not None and iout_max is not None:
            # 使用通道级参数
            half = (iout_min + iout_max) / 2
            return [iout_min, half, iout_max * 0.85, iout_max]
        if channel in self.iout_configs:
            cfg = self.iout_configs[channel]
            return [cfg.get("min", self.iout_min), cfg.get("half", self.iout_half),
                    cfg.get("rated", self.iout_rated), cfg.get("max", self.iout_max)]
        return [self.iout_min, self.iout_half, self.iout_rated, self.iout_max]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BoundaryParams":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ComponentProfile:
    ref_des: str = ""
    device_name: str = ""
    device_type: str = "MOSFET"
    stress_types: list = field(default_factory=list)
    scope_channel: int = 1
    sample_rate: float = 1e9
    timebase_scale: float = 1e-6
    voltage_scale: float = 1.0
    trigger_source: str = "CH1"
    trigger_edge: str = "RISING"
    trigger_level: float = 0.5
    bandwidth: str = "FULL"
    dc_offset: float = 0.0
    voltage_rating: float = 100.0  # 器件耐压 (V)
    stress_criteria: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ComponentProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CriteriaSpec:
    upper_limit: float = 0.0
    lower_limit: float = 0.0
    nominal_value: float = 0.0
    unit: str = "V"
    overshoot_limit: float = 0.0
    undershoot_limit: float = 0.0

    def check(self, value: float) -> tuple:
        """返回 (pass: bool, deviation: float)

        当上下限未配置（均为 0）时，不做范围判定，仅返回偏差。
        """
        deviation = value - self.nominal_value
        if self.lower_limit == 0 and self.upper_limit == 0:
            return True, deviation
        if self.lower_limit <= value <= self.upper_limit:
            return True, deviation
        return False, deviation

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CriteriaSpec":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TestItemConfig:
    name: str = ""
    test_type: str = "black_box"
    channel: str = "CH1"
    criteria: CriteriaSpec = field(default_factory=CriteriaSpec)
    enabled: bool = True

    def __post_init__(self):
        # 兼容旧工程文件/GUI 中 criteria 以 dict 形式出现的情况
        if isinstance(self.criteria, dict):
            self.criteria = CriteriaSpec.from_dict(self.criteria)
        elif self.criteria is None:
            self.criteria = CriteriaSpec()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TestItemConfig":
        kwargs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        criteria = kwargs.get("criteria")
        if isinstance(criteria, dict):
            kwargs["criteria"] = CriteriaSpec.from_dict(criteria)
        return cls(**kwargs)


@dataclass
class ProjectConfig:
    model_name: str = "新样机"
    output_type: OutputType = OutputType.SINGLE
    sn: str = ""
    version: str = "V1.0"
    tester: str = ""
    test_date: str = ""
    output_channels: list = field(default_factory=lambda: [OutputChannelConfig()])
    boundary: BoundaryParams = field(default_factory=BoundaryParams)
    components: list = field(default_factory=list)
    test_items: list = field(default_factory=list)
    output_root: str = ""

    def to_dict(self) -> dict:
        d = {
            "model_name": self.model_name,
            "output_type": self.output_type.value,
            "sn": self.sn,
            "version": self.version,
            "tester": self.tester,
            "test_date": self.test_date,
            "output_channels": [ch.to_dict() for ch in self.output_channels],
            "boundary": self.boundary.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "test_items": [t.to_dict() for t in self.test_items],
            "output_root": self.output_root,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        cfg = cls()
        cfg.model_name = d.get("model_name", "新样机")
        cfg.output_type = _coerce_enum(OutputType, d.get("output_type"), OutputType.SINGLE)
        cfg.sn = d.get("sn", "")
        cfg.version = d.get("version", "V1.0")
        cfg.tester = d.get("tester", "")
        cfg.test_date = d.get("test_date", "")
        cfg.output_channels = [OutputChannelConfig.from_dict(c) for c in d.get("output_channels", [])]
        cfg.boundary = BoundaryParams.from_dict(d.get("boundary", {}))
        cfg.components = [ComponentProfile.from_dict(c) for c in d.get("components", [])]
        cfg.test_items = [TestItemConfig.from_dict(t) for t in d.get("test_items", [])]
        cfg.output_root = d.get("output_root", "")
        return cfg

    def save(self, filepath: str):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "ProjectConfig":
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
