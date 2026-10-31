import os
import csv
import json
from datetime import datetime
import numpy as np


class WaveformArchiver:
    """波形文件归档器 - 按规范树形目录结构保存"""

    def __init__(self, output_root: str):
        self.output_root = output_root
        self._ensure_root()

    def _ensure_root(self):
        if self.output_root:
            os.makedirs(self.output_root, exist_ok=True)

    def get_waveform_path(self, test_type: str, test_item: str, component_ref: str = "") -> str:
        """获取波形文件归档目录"""
        if test_type == "black_box":
            path = os.path.join(self.output_root, "黑盒测试", test_item)
        else:
            # 白盒按器件位号分类
            ref = component_ref or "default"
            path = os.path.join(self.output_root, "白盒测试", ref)
        os.makedirs(path, exist_ok=True)
        return path

    def build_filename(self, test_type: str, test_item: str, vin: float, temp: float,
                       iout: float, channel: str, component_ref: str = "",
                       suffix: str = ".csv") -> str:
        """构建标准化文件名: 工况信息_测试项_器件位号_时间戳"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        temp_str = f"{temp:.0f}C" if temp == 25.0 else f"{temp:.0f}C"

        parts = [channel, f"Vin{vin:g}V", f"T{temp:g}C", f"Iout{iout:g}A", test_item]

        if component_ref:
            parts.append(component_ref)

        parts.append(timestamp)
        return "_".join(parts) + suffix

    def save_waveform_csv(self, data: np.ndarray, test_type: str, test_item: str,
                          vin: float, temp: float, iout: float, channel: str,
                          component_ref: str = "", sample_interval: float = None) -> str:
        """保存波形CSV数据文件"""
        if data is None or len(data) == 0:
            return ""

        dir_path = self.get_waveform_path(test_type, test_item, component_ref)
        filename = self.build_filename(test_type, test_item, vin, temp, iout,
                                       channel, component_ref, ".csv")
        filepath = os.path.join(dir_path, filename)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Index", "Time_s", "Voltage_V"] if sample_interval else ["Index", "Value"])
            for i, val in enumerate(data):
                writer.writerow([i, (i - len(data) / 2) * sample_interval, float(val)] if sample_interval else [i, float(val)])

        return filepath

    def save_capture(self, record, test_type, test_item, vin, temp, iout, channel,
                     context=None):
        """Save PNG/CSV/ScopeHost NPZ from one frozen record; no instrument I/O."""
        from pathlib import Path
        directory = Path(self.get_waveform_path(test_type, test_item))
        filename = self.build_filename(test_type, test_item, vin, temp, iout, channel)
        return record.save(directory / Path(filename).stem, context=context)

    def save_waveform_png(self, png_data: bytes, test_type: str, test_item: str,
                          vin: float, temp: float, iout: float, channel: str,
                          component_ref: str = "") -> str:
        """保存波形PNG截图"""
        if not png_data:
            return ""

        dir_path = self.get_waveform_path(test_type, test_item, component_ref)
        filename = self.build_filename(test_type, test_item, vin, temp, iout,
                                       channel, component_ref, ".png")
        filepath = os.path.join(dir_path, filename)

        with open(filepath, "wb") as f:
            f.write(png_data)

        return filepath

    def save_metadata(self, result, test_type: str, test_item: str,
                      filepath: str) -> str:
        """保存测试元数据JSON"""
        json_path = filepath.replace(".csv", ".json").replace(".png", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        return json_path

    @staticmethod
    def save_waveform_png_from_csv(csv_path: str, title: str = "") -> str:
        """将波形 CSV 绘制为 PNG 图（matplotlib），返回 PNG 路径；失败返回 ""。"""
        if not csv_path or not os.path.exists(csv_path):
            return ""
        try:
            # 必须在导入 matplotlib 前设置配置目录（避免写用户目录被拒）
            from ..runtime import user_data_directory
            _cfg_dir = str(user_data_directory() / "matplotlib")
            os.environ.setdefault("MPLCONFIGDIR", _cfg_dir)
            os.makedirs(_cfg_dir, exist_ok=True)
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False

            xs, ys = [], []
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                timed = "Time_s" in header
                for row in reader:
                    if len(row) >= 2:
                        try:
                            xs.append(float(row[1]) if timed else int(row[0]))
                            ys.append(float(row[2]) if timed else float(row[1]))
                        except ValueError:
                            continue
            if not ys:
                return ""

            png_path = os.path.splitext(csv_path)[0] + ".png"
            fig, ax = plt.subplots(figsize=(9.5, 3.2))
            ax.plot(xs, ys, lw=0.7, color="#1f77b4")
            ax.set_xlabel("Time (s)" if timed else "Sample Index")
            ax.set_ylabel("Voltage (V)")
            ax.set_title(title or os.path.basename(csv_path))
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(png_path, dpi=110)
            plt.close(fig)
            return png_path
        except Exception:
            return ""

    def get_relative_path(self, absolute_path: str) -> str:
        """获取相对于输出根目录的路径"""
        if not self.output_root:
            return absolute_path
        try:
            return os.path.relpath(absolute_path, self.output_root)
        except ValueError:
            return absolute_path

    def create_directory_structure(self) -> dict:
        """创建完整的目录结构并返回结构树"""
        structure = {
            self.output_root: {
                "黑盒测试": {
                    "稳压精度": {},
                    "输出纹波与噪声": {},
                    "动态响应": {},
                    "开关机时序": {},
                    "短路保护与恢复": {},
                },
                "白盒测试": {},
            }
        }

        for test_type, items in structure[self.output_root].items():
            for item_name in items:
                path = os.path.join(self.output_root, test_type, item_name)
                os.makedirs(path, exist_ok=True)

        return structure
