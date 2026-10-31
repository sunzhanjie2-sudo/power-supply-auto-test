"""Regressions for incomplete measurements, temperature deduplication and reports."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from auto_test.communication.serial_comm import SerialComm
from auto_test.config.project_config import ProjectConfig, OutputChannelConfig
from auto_test.test_case import PowerSpec, TestCaseGenerator, TestCaseLayout, build_tasks
from auto_test.test_case.test_case_generator import writable_cell
from auto_test.test_case.test_case_runner import CaseExecutor, RESULT_COLS_ATTR


class ReportIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.spec = PowerSpec.from_config(ProjectConfig())

    def test_missing_ripple_or_nonfinite_voltage_never_passes(self):
        task = build_tasks(self.spec, ("ripple",), 25)[0]
        ex = CaseExecutor(self.spec, {}, None, [task], "unused")
        for values in ((12, 12.1, None), (None, 12.1, .1), (12, float("nan"), .1)):
            self.assertEqual(ex._judge(task, *values), "ERROR")
        self.assertEqual(ex._judge(task, 11, 12.1, .1), "FAIL")
        self.assertEqual(ex._judge(task, 12, 12.1, .1), "PASS")

    def test_unique_temperatures_and_result_cells_align_for_one_to_seven_outputs(self):
        for n in range(1, 8):
            cfg = ProjectConfig(output_channels=[OutputChannelConfig(channel_name=f"CH{i+1}") for i in range(n)])
            spec = PowerSpec.from_config(cfg)
            wb = TestCaseGenerator(spec).build_workbook()
            tasks = build_tasks(spec, temp=25)
            self.assertEqual(len([t for t in tasks if t.kind == "dynamic"]), 3 * n)
            layout = TestCaseLayout(n)
            for task in tasks:
                ws = wb[task.sheet]
                cols = getattr(layout, RESULT_COLS_ATTR[task.sheet])(task.channel)
                for col in cols:
                    row, c = writable_cell(ws, task.row, col)
                    self.assertIsNone(ws.cell(row, c).value)

    def test_error_and_unexecuted_tasks_remain_visible_in_saved_report(self):
        tasks = build_tasks(self.spec, ("ripple",), 25)
        wb = TestCaseGenerator(self.spec).build_workbook()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "report.xlsx")
            ex = CaseExecutor(self.spec, {}, wb, tasks, path)
            def execute(task):
                ex.stop()
                return ex._result("ERROR", note="示波器取数失败")
            ex._execute = execute
            ex.run_blocking()
            saved = load_workbook(path)
            ws = saved["执行汇总"]
            self.assertEqual(ws["K9"].value, "ERROR")
            self.assertEqual(ws["L9"].value, "示波器取数失败")
            self.assertEqual(ws["K10"].value, "未执行")
            self.assertFalse(ex.all_passed)
            self.assertIn("停止", ws["B2"].value)
            self.assertFalse(Path(path + ".tmp.xlsx").exists())
            saved.close()

    def test_blank_measurement_columns_have_unmeasured_conclusions(self):
        wb = TestCaseGenerator(self.spec).build_workbook()
        for ws in list(wb)[1:]:
            formulas = [cell.value for row in ws for cell in row if cell.data_type == "f"]
            self.assertTrue(any('"未测量"' in f and "COUNT(" in f for f in formulas))
            self.assertTrue(any('"未测量"' in f and "ISNUMBER(" in f for f in formulas))
            self.assertTrue(all("=规格&说明!" not in f for f in formulas))

    def test_serial_query_has_only_one_reader(self):
        comm = SerialComm()
        class Port:
            in_waiting = 8
            def write(self, value):
                pass
            def flush(self):
                pass
            def read(self, count):
                raise AssertionError("query must not race the background reader")
        comm.ser = Port()
        comm.is_connected = True
        def deliver():
            with comm._buffer_lock:
                comm._response_buffer.append("12.116")
        timer = threading.Timer(.05, deliver)
        timer.start()
        self.assertEqual(comm.send_command("MEAS:VOLT?", True), "12.116")
        timer.join()

    def test_failed_save_preserves_the_previous_report(self):
        wb = TestCaseGenerator(self.spec).build_workbook()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "report.xlsx")
            ex = CaseExecutor(self.spec, {}, wb, build_tasks(self.spec, ("ripple",), 25), path)
            ex._save()
            before = Path(path).read_bytes()
            with patch("auto_test.test_case.test_case_runner.os.replace", side_effect=PermissionError("Excel lock")):
                with self.assertRaises(PermissionError):
                    ex._save()
            self.assertEqual(Path(path).read_bytes(), before)
            self.assertIn("Excel lock", ex.save_error)


if __name__ == "__main__":
    unittest.main()
