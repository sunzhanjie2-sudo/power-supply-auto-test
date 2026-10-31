from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QFileDialog, QMessageBox, QHeaderView, QCheckBox
)
from PyQt5.QtCore import Qt
from ..config.project_config import (
    ProjectConfig, BoundaryParams, OutputChannelConfig,
    ComponentProfile, TestItemConfig, CriteriaSpec, OutputType
)


class ConfigPanel(QWidget):
    """配置面板 - 样机信息、边界工况、白盒器件、测试项判据"""

    # 默认测试项（动态响应、短路保护等由测试矩阵自动生成，此处只需稳态测量项）
    DEFAULT_TEST_ITEMS = [
        ("稳压精度", "black_box", "CH1", "12.6", "11.4"),
        ("输出纹波与噪声", "black_box", "CH1", "0.5", "0.0"),
        ("开关机时序", "black_box", "CH1", "100", "0"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_config = ProjectConfig()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tab = QTabWidget()

        # 标签页1: 样机基础配置
        tab.addTab(self._create_basic_tab(), "样机基础配置")

        # 标签页2: 边界工况配置
        tab.addTab(self._create_boundary_tab(), "边界工况配置")

        # 标签页3: 白盒器件配置
        tab.addTab(self._create_component_tab(), "白盒器件配置")

        # 标签页4: 测试项与判据
        tab.addTab(self._create_test_items_tab(), "测试项与判据")

        layout.addWidget(tab)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("保存工程文件")
        self.btn_load = QPushButton("加载工程文件")
        self.btn_save.clicked.connect(self._save_config)
        self.btn_load.clicked.connect(self._load_config)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_load)
        layout.addLayout(btn_layout)

    def _create_basic_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self.edit_model = QLineEdit("新样机")
        self.cmb_output_type = QComboBox()
        self.cmb_output_type.addItems([t.value for t in OutputType])
        self.cmb_output_type.currentTextChanged.connect(self._on_output_type_changed)
        self.edit_sn = QLineEdit()
        self.edit_version = QLineEdit("V1.0")
        self.edit_tester = QLineEdit()
        self.edit_date = QLineEdit()
        self.edit_output_root = QLineEdit("")
        self.btn_browse_output = QPushButton("浏览")
        self.btn_browse_output.clicked.connect(self._browse_output_root)

        layout.addRow("样机型号:", self.edit_model)
        layout.addRow("输出类型:", self.cmb_output_type)
        layout.addRow("SN编号:", self.edit_sn)
        layout.addRow("研发版本:", self.edit_version)
        layout.addRow("测试人员:", self.edit_tester)
        layout.addRow("测试日期:", self.edit_date)

        output_root_row = QHBoxLayout()
        output_root_row.addWidget(self.edit_output_root)
        output_root_row.addWidget(self.btn_browse_output)
        layout.addRow("输出根目录:", output_root_row)

        # 输出通道配置
        group_channels = QGroupBox("输出通道配置")
        ch_layout = QVBoxLayout(group_channels)
        self.CH_COLUMNS = ["通道名称", "标称电压(V)", "标称电流(A)", "Vout_min(V)", "Vout_max(V)",
                           "Pout_min(W)", "Pout_typ(W)", "Pout_max(W)", "纹波(%)"]
        self.table_channels = QTableWidget(1, len(self.CH_COLUMNS))
        self.table_channels.setHorizontalHeaderLabels(self.CH_COLUMNS)
        self.table_channels.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._set_channel_row(0, "CH1")
        btn_ch = QPushButton("添加通道")
        btn_ch.clicked.connect(lambda: self.table_channels.insertRow(self.table_channels.rowCount()))
        ch_layout.addWidget(self.table_channels)
        ch_layout.addWidget(btn_ch)
        layout.addRow(group_channels)

        return w

    def _set_channel_row(self, row: int, name: str):
        """填充一个通道行的默认值"""
        defaults = [name, "12.0", "2.5", "11.4", "12.6", "1.2", "15.0", "30.0", "3.0"]
        for c, v in enumerate(defaults):
            self.table_channels.setItem(row, c, QTableWidgetItem(v))

    def _on_output_type_changed(self, text: str):
        """输出类型变化时自动调整输出通道数"""
        import re
        match = re.search(r'(\d+)路', text)
        num = int(match.group(1)) if match else 1

        self.table_channels.setRowCount(0)
        for i in range(num):
            row = self.table_channels.rowCount()
            self.table_channels.insertRow(row)
            self._set_channel_row(row, f"CH{i+1}")

        self._refresh_multi_iout_fields()

    def _browse_output_root(self):
        """浏览选择输出根目录"""
        path = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.edit_output_root.text())
        if path:
            self.edit_output_root.setText(path)

    def _create_boundary_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        self.edit_vin_min = QDoubleSpinBox()
        self.edit_vin_min.setRange(0, 1000)
        self.edit_vin_min.setValue(36.0)
        self.edit_vin_min.setSuffix(" V")

        self.edit_vin_rated = QDoubleSpinBox()
        self.edit_vin_rated.setRange(0, 1000)
        self.edit_vin_rated.setValue(42.0)
        self.edit_vin_rated.setSuffix(" V")

        self.edit_vin_max = QDoubleSpinBox()
        self.edit_vin_max.setRange(0, 1000)
        self.edit_vin_max.setValue(48.0)
        self.edit_vin_max.setSuffix(" V")

        self.edit_temp_min = QDoubleSpinBox()
        self.edit_temp_min.setRange(-100, 200)
        self.edit_temp_min.setValue(25.0)
        self.edit_temp_min.setSuffix(" °C")

        self.edit_temp_rated = QDoubleSpinBox()
        self.edit_temp_rated.setRange(-100, 200)
        self.edit_temp_rated.setValue(25.0)
        self.edit_temp_rated.setSuffix(" °C")

        self.edit_temp_max = QDoubleSpinBox()
        self.edit_temp_max.setRange(-100, 200)
        self.edit_temp_max.setValue(25.0)
        self.edit_temp_max.setSuffix(" °C")

        layout.addRow("Vin_min:", self.edit_vin_min)
        layout.addRow("Vin_rated:", self.edit_vin_rated)
        layout.addRow("Vin_max:", self.edit_vin_max)
        layout.addRow("T_min:", self.edit_temp_min)
        layout.addRow("T_rated:", self.edit_temp_rated)
        layout.addRow("T_max:", self.edit_temp_max)

        self.edit_switch_freq = QDoubleSpinBox()
        self.edit_switch_freq.setRange(1000, 1e7)
        self.edit_switch_freq.setValue(100000)
        self.edit_switch_freq.setDecimals(0)
        self.edit_switch_freq.setSuffix(" Hz")
        layout.addRow("开关频率:", self.edit_switch_freq)

        # 各通道Iout边界
        self.group_multi_iout = QGroupBox("各通道Iout边界")
        self.multi_iout_layout = QFormLayout(self.group_multi_iout)
        self.multi_iout_widgets = {}  # {"CH1": (edit_min, edit_half, edit_rated, edit_max), ...}
        layout.addRow(self.group_multi_iout)

        return w

    def _refresh_multi_iout_fields(self):
        """根据输出类型刷新各通道Iout边界字段"""
        # 清除旧控件
        for widgets in self.multi_iout_widgets.values():
            for w in widgets:
                self.multi_iout_layout.removeRow(w)
        self.multi_iout_widgets.clear()

        # 获取当前输出通道数
        import re
        text = self.cmb_output_type.currentText()
        match = re.search(r'(\d+)路', text)
        num_channels = int(match.group(1)) if match else 1

        self.group_multi_iout.show()
        for i in range(num_channels):  # 从CH1开始
            ch_name = f"CH{i+1}"
            edit_min = QDoubleSpinBox()
            edit_min.setRange(0, 100)
            edit_min.setValue(0.1)
            edit_min.setSuffix(" A")
            edit_half = QDoubleSpinBox()
            edit_half.setRange(0, 100)
            edit_half.setValue(1.25)
            edit_half.setSuffix(" A")
            edit_rated = QDoubleSpinBox()
            edit_rated.setRange(0, 100)
            edit_rated.setValue(2.5)
            edit_rated.setSuffix(" A")
            edit_max = QDoubleSpinBox()
            edit_max.setRange(0, 100)
            edit_max.setValue(2.5)
            edit_max.setSuffix(" A")
            self.multi_iout_layout.addRow(f"{ch_name}_min:", edit_min)
            self.multi_iout_layout.addRow(f"{ch_name}_half:", edit_half)
            self.multi_iout_layout.addRow(f"{ch_name}_rated:", edit_rated)
            self.multi_iout_layout.addRow(f"{ch_name}_max:", edit_max)
            self.multi_iout_widgets[ch_name] = (edit_min, edit_half, edit_rated, edit_max)

    def _create_component_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.table_components = QTableWidget(0, 11)
        headers = ["位号", "器件名称", "类型", "示波器通道", "电压档位", "时基(ns)", "触发源", "触发边沿", "触发电平", "带宽", "耐压(V)"]
        self.table_components.setHorizontalHeaderLabels(headers)
        self.table_components.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("添加器件")
        btn_del = QPushButton("删除选中")
        btn_add.clicked.connect(self._add_component_row)
        btn_del.clicked.connect(lambda: self.table_components.removeRow(self.table_components.currentRow()))
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()

        layout.addWidget(self.table_components)
        layout.addLayout(btn_row)

        return w

    def _add_component_row(self):
        row = self.table_components.rowCount()
        self.table_components.insertRow(row)
        self.table_components.setItem(row, 0, QTableWidgetItem(f"Q{row+1}"))
        self.table_components.setItem(row, 1, QTableWidgetItem("MOSFET"))
        self.table_components.setItem(row, 2, QTableWidgetItem("MOSFET"))
        self.table_components.setItem(row, 3, QTableWidgetItem("1"))
        self.table_components.setItem(row, 4, QTableWidgetItem("1.0"))
        self.table_components.setItem(row, 5, QTableWidgetItem("1000"))
        self.table_components.setItem(row, 6, QTableWidgetItem("CH1"))
        self.table_components.setItem(row, 7, QTableWidgetItem("RISING"))
        self.table_components.setItem(row, 8, QTableWidgetItem("0.5"))
        self.table_components.setItem(row, 9, QTableWidgetItem("FULL"))
        self.table_components.setItem(row, 10, QTableWidgetItem("100"))

    def _create_test_items_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.table_test_items = QTableWidget(0, 5)
        self.table_test_items.setHorizontalHeaderLabels(["测试项", "类型", "通道", "判据上限", "判据下限"])
        self.table_test_items.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 默认测试项（动态响应和短路保护由测试矩阵自动生成，此处不需要）
        for name, ttype, ch, up, low in self.DEFAULT_TEST_ITEMS:
            row = self.table_test_items.rowCount()
            self.table_test_items.insertRow(row)
            self.table_test_items.setItem(row, 0, QTableWidgetItem(name))
            self.table_test_items.setItem(row, 1, QTableWidgetItem(ttype))
            self.table_test_items.setItem(row, 2, QTableWidgetItem(ch))
            self.table_test_items.setItem(row, 3, QTableWidgetItem(up))
            self.table_test_items.setItem(row, 4, QTableWidgetItem(low))

        layout.addWidget(self.table_test_items)
        return w

    def get_config(self) -> ProjectConfig:
        """从GUI获取配置"""
        cfg = ProjectConfig()
        cfg.model_name = self.edit_model.text()
        cfg.output_type = OutputType(self.cmb_output_type.currentText())
        cfg.sn = self.edit_sn.text()
        cfg.version = self.edit_version.text()
        cfg.tester = self.edit_tester.text()
        cfg.test_date = self.edit_date.text()
        cfg.output_root = self.edit_output_root.text()

        # 输出通道
        cfg.output_channels = []
        for r in range(self.table_channels.rowCount()):
            name = self.table_channels.item(r, 0)
            volt = self.table_channels.item(r, 1)
            curr = self.table_channels.item(r, 2)

            def _cell(c):
                it = self.table_channels.item(r, c)
                return it.text() if it else ""

            vout_min = float(_cell(3)) if _cell(3) else 0.0
            vout_max = float(_cell(4)) if _cell(4) else 0.0
            pout_min = float(_cell(5)) if _cell(5) else 0.0
            pout_typ = float(_cell(6)) if _cell(6) else 0.0
            pout_max = float(_cell(7)) if _cell(7) else 0.0
            ripple = float(_cell(8)) if _cell(8) else 3.0

            if name:
                ch_name = name.text() if name else "CH1"
                # 从多通道Iout边界获取该通道的Iout参数
                iout_widgets = self.multi_iout_widgets.get(ch_name)
                if iout_widgets:
                    cfg.output_channels.append(OutputChannelConfig(
                        channel_name=ch_name,
                        nominal_voltage=float(volt.text()) if volt else 12.0,
                        nominal_current=float(curr.text()) if curr else 2.5,
                        vout_min=vout_min, vout_max=vout_max,
                        pout_min=pout_min, pout_typ=pout_typ, pout_max=pout_max,
                        ripple_percent=ripple,
                        iout_min=iout_widgets[0].value(),
                        iout_half=iout_widgets[1].value(),
                        iout_rated=iout_widgets[2].value(),
                        iout_max=iout_widgets[3].value(),
                    ))
                else:
                    cfg.output_channels.append(OutputChannelConfig(
                        channel_name=ch_name,
                        nominal_voltage=float(volt.text()) if volt else 12.0,
                        nominal_current=float(curr.text()) if curr else 2.5,
                        vout_min=vout_min, vout_max=vout_max,
                        pout_min=pout_min, pout_typ=pout_typ, pout_max=pout_max,
                        ripple_percent=ripple,
                    ))

        # 边界（Iout从CH1的多通道边界获取）
        ch1_iout = self.multi_iout_widgets.get("CH1", (None, None, None, None))
        iout_min = ch1_iout[0].value() if ch1_iout[0] else 0.1
        iout_half = ch1_iout[1].value() if ch1_iout[1] else 1.25
        iout_rated = ch1_iout[2].value() if ch1_iout[2] else 2.5
        iout_max = ch1_iout[3].value() if ch1_iout[3] else 2.5

        cfg.boundary = BoundaryParams(
            vin_min=self.edit_vin_min.value(),
            vin_rated=self.edit_vin_rated.value(),
            vin_max=self.edit_vin_max.value(),
            vin_list=[self.edit_vin_min.value(), self.edit_vin_rated.value(), self.edit_vin_max.value()],
            temp_min=self.edit_temp_min.value(),
            temp_rated=self.edit_temp_rated.value(),
            temp_max=self.edit_temp_max.value(),
            temp_list=[self.edit_temp_min.value(), self.edit_temp_rated.value(), self.edit_temp_max.value()],
            iout_min=iout_min,
            iout_half=iout_half,
            iout_rated=iout_rated,
            iout_max=iout_max,
            switch_freq=self.edit_switch_freq.value(),
        )

        # 白盒器件
        cfg.components = []
        for r in range(self.table_components.rowCount()):
            comp = ComponentProfile()
            if self.table_components.item(r, 0):
                comp.ref_des = self.table_components.item(r, 0).text()
            if self.table_components.item(r, 1):
                comp.device_name = self.table_components.item(r, 1).text()
            if self.table_components.item(r, 2):
                comp.device_type = self.table_components.item(r, 2).text()
            if self.table_components.item(r, 3):
                comp.scope_channel = int(self.table_components.item(r, 3).text())
            if self.table_components.item(r, 4):
                comp.voltage_scale = float(self.table_components.item(r, 4).text())
            if self.table_components.item(r, 5):
                comp.timebase_scale = float(self.table_components.item(r, 5).text()) * 1e-9
            if self.table_components.item(r, 6):
                comp.trigger_source = self.table_components.item(r, 6).text()
            if self.table_components.item(r, 7):
                comp.trigger_edge = self.table_components.item(r, 7).text()
            if self.table_components.item(r, 8):
                comp.trigger_level = float(self.table_components.item(r, 8).text())
            if self.table_components.item(r, 9):
                comp.bandwidth = self.table_components.item(r, 9).text()
            if self.table_components.item(r, 10):
                comp.voltage_rating = float(self.table_components.item(r, 10).text())
            cfg.components.append(comp)

        # 测试项
        cfg.test_items = []
        for r in range(self.table_test_items.rowCount()):
            item = TestItemConfig()
            if self.table_test_items.item(r, 0):
                item.name = self.table_test_items.item(r, 0).text()
            if self.table_test_items.item(r, 1):
                item.test_type = self.table_test_items.item(r, 1).text()
            if self.table_test_items.item(r, 2):
                item.channel = self.table_test_items.item(r, 2).text()
            up = float(self.table_test_items.item(r, 3).text()) if self.table_test_items.item(r, 3) else 0
            low = float(self.table_test_items.item(r, 4).text()) if self.table_test_items.item(r, 4) else 0
            item.criteria = CriteriaSpec(
                upper_limit=up,
                lower_limit=low,
                nominal_value=(up + low) / 2 if (up or low) else 0,
            )
            item.enabled = True
            cfg.test_items.append(item)

        return cfg

    def set_config(self, cfg: ProjectConfig):
        """将配置显示到GUI"""
        self.edit_model.setText(cfg.model_name)
        self.cmb_output_type.setCurrentText(cfg.output_type.value)
        self.edit_sn.setText(cfg.sn)
        self.edit_version.setText(cfg.version)
        self.edit_tester.setText(cfg.tester)
        self.edit_date.setText(cfg.test_date)
        self.edit_output_root.setText(cfg.output_root)

        # 恢复输出通道
        self.table_channels.setRowCount(0)
        for ch_cfg in cfg.output_channels:
            r = self.table_channels.rowCount()
            self.table_channels.insertRow(r)
            self.table_channels.setItem(r, 0, QTableWidgetItem(ch_cfg.channel_name))
            self.table_channels.setItem(r, 1, QTableWidgetItem(str(ch_cfg.nominal_voltage)))
            self.table_channels.setItem(r, 2, QTableWidgetItem(str(ch_cfg.nominal_current)))
            self.table_channels.setItem(r, 3, QTableWidgetItem(str(ch_cfg.vout_min)))
            self.table_channels.setItem(r, 4, QTableWidgetItem(str(ch_cfg.vout_max)))
            self.table_channels.setItem(r, 5, QTableWidgetItem(str(ch_cfg.pout_min)))
            self.table_channels.setItem(r, 6, QTableWidgetItem(str(ch_cfg.pout_typ)))
            self.table_channels.setItem(r, 7, QTableWidgetItem(str(ch_cfg.pout_max)))
            self.table_channels.setItem(r, 8, QTableWidgetItem(str(ch_cfg.ripple_percent)))

        self.edit_vin_min.setValue(cfg.boundary.vin_min)
        self.edit_vin_rated.setValue(cfg.boundary.vin_rated)
        self.edit_vin_max.setValue(cfg.boundary.vin_max)
        self.edit_temp_min.setValue(cfg.boundary.temp_min)
        self.edit_temp_rated.setValue(cfg.boundary.temp_rated)
        self.edit_temp_max.setValue(cfg.boundary.temp_max)
        self.edit_switch_freq.setValue(cfg.boundary.switch_freq)

        # 恢复各通道Iout边界
        self._refresh_multi_iout_fields()
        for ch_cfg in cfg.output_channels:
            widgets = self.multi_iout_widgets.get(ch_cfg.channel_name)
            if widgets:
                widgets[0].setValue(ch_cfg.iout_min)
                widgets[1].setValue(ch_cfg.iout_half)
                widgets[2].setValue(ch_cfg.iout_rated)
                widgets[3].setValue(ch_cfg.iout_max)

        # 恢复白盒器件配置
        self.table_components.setRowCount(0)
        for comp in cfg.components:
            row = self.table_components.rowCount()
            self.table_components.insertRow(row)
            values = [
                comp.ref_des, comp.device_name, comp.device_type,
                str(comp.scope_channel), str(comp.voltage_scale),
                str(int(comp.timebase_scale * 1e9)),  # 秒 -> ns 显示
                comp.trigger_source, comp.trigger_edge,
                str(comp.trigger_level), comp.bandwidth,
                str(comp.voltage_rating),
            ]
            for col, val in enumerate(values):
                self.table_components.setItem(row, col, QTableWidgetItem(val))

        # 恢复测试项与判据
        self.table_test_items.setRowCount(0)
        for item in cfg.test_items:
            row = self.table_test_items.rowCount()
            self.table_test_items.insertRow(row)
            self.table_test_items.setItem(row, 0, QTableWidgetItem(item.name))
            self.table_test_items.setItem(row, 1, QTableWidgetItem(item.test_type))
            self.table_test_items.setItem(row, 2, QTableWidgetItem(item.channel))
            crit = item.criteria
            if isinstance(crit, dict):
                up, low = crit.get("upper_limit", 0), crit.get("lower_limit", 0)
            else:
                up, low = crit.upper_limit, crit.lower_limit
            self.table_test_items.setItem(row, 3, QTableWidgetItem(str(up)))
            self.table_test_items.setItem(row, 4, QTableWidgetItem(str(low)))

    def reset_to_defaults(self):
        """重置为默认工程配置（含默认测试项）"""
        cfg = ProjectConfig()
        for name, ttype, ch, up, low in self.DEFAULT_TEST_ITEMS:
            cfg.test_items.append(TestItemConfig(
                name=name,
                test_type=ttype,
                channel=ch,
                criteria=CriteriaSpec(
                    upper_limit=float(up),
                    lower_limit=float(low),
                    nominal_value=(float(up) + float(low)) / 2,
                ),
                enabled=True,
            ))
        self.set_config(cfg)

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存工程文件", "", "JSON Files (*.json)")
        if path:
            cfg = self.get_config()
            cfg.save(path)
            QMessageBox.information(self, "保存成功", f"工程文件已保存到: {path}")

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载工程文件", "", "JSON Files (*.json)")
        if path:
            cfg = ProjectConfig.load(path)
            self.set_config(cfg)
            QMessageBox.information(self, "加载成功", f"工程文件已加载: {path}")
