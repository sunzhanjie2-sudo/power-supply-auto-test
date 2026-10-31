# -*- coding: utf-8 -*-
"""GUI 可用性验证脚本（程序化驱动 PyQt5 界面）。

无需人工点击：通过触发控件信号（.click()/.setCurrentText() 等）驱动界面，
逐项检查控件存在性、默认值、信号连接、状态流转，并捕获异常。

运行：python gui_test.py
"""
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog, QTabWidget, QTableWidget
from PyQt5.QtCore import Qt

# —— 捕获模态对话框文案（同时屏蔽阻塞）——
DIALOGS = []  # 记录 (类型, 标题, 正文)


def _capture(kind):
    def _fn(*args, **kwargs):
        # 标准签名：QMessageBox.xxx(parent, title, text, ...)
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        DIALOGS.append((kind, str(title), str(text)))
        return QMessageBox.Ok
    return staticmethod(_fn)


QMessageBox.information = _capture("information")
QMessageBox.warning = _capture("warning")
QMessageBox.critical = _capture("critical")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")

from auto_test.gui.main_window import MainWindow


class GuiTest:
    def __init__(self):
        self.results = []
        self.failures = 0

    def check(self, name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        if not condition:
            self.failures += 1
        self.results.append((name, status, detail))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ->  {detail}" if detail else ""))

    def run(self):
        app = QApplication.instance() or QApplication(sys.argv)
        print("=" * 64)
        print("GUI 可用性验证")
        print("=" * 64)

        # 1. 主窗口构建
        print("\n【1. 主窗口与布局】")
        try:
            w = MainWindow()
            w.show()
            app.processEvents()
            self.check("主窗口实例化", True)
            self.check("窗口标题", "辅助电源" in w.windowTitle(), w.windowTitle())
            self.check("最小尺寸 >= 1200x800", w.minimumWidth() >= 1200 and w.minimumHeight() >= 800,
                       f"{w.minimumWidth()}x{w.minimumHeight()}")
            self.check("窗口可见", w.isVisible())
            self.check("标签页数量 = 3", w.tab.count() == 3, f"{w.tab.count()} 个")
            titles = [w.tab.tabText(i) for i in range(w.tab.count())]
            self.check("标签页标题", titles == ["配置", "仪器调试", "用例测试"], str(titles))
            self.check("存在 btn_connect_all", hasattr(w, "btn_connect_all"))
            self.check("存在实时波形入口", hasattr(w, "btn_waveform"))
            self.check("用例测试面板实例", w.case_panel is not None)
            self.check("用例测试控件", all(hasattr(w.case_panel, a) for a in
                                         ("btn_generate", "btn_start", "spin_temp", "table", "log")))
        except Exception as e:
            self.check("主窗口构建", False, f"{e}\n{traceback.format_exc()}")
            return

        # 2. 配置面板
        print("\n【2. 配置面板】")
        cp = w.config_panel
        try:
            self.check("配置面板实例", cp is not None)
            self.check("配置子页数量 = 4", cp.findChild(QTabWidget).count() == 4)
            self.check("样机型号默认值", cp.edit_model.text() == "新样机", cp.edit_model.text())
            self.check("输出类型默认", cp.cmb_output_type.currentText() == "1路输出", cp.cmb_output_type.currentText())
            self.check("输出根目录控件", hasattr(cp, "edit_output_root"))
            # 通道表默认 1 行
            self.check("通道表默认 1 行", cp.table_channels.rowCount() == 1, f"{cp.table_channels.rowCount()} 行")
            # 测试项默认 3 项
            self.check("测试项默认 3 项", cp.table_test_items.rowCount() == 3, f"{cp.table_test_items.rowCount()} 项")

            # 输出类型切换 -> 通道表联动
            cp.cmb_output_type.setCurrentText("3路输出")
            app.processEvents()
            self.check("输出类型3路 -> 通道表3行", cp.table_channels.rowCount() == 3, f"{cp.table_channels.rowCount()} 行")
            cp.cmb_output_type.setCurrentText("1路输出")
            app.processEvents()
            self.check("输出类型1路 -> 通道表1行", cp.table_channels.rowCount() == 1, f"{cp.table_channels.rowCount()} 行")

            # get_config 返回完整配置
            cfg = cp.get_config()
            self.check("get_config 返回 ProjectConfig", cfg is not None)
            self.check("get_config 通道数", len(cfg.output_channels) == 1, str(len(cfg.output_channels)))
            self.check("get_config 测试项数", len(cfg.test_items) == 3, str(len(cfg.test_items)))
            self.check("get_config 边界 Vin", cfg.boundary.vin_list == [36.0, 42.0, 48.0], str(cfg.boundary.vin_list))
            self.check("配置不含拓扑字段", not hasattr(cfg, "topology"))

            # 配置序列化往返
            import json
            d = cfg.to_dict()
            self.check("配置 to_dict 可 JSON 序列化", json.dumps(d, ensure_ascii=False) is not None)
            from auto_test.config.project_config import ProjectConfig
            cfg2 = ProjectConfig.from_dict(d)
            self.check("配置 from_dict 往返", cfg2.model_name == cfg.model_name and len(cfg2.test_items) == 3)
        except Exception as e:
            self.check("配置面板测试", False, f"{e}\n{traceback.format_exc()}")

        # 3. 仪器调试面板
        print("\n【3. 仪器调试面板】")
        dp = w.debug_panel
        try:
            self.check("调试面板实例", dp is not None)
            self.check("调试子页数量 = 4", dp.tab_widget.count() == 4, f"{dp.tab_widget.count()} 个")
            tabs = [dp.tab_widget.tabText(i) for i in range(dp.tab_widget.count())]
            self.check("调试子页标题", tabs == ["示波器", "直流电源", "电子负载", "温箱"], str(tabs))
            self.check("示波器默认通信 VISA", dp.scope_widget.cmb_comm_type.currentText() == "VISA")
            self.check("负载默认波特率 9600", dp.load_widget.cmb_baud.currentText() == "9600")
            self.check("电源默认波特率 115200", dp.power_widget.cmb_baud.currentText() == "115200")

            # 串口扫描
            from auto_test.communication.serial_comm import SerialComm
            ports = SerialComm.list_ports()
            self.check("串口扫描返回列表", isinstance(ports, list) and len(ports) >= 0, f"{len(ports)} 个端口")
            # 刷新到下拉框
            dp.scope_widget._refresh_ports()
            self.check("示波器端口下拉已填充", dp.scope_widget.cmb_port.count() > 0, f"{dp.scope_widget.cmb_port.count()} 项")
        except Exception as e:
            self.check("调试面板测试", False, f"{e}\n{traceback.format_exc()}")

        # 4. 一键连接仪器（真实扫描+连接）
        print("\n【4. 一键连接仪器（真实硬件）】")
        try:
            # 输出根目录改到工作区，避免写 D: 盘
            cp.edit_output_root.setText(os.path.join(os.getcwd(), "test_reports", "gui_output"))
            n_dialogs_before = len(DIALOGS)
            w.btn_connect_all.click()
            app.processEvents()
            has_ps = "power_supply" in w.instruments
            has_load = "electronic_load" in w.instruments
            has_scope = "oscilloscope" in w.instruments
            self.check("直流源已连接", has_ps)
            self.check("电子负载已连接", has_load)
            self.check("示波器已连接", has_scope)
            self.check("仪器对象已创建", w.instruments.get("power_supply") is not None)

            # 前端细节：连接成功按钮变绿
            style = w.btn_connect_all.styleSheet()
            self.check("连接成功按钮变绿反馈", "#C6EFCE" in style, style or "(无样式)")

            # 前端细节：成功弹窗文案
            new_dialogs = DIALOGS[n_dialogs_before:]
            info_texts = [t for _, _, t in new_dialogs]
            success_dialog = any("已连接" in t for t in info_texts)
            self.check("连接成功弹窗文案", success_dialog, str(info_texts) if info_texts else "(无弹窗)")
            self.check("连接成功弹窗含仪器名", any("示波器" in t or "负载" in t or "电源" in t for t in info_texts),
                       str(info_texts))

            w.btn_waveform.click()
            app.processEvents()
            self.check("实时波形窗口打开", w.waveform_window is not None and w.waveform_window.isVisible())
            self.check("实时波形复用示波器连接", w.waveform_window._scope is w.instruments.get("oscilloscope"))
            from auto_test.waveforms.ui.scope_view import ScopeView
            self.check("实时波形使用 ScopeHost 绘图控件", isinstance(w.waveform_window.view, ScopeView))
            w.waveform_window.close()
        except Exception as e:
            self.check("一键连接", False, f"{e}\n{traceback.format_exc()}")

        # 5. 用例测试面板（不执行真机测试，仅验证面板状态）
        print("\n【5. 用例测试面板】")
        try:
            cp2 = w.case_panel
            self.check("仪器已注入", cp2.instruments.get("power_supply") is not None)
            self.check("环温输入默认 25", abs(cp2.spin_temp.value() - 25.0) < 0.01, str(cp2.spin_temp.value()))
            self.check("开始按钮可用", cp2.btn_start.isEnabled())
            self.check("暂停/停止默认禁用", not cp2.btn_pause.isEnabled() and not cp2.btn_stop.isEnabled())
            self.check("工况表列数 = 11", cp2.table.columnCount() == 11, f"{cp2.table.columnCount()} 列")
            self.check("日志框只读", cp2.log.isReadOnly())
            self.check("存在工况波形入口", hasattr(cp2, "btn_waveform"))
            self.check("未执行时工况波形按钮禁用", not cp2.btn_waveform.isEnabled())
            self.check("历史波形入口可用", cp2.btn_history_waveform.isEnabled())
        except Exception as e:
            self.check("用例测试面板", False, f"{e}\n{traceback.format_exc()}")

        # 汇总
        total = len(self.results)
        passed = sum(1 for _, s, _ in self.results if s == "PASS")
        print("\n" + "=" * 64)
        print(f"GUI 验证结果：{passed}/{total} 通过，{self.failures} 失败")
        print("=" * 64)
        return self.failures == 0


def run_selftest():
    """供 main.py --selftest 调用：无头运行 GUI 可用性验证，返回进程退出码。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t = GuiTest()
    return 0 if t.run() else 1


if __name__ == "__main__":
    sys.exit(run_selftest())
