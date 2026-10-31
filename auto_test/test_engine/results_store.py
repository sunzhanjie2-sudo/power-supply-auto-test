from dataclasses import dataclass, field, asdict
from datetime import datetime
import csv
import os
import json
from typing import Optional


@dataclass
class TestResult:
    step_id: int = 0
    test_item: str = ""
    test_type: str = ""
    component_ref: str = ""
    status: str = "PENDING"  # PASS, FAIL, ERROR, SKIP, PENDING
    data: dict = field(default_factory=dict)
    deviation: Optional[float] = None
    error_msg: str = ""
    waveform_csv_path: str = ""
    waveform_png_path: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data"] = json.dumps(self.data, ensure_ascii=False)
        return d


class ResultsStore:
    """结果存储器，按测试类型分组"""

    def __init__(self):
        self.results: list = []

    def add_result(self, result: TestResult):
        self.results.append(result)

    def get_black_box_results(self) -> list:
        return [r for r in self.results if r.test_type == "black_box"]

    def get_white_box_results(self) -> list:
        return [r for r in self.results if r.test_type == "white_box"]

    def get_by_test_item(self, item_name: str) -> list:
        return [r for r in self.results if r.test_item == item_name]

    def get_by_component(self, ref_des: str) -> list:
        return [r for r in self.results if r.component_ref == ref_des]

    def get_pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    def get_fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    def get_error_count(self) -> int:
        return sum(1 for r in self.results if r.status == "ERROR")

    def get_total(self) -> int:
        return len(self.results)

    def export_csv(self, filepath: str, results: list = None):
        if results is None:
            results = self.results
        if not results:
            return
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        fieldnames = ["step_id", "test_item", "test_type", "component_ref",
                      "status", "deviation", "error_msg", "waveform_csv_path",
                      "waveform_png_path", "timestamp", "data"]
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                d = r.to_dict()
                writer.writerow(d)

    def clear(self):
        self.results.clear()