import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .waveform_archiver import WaveformArchiver


class ReportGenerator:
    """Excel报告生成器 - 生成黑盒和白盒两份独立报告"""

    # 样式定义
    HEADER_FONT = Font(name="微软雅黑", bold=True, size=11)
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    HEADER_FONT_WHITE = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
    FAIL_FILL = PatternFill(start_color="FF4444", end_color="FF4444", fill_type="solid")
    FAIL_FONT = Font(name="微软雅黑", color="FFFFFF", bold=True)
    PASS_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    NORMAL_FONT = Font(name="微软雅黑", size=10)
    BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # 固定列定义（单 Sheet 模式：含"测试项"列）
    SINGLE_SHEET_COLUMNS = [
        "步骤ID", "测试项", "工况条件(Vin/T/Iout)", "被测通道/器件位号",
        "实测数据", "规格判据(上限/下限/典型值)", "偏差值",
        "判定结果(PASS/FAIL)", "波形文件相对路径", "备注"
    ]

    def __init__(self, config, archiver: WaveformArchiver = None):
        self.config = config
        self.archiver = archiver

    def generate_black_box_report(self, results: list, output_path: str):
        """生成黑盒测试报告 —— 单 Excel 文件多 Sheet（汇总 + 每测试项一页，波形图内嵌）"""
        wb = Workbook()
        wb.remove(wb.active)
        ordered = sorted(results, key=lambda r: r.step_id)
        self._write_summary_sheet(wb, ordered, "黑盒")

        # 按测试项分页（结构清晰、覆盖全量工况）
        grouped = {}
        for r in ordered:
            item = r.test_item or "其他"
            grouped.setdefault(item, []).append(r)
        for item_name, item_results in grouped.items():
            ws = wb.create_sheet(title=item_name[:28])
            self._write_sheet(ws, item_name, item_results, "black_box")

        output_path = output_path.replace(".xlsx", "") + "_黑盒测试报告.xlsx"
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        wb.save(output_path)
        return output_path

    def generate_white_box_report(self, results: list, output_path: str):
        """生成白盒器件应力测试报告 —— 单 Excel 文件多 Sheet（汇总 + 每器件一页，波形图内嵌）"""
        wb = Workbook()
        wb.remove(wb.active)
        ordered = sorted(results, key=lambda r: r.step_id)
        self._write_summary_sheet(wb, ordered, "白盒")

        grouped = {}
        for r in ordered:
            comp = r.component_ref or "未指定"
            grouped.setdefault(comp, []).append(r)
        for comp_name, comp_results in grouped.items():
            ws = wb.create_sheet(title=comp_name[:28])
            self._write_sheet(ws, comp_name, comp_results, "white_box")

        output_path = output_path.replace(".xlsx", "") + "_白盒器件应力测试报告.xlsx"
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        wb.save(output_path)
        return output_path

    def _write_summary_sheet(self, wb, results: list, kind: str):
        """汇总 Sheet：样机信息 + 按测试项/器件的统计表"""
        ws = wb.create_sheet("汇总")
        ws.cell(row=1, column=1, value=f"辅助电源自动化测试 - {kind}盒测试汇总报告").font = Font(name="微软雅黑", bold=True, size=14)
        _topo = getattr(self.config, "topology", None)
        _topo_txt = _topo.value if _topo else "-"
        info = f"样机型号: {self.config.model_name} | 拓扑: {_topo_txt} | SN: {self.config.sn} | 测试人员: {self.config.tester} | 日期: {self.config.test_date}"
        ws.cell(row=2, column=1, value=info).font = Font(name="微软雅黑", size=10)

        # 统计表
        headers = ["测试项/器件", "步数", "PASS", "FAIL", "ERROR", "SKIP", "通过率"]
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=4, column=c, value=h)
            cell.font = self.HEADER_FONT_WHITE
            cell.fill = self.HEADER_FILL
            cell.alignment = Alignment(horizontal="center")
            cell.border = self.BORDER

        key_fn = (lambda r: r.test_item) if kind == "黑盒" else (lambda r: r.component_ref or "未指定")
        stats = {}
        for r in results:
            k = key_fn(r)
            s = stats.setdefault(k, {"total": 0, "PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 0})
            s["total"] += 1
            st = r.status or "SKIP"
            if st in s:
                s[st] += 1
            else:
                s["SKIP"] += 1

        row = 5
        for k, s in sorted(stats.items()):
            rate = round(s["PASS"] / s["total"] * 100, 1) if s["total"] else 0
            vals = [k, s["total"], s["PASS"], s["FAIL"], s["ERROR"], s["SKIP"], f"{rate}%"]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = self.NORMAL_FONT
                cell.border = self.BORDER
            row += 1

        # 总通过率
        total = len(results)
        npass = sum(1 for r in results if r.status == "PASS")
        ws.cell(row=row + 1, column=1, value=f"合计 {total} 步 | PASS {npass} | 通过率 {npass/total*100:.1f}%" if total else "无结果").font = Font(name="微软雅黑", bold=True, size=11)

        for c in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(c)].width = 16

    def _write_sheet(self, ws, sheet_title: str, results: list, test_type: str):
        """写入单个测试项 Sheet：数据表 + 波形图内嵌（波形与数据并存）"""
        columns = self.SINGLE_SHEET_COLUMNS
        n_cols = len(columns)

        # 标题行
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
        title_cell = ws.cell(row=1, column=1, value=f"{sheet_title} - 测试报告")
        title_cell.font = Font(name="微软雅黑", bold=True, size=14)
        title_cell.alignment = Alignment(horizontal="center")

        # 样机信息行
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_cols)
        _topo = getattr(self.config, "topology", None)
        _topo_txt = _topo.value if _topo else "-"
        info = f"样机型号: {self.config.model_name} | 拓扑: {_topo_txt} | SN: {self.config.sn} | 测试人员: {self.config.tester} | 日期: {self.config.test_date}"
        info_cell = ws.cell(row=2, column=1, value=info)
        info_cell.font = Font(name="微软雅黑", size=10)

        # 表头
        header_row = 4
        for col_idx, col_name in enumerate(columns, 1):
            cell = ws.cell(row=header_row, column=col_idx, value=col_name)
            cell.font = self.HEADER_FONT_WHITE
            cell.fill = self.HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = self.BORDER

        # 数据行
        for row_idx, result in enumerate(results):
            data_row = header_row + 1 + row_idx
            is_fail = result.status == "FAIL"

            # 列1: 步骤ID
            ws.cell(row=data_row, column=1, value=result.step_id).font = self.NORMAL_FONT

            # 列2: 测试项
            ws.cell(row=data_row, column=2, value=result.test_item).font = self.NORMAL_FONT

            # 列3: 工况条件
            condition = self._format_condition(result)
            ws.cell(row=data_row, column=3, value=condition).font = self.NORMAL_FONT

            # 列4: 被测通道/器件位号
            target = result.component_ref if test_type == "white_box" else (result.data.get("channel", "CH1"))
            ws.cell(row=data_row, column=4, value=target).font = self.NORMAL_FONT

            # 列5: 实测数据
            measured = self._format_measured_data(result)
            ws.cell(row=data_row, column=5, value=measured).font = self.NORMAL_FONT

            # 列6: 规格判据
            criteria = self._format_criteria(result)
            ws.cell(row=data_row, column=6, value=criteria).font = self.NORMAL_FONT

            # 列7: 偏差值
            deviation = result.deviation if result.deviation is not None else ""
            ws.cell(row=data_row, column=7, value=deviation).font = self.NORMAL_FONT

            # 列8: 判定结果
            ws.cell(row=data_row, column=8, value=result.status).font = self.NORMAL_FONT

            # 列9: 波形文件相对路径
            waveform_path = result.waveform_csv_path or result.waveform_png_path or ""
            if self.archiver and waveform_path:
                waveform_path = self.archiver.get_relative_path(waveform_path)
            ws.cell(row=data_row, column=9, value=waveform_path).font = self.NORMAL_FONT

            # 列10: 备注
            ws.cell(row=data_row, column=10, value=result.error_msg or "").font = self.NORMAL_FONT

            # 标红处理
            if is_fail:
                for col in range(1, n_cols + 1):
                    cell = ws.cell(row=data_row, column=col)
                    cell.fill = self.FAIL_FILL
                    cell.font = self.FAIL_FONT

            # 边框
            for col in range(1, n_cols + 1):
                ws.cell(row=data_row, column=col).border = self.BORDER

        # 自动列宽
        for col_idx in range(1, n_cols + 1):
            max_width = max(
                len(str(columns[col_idx - 1])),
                max((len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(header_row + 1, header_row + 1 + len(results))), default=0)
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_width * 1.5 + 2, 10), 40)

        # ===== 波形图内嵌：波形与数据并存 =====
        try:
            from openpyxl.drawing.image import Image as XLImage
            from .waveform_archiver import WaveformArchiver
        except Exception:
            return

        img_section_row = header_row + len(results) + 2
        ws.cell(row=img_section_row, column=1, value="波形图（Waveforms）").font = Font(name="微软雅黑", bold=True, size=12)

        img_row = img_section_row + 2
        img_idx = 0
        rows_per_img = 15  # 每个波形图占用的行高
        for result in results:
            csv_path = result.waveform_csv_path
            if not csv_path or not os.path.exists(csv_path):
                continue
            caption = f"#{result.step_id} {self._format_condition(result)}  [{result.status}]"
            png_path = WaveformArchiver.save_waveform_png_from_csv(
                csv_path, title=f"{result.test_item}  {self._format_condition(result)}")
            if not png_path or not os.path.exists(png_path):
                continue
            row = img_row + (img_idx // 3) * rows_per_img
            col = 1 + (img_idx % 3) * 6  # 每 3 列一组放置
            ws.cell(row=row, column=col, value=caption).font = self.NORMAL_FONT
            try:
                xl_img = XLImage(png_path)
                xl_img.width = 420
                xl_img.height = 142
                ws.add_image(xl_img, f"{get_column_letter(col)}{row + 1}")
            except Exception:
                pass
            img_idx += 1
        if img_idx:
            ws.cell(row=img_row + ((img_idx - 1) // 3 + 1) * rows_per_img, column=1, value="")

    def _format_condition(self, result) -> str:
        """格式化工况条件（只显示实际记录的字段）"""
        data = result.data
        parts = []
        if data.get("vin") is not None:
            parts.append(f"Vin={data['vin']}V")
        if data.get("temp") is not None:
            parts.append(f"T={data['temp']}C")
        if data.get("iout") is not None:
            parts.append(f"Iout={data['iout']}A")
        return ", ".join(parts) if parts else str(data)

    @staticmethod
    def _fmt(val, fmt: str) -> str:
        """对可能为 None 的数值做安全格式化"""
        if val is None:
            return "N/A"
        try:
            return fmt.format(val)
        except (ValueError, TypeError):
            return str(val)

    def _format_measured_data(self, result) -> str:
        """格式化实测数据"""
        data = result.data
        parts = []
        if "vout" in data:
            parts.append(f"Vout={self._fmt(data.get('vout'), '{:.3f}')}V")
        if "vpp" in data:
            parts.append(f"Vpp={self._fmt(data.get('vpp'), '{:.3f}')}V")
        if "v_peak" in data:
            parts.append(f"Vpeak={self._fmt(data.get('v_peak'), '{:.3f}')}V")
        if "v_rms" in data:
            parts.append(f"Vrms={self._fmt(data.get('v_rms'), '{:.3f}')}V")
        if "stress_ratio" in data:
            parts.append(f"应力比={self._fmt(data.get('stress_ratio'), '{:.2%}')}")
        # 动态响应
        if "overshoot" in data:
            parts.append(f"过冲={self._fmt(data.get('overshoot'), '{:.3f}')}V")
        if "undershoot" in data:
            parts.append(f"下冲={self._fmt(data.get('undershoot'), '{:.3f}')}V")
        # 开关机时序
        if "startup_time_ms" in data:
            parts.append(f"启动时间={self._fmt(data.get('startup_time_ms'), '{:.2f}')}ms")
        if "shutdown_time_ms" in data:
            parts.append(f"关断时间={self._fmt(data.get('shutdown_time_ms'), '{:.2f}')}ms")
        # 短路保护与恢复
        if "protection_triggered" in data:
            parts.append("保护触发" if data.get("protection_triggered") else "未触发保护")
        if "short_v_min" in data:
            parts.append(f"短路最低电压={self._fmt(data.get('short_v_min'), '{:.3f}')}V")
        if "recovery_voltage" in data:
            parts.append(f"恢复电压={self._fmt(data.get('recovery_voltage'), '{:.3f}')}V")
        if "auto_recovered" in data:
            parts.append("自动恢复" if data.get("auto_recovered") else "未自动恢复")
        return "; ".join(parts) if parts else str(data)

    def _format_criteria(self, result) -> str:
        """格式化规格判据"""
        item_cfg = None
        for t in self.config.test_items:
            if t.name == result.test_item:
                item_cfg = t
                break

        if item_cfg and item_cfg.criteria:
            crit = item_cfg.criteria
            if isinstance(crit, dict):
                up, low, nom = crit.get("upper_limit"), crit.get("lower_limit"), crit.get("nominal_value")
            else:
                up, low, nom = crit.upper_limit, crit.lower_limit, crit.nominal_value
            return f"上限:{up} / 下限:{low} / 典型:{nom}"
        return "未配置"

    def generate_both_reports(self, results: list, output_dir: str) -> tuple:
        """一键生成两份报告，返回实际生成的文件路径（未生成则为 None）"""
        black_results = [r for r in results if r.test_type == "black_box"]
        white_results = [r for r in results if r.test_type == "white_box"]

        black_path = None
        white_path = None
        if black_results:
            black_path = self.generate_black_box_report(
                black_results, os.path.join(output_dir, "report.xlsx")
            )
        if white_results:
            white_path = self.generate_white_box_report(
                white_results, os.path.join(output_dir, "report.xlsx")
            )

        return black_path, white_path