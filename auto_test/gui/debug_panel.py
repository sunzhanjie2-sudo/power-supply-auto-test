import sys
import re
import time
import serial
from serial import PARITY_NONE, STOPBITS_ONE, EIGHTBITS
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QTextEdit, QGroupBox, QMessageBox, QProgressBar,
    QSpacerItem, QSizePolicy, QStatusBar, QTabWidget, QLineEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from ..communication.serial_comm import SerialComm


class ScanThread(QThread):
    scan_finished = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def __init__(self, scan_type, parent=None):
        super().__init__(parent)
        self.scan_type = scan_type

    def run(self):
        try:
            if self.scan_type == "visa":
                from ..communication.visa_comm import VisaComm
                devices = VisaComm.list_devices()
                self.scan_finished.emit(devices)
            elif self.scan_type == "usbtmc":
                from ..communication.usbtmc_ctypes import UsbtmcCtypes
                devices = UsbtmcCtypes.list_devices()
                self.scan_finished.emit(devices)
            elif self.scan_type == "serial":
                ports = SerialComm.list_ports()
                self.scan_finished.emit(ports)
        except Exception as e:
            self.scan_error.emit(str(e))


class AutoConnectThread(QThread):
    connect_found = pyqtSignal(str, int)
    connect_finished = pyqtSignal(bool)
    progress_update = pyqtSignal(str)

    def __init__(self, ports, parent=None):
        super().__init__(parent)
        self.ports = ports
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        baud_rates = [9600, 19200, 38400, 57600, 115200]
        commands = ["*IDN?", "IDN?", "FUNC?", "INP?", "STATUS?"]

        for port in self.ports:
            if not self._running:
                break
            self.progress_update.emit(f"尝试端口: {port}")

            for baud in baud_rates:
                if not self._running:
                    break
                try:
                    ser = serial.Serial(
                        port=port,
                        baudrate=baud,
                        parity=PARITY_NONE,
                        stopbits=STOPBITS_ONE,
                        bytesize=EIGHTBITS,
                        timeout=0.5,
                        write_timeout=0.5
                    )

                    if ser.is_open:
                        time.sleep(0.2)
                        ser.reset_input_buffer()

                        for cmd in commands:
                            if not self._running:
                                break
                            ser.write((cmd + '\r\n').encode('utf-8'))
                            ser.flush()
                            time.sleep(0.2)

                            if ser.in_waiting > 0:
                                response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                                if response.strip():
                                    ser.close()
                                    self.connect_found.emit(port, baud)
                                    self.connect_finished.emit(True)
                                    return

                            ser.reset_input_buffer()

                        ser.close()
                except:
                    pass

        self.connect_finished.emit(False)


class InstrumentDebugWidget(QWidget):
    def __init__(self, instrument_name: str, instrument_type: str, parent=None):
        super().__init__(parent)
        self.instrument_name = instrument_name
        self.instrument_type = instrument_type
        self._connected = False
        self._port = ""
        self._comm_type = ""
        self._comm = None
        self._scan_thread = None
        self._auto_connect_thread = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        comm_group = QGroupBox(f"{self.instrument_name} - 通信设置")
        comm_layout = QFormLayout(comm_group)

        self.cmb_comm_type = QComboBox()
        self.cmb_comm_type.addItems(["串口(Serial)", "USB-TMC", "VISA"])
        self.cmb_comm_type.currentIndexChanged.connect(self._on_comm_type_changed)

        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(300)

        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])

        comm_layout.addRow("通信类型:", self.cmb_comm_type)
        comm_layout.addRow("端口/资源:", self.cmb_port)
        comm_layout.addRow("波特率:", self.cmb_baud)

        btn_layout = QHBoxLayout()
        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_disconnect.setEnabled(False)
        self.btn_scan = QPushButton("扫描")
        self.btn_scan.clicked.connect(self._scan_ports)
        self.btn_auto_connect = QPushButton("自动连接")
        self.btn_auto_connect.clicked.connect(self._auto_connect)

        btn_layout.addWidget(self.btn_connect)
        btn_layout.addWidget(self.btn_disconnect)
        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_auto_connect)
        comm_layout.addRow(btn_layout)

        layout.addWidget(comm_group)

        self.status_label = QLabel("状态: 未连接")
        self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(15)
        layout.addWidget(self.progress_bar)

        cmd_group = QGroupBox(f"{self.instrument_name} - 指令调试")
        cmd_layout = QVBoxLayout(cmd_group)

        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(4)

        quick_cmds = self._get_quick_commands()
        for cmd, label in quick_cmds[:12]:
            btn = QPushButton(label)
            btn.setMaximumWidth(80)
            btn.clicked.connect(lambda checked, c=cmd: self._execute_command(c, wait_response="?" in c))
            quick_layout.addWidget(btn)

        layout1 = QHBoxLayout()
        layout1.addLayout(quick_layout)
        layout1.addStretch()
        cmd_layout.addLayout(layout1)

        if len(quick_cmds) > 12:
            quick_layout2 = QHBoxLayout()
            quick_layout2.setSpacing(4)
            for cmd, label in quick_cmds[12:]:
                btn = QPushButton(label)
                btn.setMaximumWidth(80)
                btn.clicked.connect(lambda checked, c=cmd: self._execute_command(c, wait_response="?" in c))
                quick_layout2.addWidget(btn)

            layout2 = QHBoxLayout()
            layout2.addLayout(quick_layout2)
            layout2.addStretch()
            cmd_layout.addLayout(layout2)

        input_layout = QHBoxLayout()
        self.edit_command = QLineEdit()
        self.edit_command.setPlaceholderText("输入命令...")
        self.edit_command.returnPressed.connect(self._query_command)

        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self._send_command)
        self.btn_query = QPushButton("查询")
        self.btn_query.clicked.connect(self._query_command)

        input_layout.addWidget(self.edit_command)
        input_layout.addWidget(self.btn_send)
        input_layout.addWidget(self.btn_query)
        cmd_layout.addLayout(input_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.log_text.setMaximumHeight(120)
        cmd_layout.addWidget(self.log_text)

        layout.addWidget(cmd_group)

        self._refresh_ports()

    def _get_quick_commands(self):
        if self.instrument_type == "oscilloscope":
            return [
                ("*IDN?", "IDN"),
                ("RUN", "运行"),
                ("STOP", "停止"),
                ("AUTO", "自动"),
                ("*RST", "复位"),
                ("CHAN1:DISP ON", "CH1开"),
                ("CHAN1:DISP OFF", "CH1关"),
                ("CHAN2:DISP ON", "CH2开"),
                ("CHAN2:DISP OFF", "CH2关"),
                ("CHAN1:SCAL 1V", "CH1量程1V"),
                ("CHAN1:SCAL 10V", "CH1量程10V"),
                ("CHAN2:SCAL 1V", "CH2量程1V"),
                ("CHAN2:SCAL 10V", "CH2量程10V"),
                ("TIM:SCAL 100US", "时基100us"),
                ("TIM:SCAL 1MS", "时基1ms"),
                ("TIM:SCAL 10MS", "时基10ms"),
                ("MEAS:VPP? CHAN1", "测量Vpp"),
                ("MEAS:FREQ? CHAN1", "测量频率"),
                ("MEAS:VMAX? CHAN1", "测量Vmax"),
                ("MEAS:VMIN? CHAN1", "测量Vmin"),
                ("MEAS:VRMS? CHAN1", "测量Vrms"),
                ("ACQ:MEMD LONG", "长内存"),
                ("ACQ:MEMD NORM", "正常内存"),
                ("TRIG:MODE AUTO", "触发自动"),
                ("TRIG:MODE NORM", "触发正常"),
                ("TRIG:MODE SING", "触发单次"),
                ("TRIG:SOURCE CHAN1", "触发源CH1"),
                ("TRIG:SOURCE CHAN2", "触发源CH2"),
            ]
        elif self.instrument_type == "power_supply":
            return [
                ("*IDN?", "IDN"),
                ("VOLT?", "查询电压"),
                ("CURR?", "查询电流"),
                ("OUTP?", "查询输出"),
                ("OUTP ON", "输出开"),
                ("OUTP OFF", "输出关"),
                ("VOLT 30", "设电压30V"),
                ("CURR 2", "设电流2A"),
                ("MEAS:VOLT?", "测量电压"),
                ("MEAS:CURR?", "测量电流"),
                ("MEAS:POW?", "测量功率"),
                ("*RST", "复位"),
            ]
        elif self.instrument_type == "electronic_load":
            return [
                ("*IDN?", "IDN"),
                ("FUNC?", "查询模式"),
                ("INP?", "查询输入"),
                ("INP ON", "输入开"),
                ("INP OFF", "输入关"),
                ("FUNC CC", "设CC模式"),
                ("FUNC CV", "设CV模式"),
                ("FUNC CR", "设CR模式"),
                ("FUNC CP", "设CP模式"),
                ("CURR 1", "设电流1A"),
                ("CURR 2", "设电流2A"),
                ("CURR 5", "设电流5A"),
                ("RES 10", "设电阻10Ω"),
                ("RES 5", "设电阻5Ω"),
                ("RES 1", "设电阻1Ω"),
            ]
        elif self.instrument_type == "temp_chamber":
            return [
                ("*IDN?", "IDN"),
                ("TEMP?", "查询温度"),
                ("TEMP 25", "设温度25℃"),
                ("RUN", "运行"),
                ("STOP", "停止"),
                ("STATUS?", "状态"),
            ]
        else:
            return [("*IDN?", "IDN"), ("*RST", "复位")]

    def _refresh_ports(self):
        self.cmb_port.clear()
        ports = SerialComm.list_ports()
        for p in ports:
            self.cmb_port.addItem(f"{p['port']} - {p['description']}")

    def _on_comm_type_changed(self, index):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.wait()

        comm_type = self.cmb_comm_type.currentText()
        self.btn_auto_connect.setEnabled(comm_type == "串口(Serial)")

        if comm_type == "USB-TMC":
            self._start_scan("usbtmc")
        elif comm_type == "VISA":
            self._start_scan("visa")
        else:
            self._refresh_ports()

    def _start_scan(self, scan_type):
        self.progress_bar.setVisible(True)
        self.btn_scan.setEnabled(False)
        self._scan_thread = ScanThread(scan_type)
        self._scan_thread.scan_finished.connect(self._on_scan_finished)
        self._scan_thread.scan_error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_scan_finished(self, devices):
        self.progress_bar.setVisible(False)
        self.btn_scan.setEnabled(True)
        self.cmb_port.clear()

        if self.cmb_comm_type.currentText() == "USB-TMC":
            for dev in devices:
                desc = f"{dev['manufacturer']} {dev['product']}"
                self.cmb_port.addItem(f"{dev['resource']} - {desc}")
            if not devices:
                self.cmb_port.addItem("未发现USB设备")
        elif self.cmb_comm_type.currentText() == "VISA":
            for dev in devices:
                self.cmb_port.addItem(f"{dev['resource']} - {dev['description']}")
            if not devices:
                self.cmb_port.addItem("未发现VISA设备")
        else:
            for port in devices:
                self.cmb_port.addItem(f"{port['port']} - {port['description']}")

    def _on_scan_error(self, error):
        self.progress_bar.setVisible(False)
        self.btn_scan.setEnabled(False)
        self.cmb_port.clear()
        if self.cmb_comm_type.currentText() == "USB-TMC":
            self.cmb_port.addItem(f"USB-TMC初始化失败: {error}")
        else:
            self.cmb_port.addItem(f"VISA初始化失败: {error}")

    def _scan_ports(self):
        self._log(f"=== 开始扫描 {self.instrument_name} ===")
        self._on_comm_type_changed(self.cmb_comm_type.currentIndex())

    def _auto_connect(self):
        if self.cmb_comm_type.currentText() != "串口(Serial)":
            return
        if self._auto_connect_thread and self._auto_connect_thread.isRunning():
            return

        ports = []
        for i in range(self.cmb_port.count()):
            port_text = self.cmb_port.itemText(i)
            if "未发现" not in port_text and "失败" not in port_text:
                ports.append(port_text.split(" - ")[0])

        if not ports:
            self._on_comm_type_changed(self.cmb_comm_type.currentIndex())
            for i in range(self.cmb_port.count()):
                port_text = self.cmb_port.itemText(i)
                if "未发现" not in port_text and "失败" not in port_text:
                    ports.append(port_text.split(" - ")[0])

        if not ports:
            self._log("未发现可用端口")
            return

        self.progress_bar.setVisible(True)
        self.btn_auto_connect.setEnabled(False)
        self._log(f"=== 开始自动连接 {self.instrument_name} ===")

        self._auto_connect_thread = AutoConnectThread(ports)
        self._auto_connect_thread.connect_found.connect(self._on_auto_connect_found)
        self._auto_connect_thread.connect_finished.connect(self._on_auto_connect_finished)
        self._auto_connect_thread.progress_update.connect(self._log)
        self._auto_connect_thread.start()

    def _on_auto_connect_found(self, port, baud):
        self.progress_bar.setVisible(False)
        self.btn_auto_connect.setEnabled(True)

        idx = self.cmb_port.findText(port, Qt.MatchContains)
        if idx >= 0:
            self.cmb_port.setCurrentIndex(idx)
        self.cmb_baud.setCurrentText(str(baud))
        self._log(f"✅ 自动连接成功! 端口={port}, 波特率={baud}")

    def _on_auto_connect_finished(self, success):
        self.progress_bar.setVisible(False)
        self.btn_auto_connect.setEnabled(True)
        if not success:
            self._log("❌ 自动连接失败，未找到响应的设备")

    def _connect(self):
        port_text = self.cmb_port.currentText()
        if not port_text or "未发现" in port_text or "失败" in port_text:
            QMessageBox.warning(self, "提示", "请先选择有效的端口/资源")
            return

        comm_type_text = self.cmb_comm_type.currentText()
        if comm_type_text == "串口(Serial)":
            comm_type = "serial"
        elif comm_type_text == "USB-TMC":
            comm_type = "usbtmc"
        else:
            comm_type = "visa"

        port = port_text.split(" - ")[0]
        baud = int(self.cmb_baud.currentText()) if comm_type == "serial" else 0

        self._log(f"=== 连接 {port} ===")

        try:
            if comm_type == "usbtmc":
                from ..communication.usbtmc_ctypes import UsbtmcCtypes
                comm = UsbtmcCtypes()

                match = re.search(r'USB0::0x([0-9A-Fa-f]{4})::0x([0-9A-Fa-f]{4})', port)
                if match:
                    vid = int(match.group(1), 16)
                    pid = int(match.group(2), 16)
                    self._log(f"尝试连接 USB设备: VID=0x{vid:04X}, PID=0x{pid:04X}")
                    success = comm.connect(vid=vid, pid=pid)
                else:
                    self._log(f"尝试连接默认示波器: VID=0x1AB1, PID=0x0588")
                    success = comm.connect(vid=0x1AB1, pid=0x0588)

            elif comm_type == "visa":
                from ..communication.visa_comm import VisaComm
                comm = VisaComm()
                self._log(f"尝试连接 VISA设备: {port}")
                success = comm.connect(port)

            else:
                comm = SerialComm()
                self._log(f"尝试连接串口: {port}, 波特率={baud}")
                success = comm.connect(port, baud_rate=baud)

            if not success:
                err_msg = comm.last_error if hasattr(comm, 'last_error') else "未知错误"
                self._log(f"连接失败: {err_msg}")
                QMessageBox.critical(self, "连接失败", f"无法连接到 {port}\n{err_msg}")
                return

            idn_response = comm.send_command("*IDN?", wait_response=True)
            self._log(f"IDN响应: {idn_response}")

            self._connected = True
            self._port = port
            self._comm_type = comm_type
            self._comm = comm

            self.btn_connect.setEnabled(False)
            self.btn_disconnect.setEnabled(True)
            self._update_status(True, f"{port} - {(idn_response or '未返回IDN')[:30]}...")

            QMessageBox.information(self, "连接成功", f"已成功连接 {self.instrument_name}\n端口: {port}\nIDN: {idn_response}")

        except Exception as e:
            self._log(f"连接异常: {str(e)}")
            import traceback
            self._log(f"异常详情:\n{traceback.format_exc()}")
            QMessageBox.critical(self, "连接异常", f"连接过程中发生错误:\n{str(e)}")

    def _disconnect(self):
        if hasattr(self, '_comm') and self._comm:
            try:
                if hasattr(self._comm, 'disconnect'):
                    self._comm.disconnect()
            except:
                pass
            self._comm = None

        self._connected = False
        self._port = ""
        self._comm_type = ""

        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self._update_status(False, "未连接")
        self._log(f"已断开连接")

    def _send_command(self):
        self._execute_command(wait_response=False)

    def _query_command(self):
        self._execute_command(wait_response=True)

    def _execute_command(self, command=None, wait_response=True):
        if not self._connected:
            QMessageBox.warning(self, "提示", "请先连接仪器")
            return

        cmd = command or self.edit_command.text().strip()
        if not cmd:
            QMessageBox.warning(self, "提示", "请输入命令")
            return

        try:
            self._log(f">>> {cmd}")
            response = self._comm.send_command(cmd, wait_response=wait_response)
            if response:
                self._log(f"<<< {response}")
            elif wait_response:
                self._log("<<< 无响应")
        except Exception as e:
            self._log(f"命令执行失败: {e}")

    def _update_status(self, connected, message):
        if connected:
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        self.status_label.setText(f"状态: {message}")

    def _log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        scroll_bar = self.log_text.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())


class DebugPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("就绪 | 未连接仪器")
        layout.addWidget(self.status_bar)

        scan_layout = QHBoxLayout()
        btn_scan_all = QPushButton("扫描所有仪器")
        btn_scan_all.clicked.connect(self._scan_all)
        btn_disconnect_all = QPushButton("断开所有")
        btn_disconnect_all.clicked.connect(self._disconnect_all)
        scan_layout.addWidget(btn_scan_all)
        scan_layout.addWidget(btn_disconnect_all)
        scan_layout.addStretch()
        layout.addLayout(scan_layout)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)

        self.scope_widget = InstrumentDebugWidget("示波器", "oscilloscope")
        self.tab_widget.addTab(self.scope_widget, "示波器")

        self.power_widget = InstrumentDebugWidget("直流电源", "power_supply")
        self.tab_widget.addTab(self.power_widget, "直流电源")

        self.load_widget = InstrumentDebugWidget("电子负载", "electronic_load")
        self.tab_widget.addTab(self.load_widget, "电子负载")

        self.chamber_widget = InstrumentDebugWidget("温箱", "temp_chamber")
        self.tab_widget.addTab(self.chamber_widget, "温箱")

        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)

        log_group = QGroupBox("全局日志")
        log_layout = QVBoxLayout(log_group)
        self.global_log = QTextEdit()
        self.global_log.setReadOnly(True)
        self.global_log.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.global_log.setMaximumHeight(80)
        log_layout.addWidget(self.global_log)
        layout.addWidget(log_group)

        self.scope_widget.cmb_comm_type.setCurrentText("VISA")
        self.load_widget.cmb_baud.setCurrentText("9600")
        self.power_widget.cmb_baud.setCurrentText("115200")

        self._log("仪器调试面板已就绪")

    def _on_tab_changed(self, index):
        pass

    def _scan_all(self):
        self._log("=== 开始扫描所有仪器 ===")

        try:
            from ..communication.visa_comm import VisaComm
            visa_devices = VisaComm.list_devices()
            self._log(f"VISA设备: {len(visa_devices)} 个")
            for dev in visa_devices:
                itype = self._identify_by_idn(dev["idn"])
                self._log(f"  发现: {itype} - {dev['resource']}")
                self._auto_select_device(itype, dev['resource'], "visa")

        except Exception as e:
            self._log(f"VISA扫描失败: {e}")

        ports = SerialComm.list_ports()
        self._log(f"串口设备: {len(ports)} 个")
        for port in ports:
            self._log(f"  发现: {port['port']} - {port['description']}")

        self._log("=== 扫描完成 ===")

    def _disconnect_all(self):
        self.scope_widget._disconnect()
        self.power_widget._disconnect()
        self.load_widget._disconnect()
        self.chamber_widget._disconnect()

    def shutdown(self):
        """Stop background scans before the owning widgets are destroyed."""
        for widget in (self.scope_widget, self.power_widget,
                       self.load_widget, self.chamber_widget):
            auto = widget._auto_connect_thread
            if auto and auto.isRunning():
                auto.stop()
                if not auto.wait(3000):
                    return False
            scan = widget._scan_thread
            if scan and scan.isRunning() and not scan.wait(5000):
                return False
        self._disconnect_all()
        return True
        self.status_bar.showMessage("已断开所有仪器连接")
        self._log("已断开所有仪器连接")

    def _identify_by_idn(self, idn: str) -> str:
        if not idn:
            return "未知设备"
        idn_lower = idn.lower()
        if any(keyword in idn_lower for keyword in ["scope", "oscilloscope", "ds", "mso"]):
            return "示波器"
        elif any(keyword in idn_lower for keyword in ["power", "supply", "source", "spm"]):
            return "直流电源"
        elif any(keyword in idn_lower for keyword in ["load", "electronic", "dcl", "utl"]):
            return "电子负载"
        elif any(keyword in idn_lower for keyword in ["chamber", "temperature", "oven", "thermo"]):
            return "温箱"
        else:
            return "未知设备"

    def _auto_select_device(self, itype: str, resource: str, comm_type: str):
        widget_map = {
            "示波器": self.scope_widget,
            "直流电源": self.power_widget,
            "电子负载": self.load_widget,
            "温箱": self.chamber_widget,
        }
        widget = widget_map.get(itype)
        if widget:
            if comm_type == "usbtmc":
                widget.cmb_comm_type.setCurrentText("USB-TMC")
            elif comm_type == "visa":
                widget.cmb_comm_type.setCurrentText("VISA")
            else:
                widget.cmb_comm_type.setCurrentText("串口(Serial)")

            idx = widget.cmb_port.findText(resource, Qt.MatchStartsWith)
            if idx >= 0:
                widget.cmb_port.setCurrentIndex(idx)
                self._log(f"  已自动选择到 {itype} 面板")

    def _log(self, message: str):
        self.global_log.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        scroll_bar = self.global_log.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
