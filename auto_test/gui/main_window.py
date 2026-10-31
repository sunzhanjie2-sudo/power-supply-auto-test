from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QMessageBox, QStatusBar, QAction, QFileDialog
)
from PyQt5.QtCore import Qt
from .config_panel import ConfigPanel
from .debug_panel import DebugPanel
from .case_panel import CasePanel
from .waveform_window import WaveformWindow
from ..communication.serial_comm import InstrumentManager
from ..instruments import PowerSupply, ElectronicLoad, Oscilloscope, TempChamber
from ..config.project_config import ProjectConfig


class MainWindow(QMainWindow):
    """辅助电源研发版全量自动化测试上位机"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("辅助电源研发版全量自动化测试上位机")
        self.setMinimumSize(1200, 800)

        self.manager = InstrumentManager()
        self.instruments = {}
        self.waveform_window = None
        self._debug_scope = None

        self._setup_menu()
        self._setup_ui()
        self._setup_statusbar()

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        act_new = QAction("新建工程", self)
        act_new.triggered.connect(self._new_project)
        file_menu.addAction(act_new)

        act_open = QAction("打开工程", self)
        act_open.triggered.connect(self._open_project)
        file_menu.addAction(act_open)

        act_save = QAction("保存工程", self)
        act_save.triggered.connect(self._save_project)
        file_menu.addAction(act_save)

        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        help_menu.addAction(act_about)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 标题
        title = QLabel("辅助电源研发版全量自动化测试上位机")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 标签页
        self.tab = QTabWidget()

        self.config_panel = ConfigPanel()
        self.tab.addTab(self.config_panel, "配置")

        self.debug_panel = DebugPanel()
        self.tab.addTab(self.debug_panel, "仪器调试")

        self.case_panel = CasePanel()
        self.case_panel.set_config_getter(self.config_panel.get_config)
        self.case_panel.before_test_start = self._pause_live_preview
        self.tab.addTab(self.case_panel, "用例测试")

        layout.addWidget(self.tab)

        # 底部快速操作栏
        quick_layout = QHBoxLayout()
        self.btn_connect_all = QPushButton("一键连接仪器")
        self.btn_connect_all.clicked.connect(self._connect_all_instruments)
        self.btn_gen_case = QPushButton("生成测试用例")
        self.btn_gen_case.clicked.connect(self._generate_test_case)
        self.btn_waveform = QPushButton("实时波形")
        self.btn_waveform.clicked.connect(self._open_waveform)
        quick_layout.addWidget(self.btn_connect_all)
        quick_layout.addWidget(self.btn_gen_case)
        quick_layout.addWidget(self.btn_waveform)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)

    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪 | 仪器未连接")

    def _connect_all_instruments(self):
        """一键连接所有仪器，支持USB-TMC和串口设备"""
        if self.case_panel.executor and self.case_panel.executor.running:
            QMessageBox.warning(self, "测试进行中", "测试结束后再重新连接仪器。")
            return
        if not self._pause_live_preview():
            QMessageBox.warning(self, "示波器忙", "实时波形读取尚未结束，请稍后重试。")
            return
        self.manager.close_all()
        self.instruments.clear()
        self.statusbar.showMessage("正在扫描仪器...")
        detected = self.manager.detect_instruments()

        if not detected:
            QMessageBox.warning(self, "提示", "自动扫描未发现仪器，请检查设备连接或使用仪器调试面板手动连接")
            self.statusbar.showMessage("扫描完成 - 未发现仪器")
            return

        connected_count = 0
        detected_info = {}

        for port, info in detected.items():
            itype = info["instrument_type"]
            comm_type = info.get("comm_type", "serial")
            baud_rate = info.get("baud_rate", 9600)
            name = f"{itype}_{port}"
            self.manager.add_instrument(name, port, itype, comm_type, baud_rate)

            comm = self.manager.get_instrument(name)
            if comm and comm.is_connected:
                detected_info[itype] = {
                    'comm': comm,
                    'info': info
                }
                connected_count += 1

        # 创建仪器对象
        if 'power_supply' in detected_info:
            self.instruments["power_supply"] = PowerSupply(detected_info['power_supply']['comm'])
            self.instruments["power_supply"].connect()

        if 'electronic_load' in detected_info:
            self.instruments["electronic_load"] = ElectronicLoad(detected_info['electronic_load']['comm'])
            self.instruments["electronic_load"].connect()

        if 'oscilloscope' in detected_info:
            self.instruments["oscilloscope"] = Oscilloscope(detected_info['oscilloscope']['comm'])
            self.instruments["oscilloscope"].connect()

        # 温箱预留
        self.instruments["temp_chamber"] = TempChamber()

        # 注入用例测试面板
        self.case_panel.set_instruments(self.instruments)
        self.case_panel.refresh_info()
        if self.waveform_window and 'oscilloscope' in self.instruments:
            self.waveform_window.set_scope(self.instruments['oscilloscope'])

        # 显示连接信息
        msg = f"已连接 {connected_count} 个仪器:"
        if 'oscilloscope' in detected_info:
            msg += f" 示波器({detected_info['oscilloscope']['info']['port']})"
        if 'electronic_load' in detected_info:
            msg += f" 负载仪({detected_info['electronic_load']['info']['port']})"
        if 'power_supply' in detected_info:
            msg += f" 电源({detected_info['power_supply']['info']['port']})"

        self.statusbar.showMessage(msg)
        self.btn_connect_all.setStyleSheet("background-color: #C6EFCE;")

        QMessageBox.information(self, "连接成功", msg)

    def _generate_test_case(self):
        """跳转到「用例测试」页并按当前配置生成黑盒测试用例 Excel"""
        self.tab.setCurrentWidget(self.case_panel)
        self.case_panel.generate_case()

    def _open_waveform(self):
        if self.waveform_window is None:
            self.waveform_window = WaveformWindow(self)
        scope = self.instruments.get("oscilloscope")
        if scope is None:
            widget = self.debug_panel.scope_widget
            if widget._comm and widget._comm.is_connected:
                if self._debug_scope is None or self._debug_scope.comm is not widget._comm:
                    self._debug_scope = Oscilloscope(widget._comm)
                    self._debug_scope.connect()
                scope = self._debug_scope
        if scope is not None:
            self.waveform_window.set_scope(scope)
        self.waveform_window.show()
        self.waveform_window.raise_()
        self.waveform_window.activateWindow()
        if scope is not None and not (self.case_panel.executor and self.case_panel.executor.running):
            self.waveform_window.start_preview()
        elif scope is not None:
            self.waveform_window.status.setText("测试进行中，预览已暂停")

    def _pause_live_preview(self):
        return self.waveform_window is None or self.waveform_window.stop_preview()

    def _new_project(self):
        self.config_panel.reset_to_defaults()
        self.case_panel.refresh_info()
        self.statusbar.showMessage("新建工程")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "JSON Files (*.json)")
        if path:
            cfg = ProjectConfig.load(path)
            self.config_panel.set_config(cfg)
            self.case_panel.refresh_info()
            self.statusbar.showMessage(f"已打开: {path}")

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存工程", "", "JSON Files (*.json)")
        if path:
            cfg = self.config_panel.get_config()
            cfg.save(path)
            self.statusbar.showMessage(f"已保存: {path}")

    def closeEvent(self, event):
        if not self._pause_live_preview():
            event.ignore()
            return
        if not self.case_panel.shutdown():
            self.statusbar.showMessage("等待当前工况安全结束后再关闭窗口")
            event.ignore()
            return
        if not self.debug_panel.shutdown():
            self.statusbar.showMessage("等待仪器扫描结束后再关闭窗口")
            event.ignore()
            return
        if self.waveform_window:
            self.waveform_window.close()
        self.manager.close_all()
        event.accept()
