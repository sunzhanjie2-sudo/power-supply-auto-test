import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QGroupBox,
    QProgressBar, QSpinBox, QDoubleSpinBox, QSplitter,
    QHeaderView, QMessageBox, QAction, QMenuBar, QStatusBar,
    QFileDialog, QCheckBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QFont

from ..communication.serial_comm import InstrumentManager
from ..instruments.power_supply import PowerSupply
from ..instruments.electronic_load import ElectronicLoad
from ..instruments.oscilloscope import Oscilloscope
from ..test_engine.timing_engine import TimingEngine, TimingSequence, TimingStep
from ..test_engine.test_cases import TestGenerator, PowerSupplyParams


class InstrumentDebugWidget(QWidget):
    def __init__(self, instrument_manager):
        super().__init__()
        self.instrument_manager = instrument_manager
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.instrument_combo = QComboBox()
        self.refresh_btn = QPushButton("刷新仪器列表")
        self.refresh_btn.clicked.connect(self.refresh_instruments)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("选择仪器:"))
        top_layout.addWidget(self.instrument_combo)
        top_layout.addWidget(self.refresh_btn)
        layout.addLayout(top_layout)

        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("输入SCPI命令，如: *IDN?")
        self.send_btn = QPushButton("发送命令")
        self.send_btn.clicked.connect(self.send_command)

        cmd_layout = QHBoxLayout()
        cmd_layout.addWidget(QLabel("命令:"))
        cmd_layout.addWidget(self.command_input)
        cmd_layout.addWidget(self.send_btn)
        layout.addLayout(cmd_layout)

        self.response_text = QTextEdit()
        self.response_text.setReadOnly(True)
        layout.addWidget(self.response_text)

        self.info_group = QGroupBox("仪器信息")
        info_layout = QVBoxLayout()
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        self.info_group.setLayout(info_layout)
        layout.addWidget(self.info_group)

        self.setLayout(layout)
        self.refresh_instruments()

    def refresh_instruments(self):
        self.instrument_combo.clear()
        instruments = self.instrument_manager.detect_instruments()
        for port, info in instruments.items():
            self.instrument_combo.addItem(
                f"{info['instrument_type']} - {port}",
                {'port': port, 'type': info['instrument_type']}
            )
            self.info_text.append(f"检测到: {info['idn']} ({port})")

    def send_command(self):
        command = self.command_input.text().strip()
        if not command:
            return

        current_data = self.instrument_combo.currentData()
        if not current_data:
            self.response_text.append("请先选择仪器")
            return

        port = current_data['port']
        comm = self.instrument_manager.get_instrument(port)
        if not comm:
            comm = self.instrument_manager.instruments.get(port)
            if not comm:
                comm_inst = InstrumentManager()
                comm_inst.add_instrument(port, port, current_data['type'])
                comm = comm_inst.get_instrument(port)

        self.response_text.append(f">> {command}")
        response = self.instrument_manager.send_to_instrument(port, command, wait_response=True)
        if response:
            self.response_text.append(f"<< {response}")
        else:
            self.response_text.append("<< 无响应")


class TimingEditorWidget(QWidget):
    def __init__(self, timing_engine):
        super().__init__()
        self.timing_engine = timing_engine
        self.current_sequence = TimingSequence()
        self.step_id_counter = 1
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        toolbar_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存时序")
        self.load_btn = QPushButton("加载时序")
        self.run_btn = QPushButton("运行时序")
        self.stop_btn = QPushButton("停止")
        self.clear_btn = QPushButton("清空")

        self.save_btn.clicked.connect(self.save_sequence)
        self.load_btn.clicked.connect(self.load_sequence)
        self.run_btn.clicked.connect(self.run_sequence)
        self.stop_btn.clicked.connect(self.stop_sequence)
        self.clear_btn.clicked.connect(self.clear_sequence)

        toolbar_layout.addWidget(self.save_btn)
        toolbar_layout.addWidget(self.load_btn)
        toolbar_layout.addWidget(self.run_btn)
        toolbar_layout.addWidget(self.stop_btn)
        toolbar_layout.addWidget(self.clear_btn)
        layout.addLayout(toolbar_layout)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.step_table = QTableWidget()
        self.step_table.setColumnCount(6)
        self.step_table.setHorizontalHeaderLabels([
            "步骤ID", "仪器", "命令", "参数", "延迟(ms)", "描述"
        ])
        self.step_table.horizontalHeader().setStretchLastSection(True)
        self.step_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.step_table)

        editor_group = QGroupBox("添加步骤")
        editor_layout = QFormLayout()

        self.instrument_combo = QComboBox()
        self.instrument_combo.addItems(["power_supply", "electronic_load", "oscilloscope"])

        self.command_combo = QComboBox()
        self.update_commands()
        self.instrument_combo.currentTextChanged.connect(self.update_commands)

        self.params_input = QLineEdit()
        self.params_input.setPlaceholderText("参数，如: voltage=30")

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0, 10000)
        self.delay_spin.setSuffix(" ms")

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("步骤描述")

        editor_layout.addRow("仪器:", self.instrument_combo)
        editor_layout.addRow("命令:", self.command_combo)
        editor_layout.addRow("参数:", self.params_input)
        editor_layout.addRow("延迟:", self.delay_spin)
        editor_layout.addRow("描述:", self.description_input)

        add_btn = QPushButton("添加步骤")
        add_btn.clicked.connect(self.add_step)
        editor_layout.addRow(add_btn)

        editor_group.setLayout(editor_layout)
        layout.addWidget(editor_group)

        self.setLayout(layout)

    def update_commands(self):
        instrument = self.instrument_combo.currentText()
        commands = {
            "power_supply": [
                "set_voltage", "set_current", "get_voltage", "get_current",
                "enable_output", "disable_output", "set_overvoltage_protection",
                "set_overcurrent_protection", "reset"
            ],
            "electronic_load": [
                "set_mode", "set_current", "set_voltage", "set_resistance",
                "set_power", "get_voltage", "get_current", "enable_input",
                "disable_input", "set_dynamic_params", "start_dynamic",
                "stop_dynamic", "reset"
            ],
            "oscilloscope": [
                "set_channel_enable", "set_channel_scale", "set_timebase_scale",
                "set_trigger_mode", "set_trigger_source", "set_trigger_level",
                "set_acquisition_mode", "save_waveform", "run", "stop", "reset"
            ]
        }
        self.command_combo.clear()
        self.command_combo.addItems(commands.get(instrument, []))

    def add_step(self):
        instrument = self.instrument_combo.currentText()
        command = self.command_combo.currentText()
        params_str = self.params_input.text().strip()
        delay = self.delay_spin.value() / 1000.0
        description = self.description_input.text().strip()

        params = {}
        if params_str:
            for part in params_str.split(','):
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    try:
                        params[key] = float(value)
                    except ValueError:
                        params[key] = value

        step = TimingStep(
            step_id=self.step_id_counter,
            instrument=instrument,
            command=command,
            parameters=params,
            delay=delay,
            description=description
        )

        self.current_sequence.add_step(step)
        self.step_id_counter += 1
        self.update_step_table()

        self.params_input.clear()
        self.description_input.clear()

    def update_step_table(self):
        self.step_table.setRowCount(len(self.current_sequence.steps))
        for i, step in enumerate(self.current_sequence.steps):
            self.step_table.setItem(i, 0, QTableWidgetItem(str(step.step_id)))
            self.step_table.setItem(i, 1, QTableWidgetItem(step.instrument))
            self.step_table.setItem(i, 2, QTableWidgetItem(step.command))
            params_str = ", ".join(f"{k}={v}" for k, v in step.parameters.items())
            self.step_table.setItem(i, 3, QTableWidgetItem(params_str))
            self.step_table.setItem(i, 4, QTableWidgetItem(f"{step.delay * 1000:.0f}"))
            self.step_table.setItem(i, 5, QTableWidgetItem(step.description))

    def save_sequence(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "保存时序", "", "JSON文件 (*.json)")
        if filepath:
            self.current_sequence.save_to_file(filepath)
            QMessageBox.information(self, "保存成功", f"时序已保存到: {filepath}")

    def load_sequence(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "加载时序", "", "JSON文件 (*.json)")
        if filepath:
            self.current_sequence = TimingSequence.load_from_file(filepath)
            self.step_id_counter = max([s.step_id for s in self.current_sequence.steps], default=0) + 1
            self.update_step_table()
            QMessageBox.information(self, "加载成功", f"时序已从: {filepath} 加载")

    def run_sequence(self):
        if not self.current_sequence.steps:
            QMessageBox.warning(self, "警告", "没有可运行的步骤")
            return

        self.timing_engine.run_sequence(self.current_sequence)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        def progress_callback(current, total, message):
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)

        def completion_callback(success, message):
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            QMessageBox.information(self, "执行完成", message)

        self.timing_engine.set_progress_callback(progress_callback)
        self.timing_engine.set_completion_callback(completion_callback)

    def stop_sequence(self):
        self.timing_engine.stop()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def clear_sequence(self):
        self.current_sequence = TimingSequence()
        self.step_id_counter = 1
        self.update_step_table()


class TestCaseGeneratorWidget(QWidget):
    def __init__(self, timing_engine):
        super().__init__()
        self.timing_engine = timing_engine
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        params_group = QGroupBox("电源参数设置")
        params_layout = QFormLayout()

        self.vin_min_spin = QDoubleSpinBox()
        self.vin_min_spin.setRange(0, 1000)
        self.vin_min_spin.setValue(90)
        self.vin_min_spin.setSuffix(" V")

        self.vin_typ_spin = QDoubleSpinBox()
        self.vin_typ_spin.setRange(0, 1000)
        self.vin_typ_spin.setValue(120)
        self.vin_typ_spin.setSuffix(" V")

        self.vin_max_spin = QDoubleSpinBox()
        self.vin_max_spin.setRange(0, 1000)
        self.vin_max_spin.setValue(150)
        self.vin_max_spin.setSuffix(" V")

        self.iout_board_spin = QDoubleSpinBox()
        self.iout_board_spin.setRange(0, 100)
        self.iout_board_spin.setValue(0.1)
        self.iout_board_spin.setSuffix(" A")

        self.iout_full_spin = QDoubleSpinBox()
        self.iout_full_spin.setRange(0, 100)
        self.iout_full_spin.setValue(1.0)
        self.iout_full_spin.setSuffix(" A")

        self.iout_overload_spin = QDoubleSpinBox()
        self.iout_overload_spin.setRange(0, 100)
        self.iout_overload_spin.setValue(1.2)
        self.iout_overload_spin.setSuffix(" A")

        params_layout.addRow("Vin_min:", self.vin_min_spin)
        params_layout.addRow("Vin_typ:", self.vin_typ_spin)
        params_layout.addRow("Vin_max:", self.vin_max_spin)
        params_layout.addRow("Iout_板载:", self.iout_board_spin)
        params_layout.addRow("Iout_满载:", self.iout_full_spin)
        params_layout.addRow("Iout_过载:", self.iout_overload_spin)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        region_group = QGroupBox("测试区域选择")
        region_layout = QHBoxLayout()

        self.region_ratings = QCheckBox("额定区")
        self.region_one = QCheckBox("一区")
        self.region_two = QCheckBox("二区")

        region_layout.addWidget(self.region_ratings)
        region_layout.addWidget(self.region_one)
        region_layout.addWidget(self.region_two)
        region_group.setLayout(region_layout)
        layout.addWidget(region_group)

        test_group = QGroupBox("测试项选择")
        test_layout = QVBoxLayout()

        self.test_regulation = QCheckBox("稳压精度测试")
        self.test_power_cycle = QCheckBox("上下电测试")
        self.test_ripple = QCheckBox("纹波测试")
        self.test_dynamic_load = QCheckBox("动态负载测试")
        self.test_dynamic_stability = QCheckBox("动态稳定度测试")
        self.test_short_protection = QCheckBox("短路保护测试")

        test_layout.addWidget(self.test_regulation)
        test_layout.addWidget(self.test_power_cycle)
        test_layout.addWidget(self.test_ripple)
        test_layout.addWidget(self.test_dynamic_load)
        test_layout.addWidget(self.test_dynamic_stability)
        test_layout.addWidget(self.test_short_protection)

        test_group.setLayout(test_layout)
        layout.addWidget(test_group)

        dynamic_params_group = QGroupBox("动态测试参数")
        dynamic_params_layout = QFormLayout()

        self.transition_slope_spin = QDoubleSpinBox()
        self.transition_slope_spin.setRange(0.1, 100)
        self.transition_slope_spin.setValue(1.0)
        self.transition_slope_spin.setSuffix(" A/ms")

        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.001, 10)
        self.period_spin.setValue(0.01)
        self.period_spin.setSuffix(" s")

        dynamic_params_layout.addRow("跳变斜率:", self.transition_slope_spin)
        dynamic_params_layout.addRow("跳变周期:", self.period_spin)

        dynamic_params_group.setLayout(dynamic_params_layout)
        layout.addWidget(dynamic_params_group)

        generate_btn = QPushButton("生成测试用例")
        generate_btn.clicked.connect(self.generate_tests)
        layout.addWidget(generate_btn)

        self.test_list = QTableWidget()
        self.test_list.setColumnCount(2)
        self.test_list.setHorizontalHeaderLabels(["测试名称", "步骤数"])
        self.test_list.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.test_list)

        run_selected_btn = QPushButton("运行选中测试")
        run_selected_btn.clicked.connect(self.run_selected_test)
        layout.addWidget(run_selected_btn)

        self.setLayout(layout)
        self.generated_tests = []

    def generate_tests(self):
        power_params = PowerSupplyParams(
            vin_min=self.vin_min_spin.value(),
            vin_typ=self.vin_typ_spin.value(),
            vin_max=self.vin_max_spin.value(),
            iout_board=self.iout_board_spin.value(),
            iout_full=self.iout_full_spin.value(),
            iout_overload=self.iout_overload_spin.value()
        )

        generator = TestGenerator(power_params)
        self.generated_tests = []

        if self.region_ratings.isChecked():
            self.generated_tests.extend(generator.generate_region_tests("额定区"))
        if self.region_one.isChecked():
            self.generated_tests.extend(generator.generate_region_tests("一区"))
        if self.region_two.isChecked():
            self.generated_tests.extend(generator.generate_region_tests("二区"))

        if self.test_regulation.isChecked():
            self.generated_tests.append(generator.generate_regulation_test())
        if self.test_power_cycle.isChecked():
            self.generated_tests.append(generator.generate_power_cycle_test())
        if self.test_ripple.isChecked():
            self.generated_tests.append(generator.generate_ripple_test())
        if self.test_dynamic_load.isChecked():
            self.generated_tests.append(generator.generate_dynamic_load_test(
                transition_slope=self.transition_slope_spin.value(),
                period=self.period_spin.value()
            ))
        if self.test_dynamic_stability.isChecked():
            self.generated_tests.append(generator.generate_dynamic_stability_test(
                period=self.period_spin.value()
            ))
        if self.test_short_protection.isChecked():
            self.generated_tests.append(generator.generate_short_protection_test())

        self.update_test_list()
        QMessageBox.information(self, "生成完成", f"已生成 {len(self.generated_tests)} 个测试用例")

    def update_test_list(self):
        self.test_list.setRowCount(len(self.generated_tests))
        for i, test in enumerate(self.generated_tests):
            self.test_list.setItem(i, 0, QTableWidgetItem(test.name))
            self.test_list.setItem(i, 1, QTableWidgetItem(str(len(test.steps))))

    def run_selected_test(self):
        selected_rows = self.test_list.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请选择要运行的测试")
            return

        row = selected_rows[0].row()
        test_sequence = self.generated_tests[row]

        self.timing_engine.run_sequence(test_sequence)

        def completion_callback(success, message):
            QMessageBox.information(self, "执行完成", f"{test_sequence.name}: {message}")

        self.timing_engine.set_completion_callback(completion_callback)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("电源自动测试系统")
        self.setGeometry(100, 100, 1200, 800)

        self.instrument_manager = InstrumentManager()
        self.timing_engine = TimingEngine()

        self.init_instruments()
        self.init_ui()

    def init_instruments(self):
        instruments = self.instrument_manager.detect_instruments()
        for port, info in instruments.items():
            comm = self.instrument_manager.get_instrument(port)
            if info['instrument_type'] == 'power_supply':
                ps = PowerSupply(comm)
                ps.connect()
                self.timing_engine.register_instrument('power_supply', ps)
            elif info['instrument_type'] == 'electronic_load':
                el = ElectronicLoad(comm)
                el.connect()
                self.timing_engine.register_instrument('electronic_load', el)
            elif info['instrument_type'] == 'oscilloscope':
                scope = Oscilloscope(comm)
                scope.connect()
                self.timing_engine.register_instrument('oscilloscope', scope)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        tab_widget = QTabWidget()

        self.debug_widget = InstrumentDebugWidget(self.instrument_manager)
        tab_widget.addTab(self.debug_widget, "仪器调试")

        self.timing_widget = TimingEditorWidget(self.timing_engine)
        tab_widget.addTab(self.timing_widget, "时序编辑")

        self.test_widget = TestCaseGeneratorWidget(self.timing_engine)
        tab_widget.addTab(self.test_widget, "自动测试")

        layout = QVBoxLayout()
        layout.addWidget(tab_widget)
        central_widget.setLayout(layout)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("系统就绪")

        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        instrument_menu = menubar.addMenu("仪器")
        refresh_action = QAction("刷新仪器", self)
        refresh_action.triggered.connect(self.debug_widget.refresh_instruments)
        instrument_menu.addAction(refresh_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def show_about(self):
        QMessageBox.about(self, "关于", "电源自动测试系统 v1.0\n\n支持仪器:\n- 电源供应器 (SPM系列)\n- 电子负载仪 (UTL8200系列)\n- 示波器 (DS1000E系列)\n\n通信协议: SCPI")

    def closeEvent(self, event):
        self.timing_engine.stop()
        self.instrument_manager.close_all()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()