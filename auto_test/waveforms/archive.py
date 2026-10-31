"""无 pickle 的压缩波形归档：精确采样值 + JSON 元数据，用于离线分析。"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import zipfile
import numpy as np
from .model import ChannelSettings, Coupling, TimebaseSettings, TriggerSettings, Waveform


def save_archive(path: str | Path, waveforms: dict[str, Waveform], settings: dict,
                 identity: str = "", processing: dict | None = None,
                 context: dict | None = None) -> str:
    if not waveforms:
        raise ValueError("当前没有可保存的波形")
    metadata = {
        "format": "ScopeHost", "version": 1,
        "created": datetime.now(timezone.utc).isoformat(), "identity": identity,
        "channels": {k: asdict(v) for k, v in settings.get("channels", {}).items()},
        "timebase": asdict(settings.get("timebase", TimebaseSettings())),
        "trigger": asdict(settings.get("trigger", TriggerSettings())),
        "processing": processing or {}, "waveforms": {}, "test_context": context or {},
    }
    arrays = {}
    for i, (name, wf) in enumerate(waveforms.items()):
        key = f"wave_{i}"
        arrays[key] = wf.y
        metadata["waveforms"][name] = {"key": key, "x_start": wf.x_start,
            "x_incr": wf.x_incr, "encoding": wf.source_encoding, "note": wf.decode_note}
        if wf.raw is not None:
            raw_key = f"raw_{i}"
            arrays[raw_key] = wf.raw
            metadata["waveforms"][name]["raw_key"] = raw_key
    arrays["metadata"] = np.array(json.dumps(metadata, ensure_ascii=False))
    path = Path(path).with_suffix(".npz")
    with path.open("wb") as out:
        np.savez_compressed(out, **arrays)
    return str(path)


def load_archive(path: str | Path) -> tuple[dict[str, Waveform], dict, dict]:
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("波形归档解压后超过 512 MB")
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["metadata"].item()))
        if meta.get("format") != "ScopeHost" or meta.get("version") != 1:
            raise ValueError("不支持的波形归档格式")
        waveforms = {}
        for name, info in meta["waveforms"].items():
            y = np.asarray(data[info["key"]], dtype=np.float64)
            x_start, x_incr = float(info["x_start"]), float(info["x_incr"])
            if y.ndim != 1 or y.size < 2 or not np.all(np.isfinite(y)):
                raise ValueError(f"{name} 采样数据无效")
            if not np.isfinite(x_start) or not np.isfinite(x_incr) or x_incr <= 0:
                raise ValueError(f"{name} 时间轴无效")
            waveforms[name] = Waveform(name, y.copy(), x_start, x_incr,
                raw=data[info["raw_key"]].copy() if "raw_key" in info else None,
                source_encoding=info.get("encoding", ""), decode_note=info.get("note", ""))
        if not waveforms:
            raise ValueError("归档没有波形")
    channels = {}
    for name, info in meta["channels"].items():
        info = dict(info)
        info["coupling"] = Coupling(info.get("coupling", "DC"))
        if not np.isfinite(info["scale"]) or info["scale"] <= 0 or not np.isfinite(info["offset"]):
            raise ValueError("通道量程或偏移无效")
        channels[name] = ChannelSettings(**info)
    tb = TimebaseSettings(**meta["timebase"])
    if not np.isfinite(tb.scale) or tb.scale <= 0 or not np.isfinite(tb.position):
        raise ValueError("时基设置无效")
    settings = {"channels": channels, "timebase": tb,
                "trigger": TriggerSettings(**meta["trigger"])}
    return waveforms, settings, meta
