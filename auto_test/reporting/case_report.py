"""Persistent execution status beside the original case worksheets."""
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


class CaseReport:
    HEADERS = ("步骤", "测试项", "环温(℃)", "Vin(V)", "通道", "工况",
               "设定电流(A)", "最小电压(V)", "最大电压(V)", "纹波(Vpp)",
               "结果", "说明", "波形 CSV", "波形 PNG", "波形 NPZ")
    COLORS = {"PASS": "C6EFCE", "FAIL": "FFC7CE", "ERROR": "FFCC99",
              "SKIP": "D9D9D9", "未执行": "FFFFFF"}

    def __init__(self, wb, spec, tasks, output_dir):
        self.tasks = tasks
        self.output_dir = Path(output_dir or ".")
        if "执行汇总" in wb.sheetnames:
            del wb["执行汇总"]
        self.ws = wb.create_sheet("执行汇总", 0)
        ws = self.ws
        ws.merge_cells("A1:O1")
        ws["A1"] = "黑盒测试执行报告"
        ws["A1"].font = Font(name="微软雅黑", size=16, bold=True)
        ws.row_dimensions[1].height = 32
        ws.merge_cells("B2:O2")
        ws["A2"] = "执行状态"
        ws["B2"] = "未开始"
        ws["A3"] = "开始时间"
        ws["B3"] = datetime.now()
        ws["B3"].number_format = "yyyy-mm-dd hh:mm:ss"
        ws.merge_cells("B3:D3")
        ws["E3"] = "结束时间"
        ws.merge_cells("F3:H3")
        ws.merge_cells("A5:O5")
        ws["A5"] = "PASS 表示该工况的必需数据完整且满足工程判据；ERROR/SKIP/未执行均不视为通过。"
        ws.merge_cells("A6:O6")
        ws["A6"] = "各测试页底部结论仅统计已测数据；全部计划工况是否通过，以本页执行状态和逐项结果为准。"
        for r in (5, 6):
            ws.row_dimensions[r].height = 26
        for col, value in enumerate(self.HEADERS, 1):
            ws.cell(8, col, value)
            ws.cell(8, col).fill = PatternFill("solid", fgColor="92D050")
            ws.cell(8, col).font = Font(name="宋体", size=11, bold=True)
        for i, task in enumerate(tasks):
            row = i + 9
            for col, value in enumerate((i + 1, task.test_item, task.temp, task.vin,
                                        spec.outputs[task.channel].name, task.name,
                                        task.currents[task.channel]), 1):
                ws.cell(row, col, value)
            ws.cell(row, 11, "未执行")
            ws.row_dimensions[row].height = 42
        for row in ws.iter_rows():
            for cell in row:
                if cell.row != 1:
                    cell.font = Font(name="宋体", size=11)
                cell.alignment = Alignment(vertical="center", wrap_text=True)
        for col, width in enumerate((8, 22, 12, 12, 12, 38, 15, 15, 15, 15, 12, 50, 35, 35, 35), 1):
            ws.column_dimensions[get_column_letter(col)].width = width
        for c in "GHIJ":
            for row in range(9, len(tasks) + 9):
                ws[f"{c}{row}"].number_format = "0.0000"
        ws.freeze_panes = "G9"
        ws.auto_filter.ref = f"A8:O{max(9, len(tasks) + 8)}"
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "1:8"
        self.update_counts()

    def record(self, index, result):
        row = index + 9
        ws = self.ws
        for col, key in ((8, "vmin"), (9, "vmax"), (10, "ripple"), (11, "status"), (12, "note")):
            ws.cell(row, col).value = result.get(key)
        for col, key in ((13, "csv"), (14, "png"), (15, "npz")):
            path = result.get(key)
            if path:
                try:
                    relative = Path(path).relative_to(self.output_dir)
                except ValueError:
                    relative = Path(path)
                cell = ws.cell(row, col, key.upper())
                cell.hyperlink = str(relative)
        fill = PatternFill("solid", fgColor=self.COLORS.get(result.get("status"), "FFCC99"))
        for cell in ws[row]:
            cell.fill = fill
        self.update_counts()

    def update_counts(self):
        counts = Counter(self.ws.cell(i + 9, 11).value for i in range(len(self.tasks)))
        for col, name, value in ((1, "计划", len(self.tasks)), (3, "PASS", counts["PASS"]),
                                 (5, "FAIL", counts["FAIL"]), (7, "ERROR", counts["ERROR"]),
                                 (9, "SKIP", counts["SKIP"]), (11, "未执行", counts["未执行"])):
            self.ws.cell(4, col, name)
            self.ws.cell(4, col + 1, value)

    def finish(self, status):
        self.ws["B2"] = status
        self.ws["F3"] = datetime.now()
        self.ws["F3"].number_format = "yyyy-mm-dd hh:mm:ss"
        self.update_counts()
