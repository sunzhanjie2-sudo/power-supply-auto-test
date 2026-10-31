"""A frozen waveform and its settings, shared by reporting and offline playback."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import csv
import json

import numpy as np

from .archive import load_archive, save_archive
from .model import ChannelSettings, Coupling, TimebaseSettings, TriggerSettings, Waveform
from .screen_render import png_bytes, render_annotated_screen


@dataclass
class WaveformRecord:
    waveforms: dict[str, Waveform]
    settings: dict
    identity: str = ""
    context: dict = field(default_factory=dict)

    def validate(self):
        if not self.waveforms:
            raise ValueError("记录没有波形")
        tb = self.settings["timebase"]
        if not np.isfinite(tb.scale) or tb.scale <= 0:
            raise ValueError("波形时基无效")
        for name, wf in self.waveforms.items():
            ch = self.settings["channels"][name]
            if (wf.y.ndim != 1 or wf.points < 2 or not np.all(np.isfinite(wf.y)) or
                    not np.isfinite(wf.x_start) or not np.isfinite(wf.x_incr) or wf.x_incr <= 0 or
                    not np.isfinite(ch.scale) or ch.scale <= 0 or not np.isfinite(ch.offset)):
                raise ValueError(f"{name} 波形或量程无效")
        return self

    def save(self, stem, context=None):
        self.validate()
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        details = {**self.context, **(context or {})}
        def extension(suffix):
            return Path(str(stem) + suffix)
        npz = save_archive(extension(".npz"), self.waveforms, self.settings,
                           self.identity, context=details)
        name, wf = next(iter(self.waveforms.items()))
        csv_path = extension(".csv")
        # Keep the original column names for existing analysis scripts.
        np.savetxt(csv_path, np.column_stack((np.arange(wf.points), wf.x, wf.y)),
                   delimiter=",", header="Index,Time_s,Voltage_V", comments="", fmt="%.17g")
        image = render_annotated_screen(self.waveforms, self.settings["channels"],
                                        self.settings["timebase"], width=1000, height=500)
        png = extension(".png")
        png.write_bytes(png_bytes(image))
        metadata = {"format": "AutoTestWaveform", "version": 1, "identity": self.identity,
                    "channels": {k: asdict(v) for k, v in self.settings["channels"].items()},
                    "timebase": asdict(self.settings["timebase"]),
                    "trigger": asdict(self.settings["trigger"]), "context": details,
                    "npz": Path(npz).name, "sample_count": wf.points}
        extension(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"csv": str(csv_path), "png": str(png), "npz": str(npz)}

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.suffix.lower() != ".csv":
            waveforms, settings, meta = load_archive(path)
            context = dict(meta.get("test_context", {}))
            if path.with_suffix(".json").is_file():
                extra = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
                context.update({key: extra[key] for key in ('result', 'task') if key in extra})
            return cls(waveforms, settings, meta.get("identity", ""), context).validate()
        # Prefer the complete snapshot when a CSV has its matching archive.
        if path.with_suffix(".npz").is_file():
            return cls.load(path.with_suffix(".npz"))
        with path.open(encoding="utf-8-sig", newline="") as source:
            rows = csv.DictReader(source)
            names = rows.fieldnames or []
            if "Time_s" not in names:
                raise ValueError("此旧 CSV 没有时间轴，请选择记录了 Time_s 的 CSV 或 NPZ")
            voltage = "Voltage_V" if "Voltage_V" in names else next(
                (name for name in names if name.endswith("_V")), None)
            if voltage is None:
                raise ValueError("CSV 缺少电压列")
            values = [(float(row["Time_s"]), float(row[voltage])) for row in rows]
        data = np.asarray(values)
        if data.ndim != 2 or data.shape[0] < 2 or not np.all(np.isfinite(data)):
            raise ValueError("CSV 波形数据无效")
        dx = float(np.median(np.diff(data[:, 0])))
        if dx <= 0 or not np.allclose(np.diff(data[:, 0]), dx, rtol=1e-5, atol=dx*1e-6):
            raise ValueError("CSV 时间轴必须等间隔递增")
        meta = {}
        if path.with_suffix(".json").is_file():
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        scope = meta.get("scope", meta.get("result", {}).get("scope", {}))
        span = max(float(np.ptp(data[:, 1])), abs(float(np.mean(data[:, 1])))*.02, .001)
        scale = float(scope.get("scale", span / 6))
        center = float((np.max(data[:, 1]) + np.min(data[:, 1])) / 2)
        offset = float(scope.get("offset", -center))
        tb = TimebaseSettings(scale=dx * len(data) / 12, position=float(data[0, 0] + dx*len(data)/2),
                              sample_rate=1/dx, record_length=len(data), horizontal_divisions=12)
        wf = Waveform("CH1", data[:, 1].copy(), float(data[0, 0]), dx,
                      decode_note="历史 CSV；缺失设置按数据范围显示")
        ch = ChannelSettings(number=1, scale=scale, offset=offset, offset_polarity=1)
        return cls({"CH1": wf}, {"channels": {"CH1": ch}, "timebase": tb,
                   "trigger": TriggerSettings()}, "历史 CSV", meta).validate()
