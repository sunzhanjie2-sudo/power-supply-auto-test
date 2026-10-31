# -*- coding: utf-8 -*-
"""多路输出辅助电源黑盒测试用例生成器（严格对齐用户模板格式）。

生成 5 个 Sheet：规格&说明、纹波与稳压精度测试、动态响应测试、动态稳定度测试、启机关机测试。
支持 1~7 路输出；测试完成后用 fill_test_results() 回填数据与波形图片。

格式严格对齐用户模板（黑盒测试用例.xlsx）：
  - 字体：宋体 11 号，黑色，非粗体
  - 表头/标题背景色：FF92D050（绿色），数据区无填充
  - 边框：thin 细线
  - 数据行高 30，列宽与模板一致
  - 数值全部来自 PowerSpec 实际规格，模板中的三路/示例数值仅为样例
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage


# ============ 数据模型 ============

@dataclass
class OutputSpec:
    name: str = "CH1"
    vout_min: float = 0.0
    vout_typ: float = 12.0
    vout_max: float = 0.0
    pout_min: float = 0.0
    pout_typ: float = 0.0
    pout_max: float = 0.0
    ripple_percent: float = 3.0

    def vmin(self) -> float:
        return self.vout_min if self.vout_min else self.vout_typ * 0.95

    def vmax(self) -> float:
        return self.vout_max if self.vout_max else self.vout_typ * 1.05

    def ripple(self) -> float:
        return self.ripple_percent / 100.0 * self.vout_typ

    def iout(self, level: str) -> float:
        p = {"min": self.pout_min, "typ": self.pout_typ, "max": self.pout_max}[level]
        return p / self.vout_typ if p else 0.0


@dataclass
class PowerSpec:
    vin_min: float = 36.0
    vin_typ: float = 42.0
    vin_max: float = 48.0
    temp_min: float = 25.0
    temp_typ: float = 25.0
    temp_max: float = 25.0
    outputs: List[OutputSpec] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.outputs)

    def temperatures(self):
        """One block per physical temperature; identical boundaries are not new tests."""
        return list(dict.fromkeys((self.temp_min, self.temp_typ, self.temp_max)))

    def validate(self):
        import math
        if not 1 <= self.n <= 7:
            raise ValueError("输出通道数必须为 1–7")
        values = (self.vin_min, self.vin_typ, self.vin_max, *self.temperatures())
        if not all(math.isfinite(x) for x in values):
            raise ValueError("输入电压和环温必须为有限数值")
        if not 0 < self.vin_min <= self.vin_typ <= self.vin_max:
            raise ValueError("输入电压必须满足 0 < 最小 ≤ 典型 ≤ 最大")
        if not self.temp_min <= self.temp_typ <= self.temp_max:
            raise ValueError("环温必须满足 最小 ≤ 典型 ≤ 最大")
        for o in self.outputs:
            if not all(math.isfinite(x) for x in (o.vout_typ, o.vmin(), o.vmax(),
                       o.pout_min, o.pout_typ, o.pout_max, o.ripple_percent)):
                raise ValueError(f"{o.name} 规格必须为有限数值")
            if not 0 < o.vmin() <= o.vout_typ <= o.vmax():
                raise ValueError(f"{o.name} 输出电压范围无效")
            if not 0 <= o.pout_min <= o.pout_typ <= o.pout_max or o.pout_max <= 0:
                raise ValueError(f"{o.name} 功率必须满足 0 ≤ 最小 ≤ 典型 ≤ 最大且最大 > 0")
            if o.ripple_percent <= 0:
                raise ValueError(f"{o.name} 纹波限值必须大于 0")

    @classmethod
    def from_config(cls, config) -> "PowerSpec":
        outs = []
        for oc in config.output_channels:
            # 功率未配置时按电流限值回推，保证轻载/满载电流不为 0
            outs.append(OutputSpec(
                name=oc.channel_name, vout_min=oc.vout_min, vout_typ=oc.nominal_voltage,
                vout_max=oc.vout_max,
                pout_min=oc.pout_min if oc.pout_min else oc.get_iout_min() * oc.nominal_voltage,
                pout_typ=oc.pout_typ if oc.pout_typ else (oc.nominal_voltage * oc.nominal_current),
                pout_max=oc.pout_max if oc.pout_max else oc.get_iout_max() * oc.nominal_voltage,
                ripple_percent=oc.ripple_percent))
        return cls(vin_min=config.boundary.vin_min, vin_typ=config.boundary.vin_rated,
                   vin_max=config.boundary.vin_max, temp_min=config.boundary.temp_min,
                   temp_typ=config.boundary.temp_rated, temp_max=config.boundary.temp_max,
                   outputs=outs)


# ============ 中文数字（用于"X路同时"、测试要求中的"第X路"）============

_CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}


def _cn(i: int) -> str:
    return _CN_NUM.get(i, str(i))


# ============ 样式（严格对齐用户模板）============

FONT = Font(name="宋体", size=11)
HDR_FILL = PatternFill("solid", fgColor="FF92D050")
BORDER = Border(left=Side(style="thin"), right=Side(style="thin"),
                top=Side(style="thin"), bottom=Side(style="thin"))
CENTER = Alignment(horizontal="center", vertical="center")
REQ_ALIGN = Alignment(horizontal="left", vertical="top", wrap_text=True)


def _sc(cell, fill=None, align=None):
    """统一设置单元格样式：宋体 11、thin 边框、居中（可覆盖）。"""
    cell.font = FONT
    cell.border = BORDER
    cell.alignment = align if align is not None else CENTER
    if fill is not None:
        cell.fill = fill


# ============ 测试要求（按路数动态生成）============

def _load_instrument_req(n: int) -> str:
    """负载仪描述：第一路 A段10ms/B段10ms，第二路 11ms，依次递增。"""
    lines = ["负载仪： 电流跳变斜率设置为最大，第一路 A段设置10ms，B段设置10ms"]
    for i in range(2, n + 1):
        ms = 9 + i
        lines.append("                               第" + _cn(i) + "路 A段设置" + str(ms) + "ms，B段设置" + str(ms) + "ms")
    return chr(10).join(lines)


_SCOPE_REQ = "示波器：1.使用20Mhz带宽，水平时间刻度为"
_NL = chr(10)


def _scope_body(unit: str) -> str:
    return (_SCOPE_REQ + unit + "/div。" + _NL + "        2.通道的直流偏置为被测电压的典型值，垂直刻度屏幕电压范围需刚大于规格书规定max值与min值的2倍。" + _NL + "探头：  1.测量输出电压，采用最小接地环。")


def test_requirement(kind: str, n: int) -> str:
    head = "测试要求：" + _NL
    if kind == "ripple":
        return head + _scope_body("100us")
    if kind == "dynamic":
        return head + _scope_body("5ms") + _NL + _load_instrument_req(n)
    if kind == "stability":
        return head + _scope_body("500ms") + _NL + _load_instrument_req(n) + _NL + "源： 输入电压从Vin_min到Vin_max跳变，A段设置500ms,B设置500ms"
    if kind == "startup":
        return head + _scope_body("10ms") + _NL + "负载仪： 上电/轻载下电采用轻载，满载下电采用额定满载（不施加超额负载）"
    return ""


# ============ 工况名（显式列出其余通道，与模板一致）============

def _cross_name(k: int, mode: str, n: int) -> str:
    others = [str(j) for j in range(1, n + 1) if j != k]
    other_txt = "，".join(others)
    if mode == "light":
        if others:
            return f"{k}路轻载，{other_txt}路满载"
        return f"{k}路轻载"
    if others:
        return f"{k}路满载，{other_txt}路轻载"
    return f"{k}路满载"


def ripple_plan(spec: "PowerSpec"):
    """生成纹波与稳压精度测试的去重工况计划（显式通道命名）。"""
    n = spec.n
    outs = spec.outputs

    def currents(ctype):
        if ctype == "light":
            return [o.iout("min") for o in outs]
        if ctype == "typ":
            return [o.iout("typ") for o in outs]
        if ctype == "full":
            return [o.iout("max") for o in outs]
        if ctype.startswith("xlight"):
            k = int(ctype[6:]) - 1
            return [o.iout("min") if i == k else o.iout("max") for i, o in enumerate(outs)]
        if ctype.startswith("xfull"):
            k = int(ctype[5:]) - 1
            return [o.iout("max") if i == k else o.iout("min") for i, o in enumerate(outs)]
        return [0.0] * n

    # 基础工况：轻载 / 典型载 / 满载
    raw = [("轻载", "light"), ("典型载", "typ"), ("满载", "full")]
    # 交叉调整率边界工况（多路输出必须全覆盖）：
    #   xlight{k} = 第 k 路轻载、其余路满载  → 第 k 路电压上漂（关注最高）
    #   xfull{k}  = 第 k 路满载、其余路轻载  → 第 k 路电压跌落（关注最低）
    # 例如三路：1满载2,3轻载(1路最低)、2满载1,3轻载(2路最低)、3满载1,2轻载(3路最低)，
    #          1轻载2,3满载(1路最高)、2轻载1,3满载(2路最高)、3轻载1,2满载(3路最高)。
    for k in range(1, n + 1):
        raw.append((_cross_name(k, "light", n), f"xlight{k}"))
        raw.append((_cross_name(k, "full", n), f"xfull{k}"))

    seen, conditions = set(), []
    for name, ctype in raw:
        cur = tuple(round(v, 6) for v in currents(ctype))
        if cur not in seen:
            seen.add(cur)
            conditions.append((name, ctype, currents(ctype)))

    temps = spec.temperatures()
    plan = []
    r = 13
    for t in temps:
        for name, ctype, cur in conditions:
            plan.append((t, name, ctype, cur, r))
            r += 2
    return plan, conditions


# ============ 布局 ============

class TestCaseLayout:
    def __init__(self, n: int):
        self.n = n

    def spec_output_label_col(self, i: int) -> int:
        return 1 + i * 4

    def spec_output_value_cols(self, i: int) -> Tuple[int, int, int]:
        c = self.spec_output_label_col(i) + 1
        return c, c + 1, c + 2

    def ripple_cond_last(self) -> int:
        """纹波与稳压精度工况区末列 = 环温 + 工况名 + n 路电流 = 2 + n。"""
        return 2 + self.n

    def ripple_result_cols(self, i: int) -> Tuple[int, int, int, int]:
        c = 3 + self.n + i * 4
        return c, c + 1, c + 2, c + 3

    def ripple_remark_col(self) -> int:
        return 3 + self.n + self.n * 4

    def dynamic_cond_last(self) -> int:
        """动态响应工况区末列 = 环温 + 工况名 + Vin + 2n 电流 = 3 + 2n。"""
        return 3 + 2 * self.n

    def dynamic_result_cols(self, i: int) -> Tuple[int, int, int]:
        c = 4 + 2 * self.n + i * 3
        return c, c + 1, c + 2

    def stability_result_cols(self, i: int) -> Tuple[int, int, int]:
        c = 5 + 2 * self.n + i * 3
        return c, c + 1, c + 2

    def startup_result_cols(self, i: int) -> Tuple[int, int, int]:
        c = 4 + self.n + i * 3
        return c, c + 1, c + 2


# ============ 生成器 ============

class TestCaseGenerator:
    def __init__(self, spec: PowerSpec):
        self.spec = spec
        self.n = spec.n
        self.layout = TestCaseLayout(self.n)

    # ---------- Sheet 1：规格&说明 ----------
    def _write_spec_sheet(self, ws):
        ws.column_dimensions["A"].width = 15.45

        # 输入电压
        for col, label in [(2, "Vin_min(V)"), (3, "Vin_typ(V)"), (4, "Vin_max(V)")]:
            _sc(ws.cell(row=2, column=col, value=label), fill=HDR_FILL)
        _sc(ws.cell(row=3, column=1, value="输入电压"))
        ws.cell(row=3, column=2, value=self.spec.vin_min)
        ws.cell(row=3, column=3, value=self.spec.vin_typ)
        ws.cell(row=3, column=4, value=self.spec.vin_max)
        for col in (2, 3, 4):
            _sc(ws.cell(row=3, column=col))

        for i, o in enumerate(self.spec.outputs):
            lc = self.layout.spec_output_label_col(i)
            cmin, ctyp, cmax = self.layout.spec_output_value_cols(i)
            # 输出电压
            for col, label in [(cmin, f"Vout{i+1}_min(V)"), (ctyp, f"Vout{i+1}_typ(V)"), (cmax, f"Vout{i+1}_max(V)")]:
                _sc(ws.cell(row=5, column=col, value=label), fill=HDR_FILL)
            _sc(ws.cell(row=6, column=lc, value=f"第{i+1}路输出电压"))
            ws.cell(row=6, column=cmin, value=o.vmin())
            ws.cell(row=6, column=ctyp, value=o.vout_typ)
            ws.cell(row=6, column=cmax, value=o.vmax())
            for col in (cmin, ctyp, cmax):
                _sc(ws.cell(row=6, column=col))

            # 纹波（公式 = Vout_typ * 纹波%）
            _sc(ws.cell(row=8, column=cmin, value=f"Vout{i+1}_ripple(V)"), fill=HDR_FILL)
            ws.merge_cells(start_row=8, start_column=cmin, end_row=8, end_column=cmax)
            _sc(ws.cell(row=9, column=lc, value=f"纹波{i+1}"))
            typ_ref = f"{get_column_letter(ctyp)}6"
            _sc(ws.cell(row=9, column=cmin, value=f"={typ_ref}*{o.ripple_percent / 100}"))
            ws.merge_cells(start_row=9, start_column=cmin, end_row=9, end_column=cmax)

        # 输出功率的单位为 W。
            for col, level in [(cmin, "min"), (ctyp, "typ"), (cmax, "max")]:
                label = f"Pout{i+1}_{level}(W)"
                _sc(ws.cell(row=11, column=col, value=label), fill=HDR_FILL)
            _sc(ws.cell(row=12, column=lc, value=f"第{i+1}路输出功率"))
            ws.cell(row=12, column=cmin, value=o.pout_min)
            ws.cell(row=12, column=ctyp, value=o.pout_typ)
            ws.cell(row=12, column=cmax, value=o.pout_max)
            for col in (cmin, ctyp, cmax):
                _sc(ws.cell(row=12, column=col))

            # 输出电流（公式 = Pout / Vout_typ）
            for col, label in [(cmin, f"Iout{i+1}_min(A)"), (ctyp, f"Iout{i+1}_typ(A)"), (cmax, f"Iout{i+1}_max(A)")]:
                _sc(ws.cell(row=14, column=col, value=label), fill=HDR_FILL)
            _sc(ws.cell(row=15, column=lc, value=f"第{i+1}路设置电流"))
            for col, level in [(cmin, "min"), (ctyp, "typ"), (cmax, "max")]:
                p_ref = f"{get_column_letter(col)}12"
                _sc(ws.cell(row=15, column=col, value=f"={p_ref}/{typ_ref}"))

        # 环境温度
        for col, label in [(2, "Ta_min(℃)"), (3, "Ta_typ(℃)"), (4, "Ta_max(℃)")]:
            _sc(ws.cell(row=18, column=col, value=label), fill=HDR_FILL)
        _sc(ws.cell(row=19, column=1, value="环境温度"))
        ws.cell(row=19, column=2, value=self.spec.temp_min)
        ws.cell(row=19, column=3, value=self.spec.temp_typ)
        ws.cell(row=19, column=4, value=self.spec.temp_max)
        for col in (2, 3, 4):
            _sc(ws.cell(row=19, column=col))

    def _current_level(self, ctype: str, j: int) -> str:
        if ctype == "light":
            return "min"
        if ctype == "typ":
            return "typ"
        if ctype == "full":
            return "max"
        if ctype.startswith("xlight"):
            k = int(ctype[6:]) - 1
            return "min" if j == k else "max"
        if ctype.startswith("xfull"):
            k = int(ctype[5:]) - 1
            return "max" if j == k else "min"
        return "min"

    def _current_ref(self, j: int, level: str) -> str:
        cmin, ctyp, cmax = self.layout.spec_output_value_cols(j)
        col = {"min": cmin, "typ": ctyp, "max": cmax}[level]
        return f"='规格&说明'!{get_column_letter(col)}15"

    # ---------- Sheet 2：纹波与稳压精度 ----------
    def _write_ripple_sheet(self, ws):
        n = self.n
        remark = self.layout.ripple_remark_col()
        ws.column_dimensions["A"].width = 9.77
        ws.column_dimensions["B"].width = 14.36
        ws.column_dimensions["C"].width = 10.68

        # 测试要求
        _sc(ws.cell(row=1, column=1, value=test_requirement("ripple", n)), align=REQ_ALIGN)
        ws.merge_cells(start_row=1, start_column=1, end_row=7, end_column=remark)

        # 标题
        _sc(ws.cell(row=9, column=1, value="稳压精度与纹波测试"), fill=HDR_FILL)
        ws.merge_cells(start_row=9, start_column=1, end_row=9, end_column=remark)

        # 表头（row 10-11）：工况区 + 每路结果区 + 备注
        _sc(ws.cell(row=10, column=1, value="工况"))
        ws.merge_cells(start_row=10, start_column=1, end_row=11, end_column=self.layout.ripple_cond_last())
        for i in range(n):
            cmin, _, _, _ = self.layout.ripple_result_cols(i)
            _sc(ws.cell(row=10, column=cmin, value=f"Vout{i+1}"))
            ws.merge_cells(start_row=10, start_column=cmin, end_row=10, end_column=cmin + 3)
            for c, label in [(cmin, "min"), (cmin + 1, "max"), (cmin + 2, "纹波"), (cmin + 3, "图片")]:
                _sc(ws.cell(row=11, column=c, value=label))
        _sc(ws.cell(row=11, column=remark, value="备注"))

        # 工况行（每工况 2 行：标签行 + 数据行，结果列合并 2 行）
        plan, _ = ripple_plan(self.spec)
        per_block = len(plan) // len(self.spec.temperatures())
        cur_headers = [f"{i+1}路电流(A)" for i in range(n)]
        for idx, (t, name, ctype, currents, data_row) in enumerate(plan):
            label_row = data_row - 1
            is_first_in_block = (idx % per_block == 0)
            if is_first_in_block:
                _sc(ws.cell(row=label_row, column=1, value="环温"))
            _sc(ws.cell(row=label_row, column=2, value=name))
            ws.merge_cells(start_row=label_row, start_column=2, end_row=data_row, end_column=2)
            for j, h in enumerate(cur_headers):
                _sc(ws.cell(row=label_row, column=3 + j, value=h))
            if is_first_in_block:
                _sc(ws.cell(row=data_row, column=1, value=t))
            for j in range(n):
                _sc(ws.cell(row=data_row, column=3 + j, value=self._current_ref(j, self._current_level(ctype, j))))
            for i in range(n):
                cmin, cmax, crip, cimg = self.layout.ripple_result_cols(i)
                for c in (cmin, cmax, crip, cimg):
                    ws.merge_cells(start_row=label_row, start_column=c, end_row=data_row, end_column=c)
            ws.row_dimensions[label_row].height = 30
            ws.row_dimensions[data_row].height = 30

        # 环温标签列合并（三块）
        per_block = len(plan) // len(self.spec.temperatures())
        for bi in range(len(self.spec.temperatures())):
            start = 13 + bi * per_block * 2
            end = start + per_block * 2 - 2
            if end > start:
                ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)

        last_data_row = 13 + len(plan) * 2 - 2
        self._write_ripple_summary(ws, last_data_row)

    def _write_ripple_summary(self, ws, start_row):
        n = self.n
        plan, _ = ripple_plan(self.spec)
        data_top, data_bottom = 12, 13 + len(plan) * 2 - 2
        r0 = start_row + 1
        _sc(ws.cell(row=r0, column=1, value="测试结果"))
        _sc(ws.cell(row=r0, column=2, value="最小值"))
        _sc(ws.cell(row=r0 + 1, column=2, value="最大值"))
        for i in range(n):
            cmin, cmax, crip, cimg = self.layout.ripple_result_cols(i)
            rng = f"{get_column_letter(cmin)}{data_top}:{get_column_letter(cmin)}{data_bottom}"
            _sc(ws.cell(row=r0, column=cmin, value=f'=IF(COUNT({rng})=0,"未测量",MIN({rng}))'))
            for c in (cmax, crip, cimg):
                _sc(ws.cell(row=r0, column=c, value="/"))
            for c in (cmax, crip):
                rng = f"{get_column_letter(c)}{data_top}:{get_column_letter(c)}{data_bottom}"
                _sc(ws.cell(row=r0 + 1, column=c, value=f'=IF(COUNT({rng})=0,"未测量",MAX({rng}))'))
            for c in (cmin, cimg):
                _sc(ws.cell(row=r0 + 1, column=c, value="/"))

        r1 = r0 + 2
        _sc(ws.cell(row=r1, column=1, value="判据"))
        _sc(ws.cell(row=r1, column=2, value="最大值"))
        _sc(ws.cell(row=r1 + 1, column=2, value="最小值"))
        for i, o in enumerate(self.spec.outputs):
            cmin, cmax, crip, cimg = self.layout.ripple_result_cols(i)
            scmin, sctyp, scmax = self.layout.spec_output_value_cols(i)
            _sc(ws.cell(row=r1, column=cmax, value=f"='规格&说明'!{get_column_letter(scmax)}6"))
            _sc(ws.cell(row=r1, column=crip, value=f"='规格&说明'!{get_column_letter(scmin)}9"))
            for c in (cmin, cimg):
                _sc(ws.cell(row=r1, column=c, value="/"))
            _sc(ws.cell(row=r1 + 1, column=cmin, value=f"='规格&说明'!{get_column_letter(scmin)}6"))
            for c in (cmax, crip, cimg):
                _sc(ws.cell(row=r1 + 1, column=c, value="/"))

        r2 = r1 + 2
        _sc(ws.cell(row=r2, column=1, value="已测数据结论"))
        for i in range(n):
            cmin, cmax, crip, cimg = self.layout.ripple_result_cols(i)
            for c, measured, limit, op in ((cmin, r0, r1+1, ">"), (cmax, r0+1, r1, "<"), (crip, r0+1, r1, "<")):
                L = get_column_letter(c)
                _sc(ws.cell(row=r2, column=c, value=f'=IF(ISNUMBER({L}{measured}),IF({L}{limit}{op}{L}{measured},"FAIL","PASS"),"未测量")'))
            _sc(ws.cell(row=r2, column=cimg, value="/"))
        for rr in range(r0, r2 + 1):
            ws.row_dimensions[rr].height = 30

    # ---------- Sheet 3/4/5：动态响应/稳定度/启机 ----------
    def _write_dynamic_sheet(self, ws, kind: str):
        n = self.n
        if kind == "dynamic":
            title, result_cols = "动态响应测试", self.layout.dynamic_result_cols
            n_param = 1 + 2 * n
            row7_height = 28
        elif kind == "stability":
            title, result_cols = "动态稳定度测试", self.layout.stability_result_cols
            n_param = 2 + 2 * n
            row7_height = 38
        else:
            title, result_cols = "启机关机测试", self.layout.startup_result_cols
            n_param = 1 + n
            row7_height = None

        result_start = result_cols(0)[0]
        last_col = result_cols(n - 1)[2]
        cond_last_col = 2 + n_param  # 环温 + 工况名 + 参数列

        if kind == "dynamic":
            ws.column_dimensions["B"].width = 14.36
        elif kind == "stability":
            ws.column_dimensions["B"].width = 14.36
        else:
            ws.column_dimensions["A"].width = 14.36

        # 测试要求
        _sc(ws.cell(row=1, column=1, value=test_requirement(kind, n)), align=REQ_ALIGN)
        ws.merge_cells(start_row=1, start_column=1, end_row=7, end_column=last_col)
        if row7_height:
            ws.row_dimensions[7].height = row7_height

        # 标题
        _sc(ws.cell(row=9, column=1, value=title), fill=HDR_FILL)
        ws.merge_cells(start_row=9, start_column=1, end_row=9, end_column=last_col)

        # 表头
        _sc(ws.cell(row=10, column=1, value="工况"))
        ws.merge_cells(start_row=10, start_column=1, end_row=11, end_column=cond_last_col)
        for i in range(n):
            cmin, _, _ = result_cols(i)
            _sc(ws.cell(row=10, column=cmin, value=f"Vout{i+1}"))
            ws.merge_cells(start_row=10, start_column=cmin, end_row=10, end_column=cmin + 2)
            for c, label in [(cmin, "min"), (cmin + 1, "max"), (cmin + 2, "图片")]:
                _sc(ws.cell(row=11, column=c, value=label))

        # 工况行（每工况 2 行）
        temps = self.spec.temperatures()
        vins = [self.spec.vin_min, self.spec.vin_typ, self.spec.vin_max]
        row = 12
        for ti, t in enumerate(temps):
            for vi, v in enumerate(vins):
                label_row = row
                data_row = row + 1
                vin_label = "最小" if v == self.spec.vin_min else ("典型" if v == self.spec.vin_typ else "最大")
                if kind == "dynamic":
                    name = f"{_cn(n)}路同时轻载满载跳变，Vin{vin_label}"
                    self._dyn_row(ws, label_row, data_row, t if vi == 0 else None, name, [v],
                                  [o.iout("min") for o in self.spec.outputs],
                                  [o.iout("max") for o in self.spec.outputs], "single", result_cols)
                elif kind == "stability":
                    name = f"{_cn(n)}路同时轻载满载跳变，Vin{vin_label}"
                    self._dyn_row(ws, label_row, data_row, t if vi == 0 else None, name,
                                  [self.spec.vin_min, self.spec.vin_max],
                                  [o.iout("min") for o in self.spec.outputs],
                                  [o.iout("max") for o in self.spec.outputs], "ab", result_cols)
                else:
                    name = ("轻载上电", "轻载下电", "满载下电")[vi]
                    curs = [o.iout("max") for o in self.spec.outputs] if name == "满载下电" else [o.iout("min") for o in self.spec.outputs]
                    self._dyn_row(ws, label_row, data_row, t if vi == 0 else None, name, [v], curs, None, "single", result_cols)
                ws.row_dimensions[label_row].height = 30
                ws.row_dimensions[data_row].height = 30
                row += 2

        # 环温列合并（每环温块 3 个 Vin 工况）
        for ti in range(len(temps)):
            start = 13 + ti * 6
            ws.merge_cells(start_row=start, start_column=1, end_row=start + 4, end_column=1)

        self._write_dynamic_summary(ws, kind, result_cols)

    def _dyn_row(self, ws, label_row, data_row, temp, name, vins, cur_a, cur_b, vin_mode, result_cols):
        n = self.n
        if temp is not None:
            _sc(ws.cell(row=label_row, column=1, value="环温"))
            _sc(ws.cell(row=data_row, column=1, value=temp))
        _sc(ws.cell(row=label_row, column=2, value=name))
        ws.merge_cells(start_row=label_row, start_column=2, end_row=data_row, end_column=2)

        if vin_mode == "ab":
            headers = ["输入电压A段(V)", "输入电压B段(V)"]
            for i in range(n):
                headers.append(f"{i+1}路电流A段(A)")
                headers.append(f"{i+1}路电流B段(A)")
            for j, h in enumerate(headers):
                _sc(ws.cell(row=label_row, column=3 + j, value=h))
            _sc(ws.cell(row=data_row, column=3, value=vins[0]))
            _sc(ws.cell(row=data_row, column=4, value=vins[1]))
            for j in range(n):
                _sc(ws.cell(row=data_row, column=5 + 2 * j, value=round(cur_a[j], 4)))
                _sc(ws.cell(row=data_row, column=6 + 2 * j, value=round(cur_b[j], 4) if cur_b else 0.0))
        elif cur_b is not None:
            headers = ["输入电压(V)"]
            for i in range(n):
                headers.append(f"{i+1}路电流A段(A)")
                headers.append(f"{i+1}路电流B段(A)")
            for j, h in enumerate(headers):
                _sc(ws.cell(row=label_row, column=3 + j, value=h))
            _sc(ws.cell(row=data_row, column=3, value=vins[0]))
            for j in range(n):
                _sc(ws.cell(row=data_row, column=4 + 2 * j, value=round(cur_a[j], 4)))
                _sc(ws.cell(row=data_row, column=5 + 2 * j, value=round(cur_b[j], 4)))
        else:
            headers = ["输入电压(V)"] + [f"{i+1}路电流(A)" for i in range(n)]
            for j, h in enumerate(headers):
                _sc(ws.cell(row=label_row, column=3 + j, value=h))
            _sc(ws.cell(row=data_row, column=3, value=vins[0]))
            for j in range(n):
                _sc(ws.cell(row=data_row, column=4 + j, value=round(cur_a[j], 4)))

        for i in range(n):
            for c in result_cols(i):
                ws.merge_cells(start_row=label_row, start_column=c, end_row=data_row, end_column=c)

    def _write_dynamic_summary(self, ws, kind, result_cols):
        """动态/稳定度/启机底部：测试结果统计 + 判据（引用规格&说明）+ 结论公式。

        与纹波表同风格：数据回填后 Excel 打开即自动计算 pass/fail。
        """
        n = self.n
        if kind in ("dynamic", "stability"):
            label_col = result_cols(0)[0] - 2
            result_merge_width = 2
        else:
            label_col = result_cols(0)[0] - 1
            result_merge_width = 1

        data_top, data_bottom = 12, 11 + 6 * len(self.spec.temperatures())
        base = data_bottom + 1

        def _label(row, text):
            row = base + row - 30
            _sc(ws.cell(row=row, column=label_col, value=text))
            if result_merge_width > 1:
                ws.merge_cells(start_row=row, start_column=label_col,
                               end_row=row, end_column=label_col + result_merge_width - 1)

        _label(30, "测试结果-最小值")
        _label(31, "测试结果-最大值")
        _label(32, "判据-最大值")
        _label(33, "判据-最小值")
        _label(34, "结论")

        for i in range(n):
            cmin, cmax, cimg = result_cols(i)
            scmin, sctyp, scmax = self.layout.spec_output_value_cols(i)
            L = get_column_letter
            # 测试结果统计
            _sc(ws.cell(row=30, column=cmin,
                        value=f'=IF(COUNT({L(cmin)}{data_top}:{L(cmin)}{data_bottom})=0,"未测量",MIN({L(cmin)}{data_top}:{L(cmin)}{data_bottom}))'))
            _sc(ws.cell(row=30, column=cmax, value="/"))
            _sc(ws.cell(row=31, column=cmin, value="/"))
            _sc(ws.cell(row=31, column=cmax,
                        value=f'=IF(COUNT({L(cmax)}{data_top}:{L(cmax)}{data_bottom})=0,"未测量",MAX({L(cmax)}{data_top}:{L(cmax)}{data_bottom}))'))
            # 判据：来自规格&说明 的输出电压上下限；启机关机只判上冲（下电 min 自然归 0）
            _sc(ws.cell(row=32, column=cmax, value=f"='规格&说明'!{L(scmax)}6"))
            _sc(ws.cell(row=32, column=cmin, value="/"))
            if kind == "startup":
                _sc(ws.cell(row=33, column=cmin, value="/"))
                _sc(ws.cell(row=33, column=cmax, value="/"))
            else:
                _sc(ws.cell(row=33, column=cmin, value=f"='规格&说明'!{L(scmin)}6"))
                _sc(ws.cell(row=33, column=cmax, value="/"))
            _sc(ws.cell(row=32, column=cimg, value="/"))
            _sc(ws.cell(row=33, column=cimg, value="/"))
            # 结论
            if kind == "startup":
                _sc(ws.cell(row=34, column=cmin, value="/"))
            else:
                _sc(ws.cell(row=34, column=cmin,
                            value=f'=IF(ISNUMBER({L(cmin)}30),IF({L(cmin)}33>{L(cmin)}30,"FAIL","PASS"),"未测量")'))
            _sc(ws.cell(row=34, column=cmax,
                        value=f'=IF(ISNUMBER({L(cmax)}31),IF({L(cmax)}32<{L(cmax)}31,"FAIL","PASS"),"未测量")'))
            _sc(ws.cell(row=34, column=cimg, value="/"))
        for rr in range(30, 35):
            ws.row_dimensions[rr].height = 30
        # Keep summary references correct when fewer than three temperature blocks exist.
        if base != 30:
            from openpyxl.formula.translate import Translator
            for row in range(30, 35):
                for cell in list(ws[row]):
                    if cell.column < result_cols(0)[0]:
                        continue
                    target = ws.cell(base + row - 30, cell.column)
                    target._style = cell._style
                    if cell.data_type == "f":
                        # Statistical ranges point at measurements, not at the moved summary.
                        if row in (30, 31):
                            target.value = cell.value
                        elif "规格&说明" in cell.value:
                            target.value = cell.value
                        else:
                            target.value = Translator(cell.value, origin=cell.coordinate).translate_formula(target.coordinate)
                    else:
                        target.value = cell.value
                    cell.value = None
            ws.delete_rows(base + 5, 34 - (base + 4))

    # ---------- 主入口 ----------
    def build_workbook(self) -> Workbook:
        """生成工作簿对象（不落盘）。执行器持有它以支持逐工况增量保存。"""
        self.spec.validate()
        wb = Workbook()
        wb.remove(wb.active)
        self._write_spec_sheet(wb.create_sheet("规格&说明"))
        self._write_ripple_sheet(wb.create_sheet("纹波与稳压精度测试"))
        self._write_dynamic_sheet(wb.create_sheet("动态响应测试"), "dynamic")
        self._write_dynamic_sheet(wb.create_sheet("动态稳定度测试"), "stability")
        self._write_dynamic_sheet(wb.create_sheet("启机关机测试"), "startup")
        for ws in wb:
            ws.freeze_panes = "C12" if ws.title != "规格&说明" else "B2"
            ws.sheet_view.showGridLines = False
            for col in range(1, ws.max_column + 1):
                letter = get_column_letter(col)
                ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 13, 15)
            if ws.title != "规格&说明":
                cols = {"纹波与稳压精度测试": self.layout.ripple_result_cols,
                        "动态响应测试": self.layout.dynamic_result_cols,
                        "动态稳定度测试": self.layout.stability_result_cols,
                        "启机关机测试": self.layout.startup_result_cols}[ws.title]
                ws.column_dimensions["B"].width = 32
                for ch in range(self.n):
                    ws.column_dimensions[get_column_letter(cols(ch)[-1])].width = 35
                ws.print_options.horizontalCentered = True
                ws.page_setup.orientation = "landscape"
                ws.page_setup.paperSize = ws.PAPERSIZE_A3
                ws.page_setup.fitToWidth = 1
                ws.page_setup.fitToHeight = 0
                ws.sheet_properties.pageSetUpPr.fitToPage = True
        wb.calculation.fullCalcOnLoad = True
        return wb

    def generate(self, output_path: str) -> str:
        wb = self.build_workbook()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        wb.save(output_path)
        return output_path


# ============ 回填辅助 ============

def writable_cell(ws, row: int, col: int):
    """若目标为合并单元格，返回其左上角坐标（合并区只有左上角可写）。"""
    cell = ws.cell(row=row, column=col)
    if cell.__class__.__name__ == "MergedCell":
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
                return rng.min_row, rng.min_col
    return row, col


# ============ 回填 ============

def fill_test_results(test_case_path: str, fills: List[dict], output_path: str = None) -> str:
    from openpyxl import load_workbook
    output_path = output_path or test_case_path
    wb = load_workbook(test_case_path)
    n = _infer_n(wb)
    layout = TestCaseLayout(n)

    def _cols(sheet):
        return {"纹波与稳压精度测试": layout.ripple_result_cols,
                "动态响应测试": layout.dynamic_result_cols,
                "动态稳定度测试": layout.stability_result_cols,
                "启机关机测试": layout.startup_result_cols}.get(sheet, lambda i: (0, 0, 0))

    for f in fills:
        sheet = f.get("sheet", "")
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        row = int(f.get("row", 0))
        ch = int(f.get("channel", 0))
        cols = _cols(sheet)(ch)
        if row <= 0 or ch < 0 or ch >= n:
            continue
        if "min" in f and f["min"] is not None:
            wr, wc = writable_cell(ws, row, cols[0])
            ws.cell(row=wr, column=wc, value=round(float(f["min"]), 4))
        if "max" in f and f["max"] is not None:
            wr, wc = writable_cell(ws, row, cols[1])
            ws.cell(row=wr, column=wc, value=round(float(f["max"]), 4))
        if len(cols) >= 4 and "ripple" in f and f["ripple"] is not None:
            wr, wc = writable_cell(ws, row, cols[2])
            ws.cell(row=wr, column=wc, value=round(float(f["ripple"]), 4))
        img_col = cols[3] if len(cols) >= 4 else cols[2]
        png = f.get("png")
        if png and os.path.exists(png):
            try:
                img = XLImage(png)
                img.width = 240
                img.height = 90
                wr, wc = writable_cell(ws, row, img_col)
                ws.add_image(img, f"{get_column_letter(wc)}{wr}")
            except Exception:
                pass
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)
    return output_path


def _infer_n(wb) -> int:
    ws = wb["纹波与稳压精度测试"]
    n = 0
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=10, column=c).value
        if v and "Vout" in str(v):
            n += 1
    return n
