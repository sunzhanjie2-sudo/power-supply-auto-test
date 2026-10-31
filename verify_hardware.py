"""Drive the real GUI test workflow and audit the saved hardware report."""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--kinds", default="ripple,dynamic,stability,startup")
    parser.add_argument("--temp", type=float, default=25.0)
    parser.add_argument("--quick", action="store_true", help="one task per test kind")
    args = parser.parse_args(argv)
    kinds = args.kinds.split(",")
    if not set(kinds) <= {"ripple", "dynamic", "stability", "startup"}:
        parser.error("unknown test kind")

    from PyQt5.QtWidgets import QApplication, QMessageBox
    from openpyxl import load_workbook
    from auto_test.config.project_config import ProjectConfig
    from auto_test.gui.main_window import MainWindow
    from auto_test.gui import case_panel as case_module
    from auto_test.test_case.test_case_generator import TestCaseLayout, writable_cell
    from auto_test.test_case.test_case_runner import RESULT_COLS_ATTR
    from auto_test.runtime import reports_directory
    from auto_test.waveforms.record import WaveformRecord
    import numpy as np

    dialogs = []
    def capture(*a, **kw):
        dialogs.append({"title": str(a[1]), "text": str(a[2])})
        print(f"[{a[1]}] {a[2]}", flush=True)
        return QMessageBox.Ok
    for name in ("information", "warning", "critical"):
        setattr(QMessageBox, name, staticmethod(capture))
    # No automatic approval of rewiring or incomplete-instrument prompts.
    QMessageBox.question = staticmethod(lambda *a, **kw: QMessageBox.No)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = MainWindow()
    cfg = ProjectConfig.load(str(args.config)) if args.config else window.config_panel.get_config()
    if len(cfg.output_channels) != 1:
        parser.error("hardware verification requires a single output; use GUI for rewiring")
    out = (args.output or reports_directory() / ("verification_" + datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg.output_root = str(out)
    cfg.model_name = "现场验证"
    cfg.save(str(out / "config.json"))
    window.config_panel.set_config(cfg)
    panel = window.case_panel
    panel.spin_temp.setValue(args.temp)
    for name, checkbox in panel.chk.items():
        checkbox.setChecked(name in kinds)
    original_build = case_module.build_tasks
    if args.quick:
        def quick_tasks(*a, **kw):
            seen = set()
            result = []
            for task in original_build(*a, **kw):
                if task.kind not in seen:
                    seen.add(task.kind)
                    result.append(task)
            return result
        case_module.build_tasks = quick_tasks
    summary = {"started_at": datetime.now().isoformat(), "dialogs": dialogs, "output": str(out)}
    try:
        window.show()
        app.processEvents()
        window.btn_connect_all.click()
        app.processEvents()
        summary["instruments"] = {name: inst.get_idn() for name, inst in window.instruments.items()
                                  if name in ("power_supply", "electronic_load", "oscilloscope")}
        print(json.dumps(summary["instruments"], ensure_ascii=False), flush=True)
        if len(summary["instruments"]) != 3:
            raise RuntimeError("three instruments are required")
        window.tab.setCurrentWidget(panel)
        finished = []
        panel._bridge.task_done.connect(lambda t, r, i, n: print(
            f"[{i+1}/{n}] {t.test_item} Vin={t.vin:g} {t.name}: {r}", flush=True))
        panel._bridge.finished.connect(lambda: finished.append(True))
        panel.btn_start.click()
        if panel.executor is None:
            raise RuntimeError("GUI did not start the test")
        deadline = time.monotonic() + 1200
        while not finished:
            app.processEvents()
            time.sleep(0.05)
            if time.monotonic() > deadline:
                panel.executor.stop()
                raise TimeoutError("hardware verification exceeded 20 minutes")
        app.processEvents()
        rows = [{"step": i + 1, "kind": task.kind, "vin": task.vin, "row": task.row,
                 "status": panel.table.item(i, 10).text(),
                 "vmin": panel.table.item(i, 7).text(), "vmax": panel.table.item(i, 8).text(),
                 "ripple": panel.table.item(i, 9).text()} for i, task in enumerate(panel._tasks)]
        summary["results"] = rows
        summary["counts"] = dict(Counter(row["status"] for row in rows))
        summary["report"] = panel.report_path
        summary["error"] = panel.executor.error_msg
        summary["software_validation"] = False
        summary["saved"] = os.path.isfile(panel.report_path)
        if summary["saved"]:
            wb = load_workbook(panel.report_path)
            layout = TestCaseLayout(1)
            summary["image_count"] = sum(len(ws._images) for ws in wb)
            if "执行汇总" in wb.sheetnames:
                audit = wb["执行汇总"]
                summary["report_state"] = audit["B2"].value
                for i, row in enumerate(rows):
                    if audit.cell(i + 9, 11).value != row["status"]:
                        raise RuntimeError("saved execution status differs from GUI")
            for task, row in zip(panel._tasks, rows):
                cols = getattr(layout, RESULT_COLS_ATTR[task.sheet])(task.channel)
                ws = wb[task.sheet]
                for col, key in zip(cols, ("vmin", "vmax", "ripple")):
                    if key == "ripple" and task.kind != "ripple":
                        continue
                    wr, wc = writable_cell(ws, task.row, col)
                    value = ws.cell(wr, wc).value
                    if row[key] != "-" and (not isinstance(value, (int, float)) or abs(float(row[key]) - value) > 1e-4):
                        raise RuntimeError(f"Excel result differs from GUI: {task.sheet} {wr},{wc}")
            summary["report_matches_gui"] = True
            wb.close()
            summary["archive_count"] = 0
            summary["hardware_errors"] = []
            for task, result in panel.executor.results:
                if not result.get("npz"):
                    if result['status'] in ('PASS', 'FAIL') or not result.get('note'):
                        raise RuntimeError(f"missing NPZ archive: {task.test_item}")
                    summary["hardware_errors"].append({"item": task.test_item, "note": result['note']})
                    continue
                record = WaveformRecord.load(result["npz"])
                wf = record.waveforms['CH1']
                csv = np.loadtxt(result['csv'], delimiter=',', skiprows=1)
                np.testing.assert_allclose(csv[:, 1], wf.x, rtol=0, atol=1e-12)
                np.testing.assert_array_equal(csv[:, 2], wf.y)
                if wf.raw is None or len(wf.raw) != wf.points:
                    raise RuntimeError('NPZ is missing original ADC codes')
                if task.kind != 'ripple':
                    for key, measured in (('vmin', np.min(wf.y)), ('vmax', np.max(wf.y))):
                        if abs(result[key] - float(measured)) > 1e-4:
                            raise RuntimeError(f'archive differs from tested waveform: {key}')
                elif abs(result['ripple'] - float(np.ptp(wf.y))) > 1e-4:
                    raise RuntimeError('ripple differs from archived waveform')
                summary["archive_count"] += 1
            summary["archive_matches_csv"] = True
            if not panel._waveform_paths:
                raise RuntimeError('no physical waveform available for viewer validation')
            panel.table.selectRow(max(panel._waveform_paths))
            panel.btn_waveform.click()
            app.processEvents()
            viewer = panel._waveform_viewer
            if not viewer or not viewer.isVisible() or not viewer.record:
                raise RuntimeError('case waveform viewer did not open')
            original = viewer.record.waveforms['CH1'].y.copy()
            viewer.zoom.setChecked(True)
            viewer.cursors.setChecked(True)
            viewer.fft.setChecked(True)
            viewer.gain.setCurrentIndex(1)
            app.processEvents()
            np.testing.assert_array_equal(viewer.record.waveforms['CH1'].y, original)
            viewer.grab().save(str(out / 'waveform_viewer.png'))
            viewer.close()
            summary["viewer_verified"] = True
            summary["software_validation"] = (not summary["error"] and not panel.executor.save_error
                                                and summary["image_count"] == summary["archive_count"]
                                                and summary["archive_count"] + len(summary["hardware_errors"]) == len(rows))
        summary["success"] = (bool(rows) and all(r["status"] == "PASS" for r in rows)
                              and summary["saved"] and not summary["error"])
    except Exception as exc:
        summary["success"] = False
        summary["error"] = str(exc)
        print(f"ERROR: {exc}", flush=True)
    finally:
        case_module.build_tasks = original_build
        ex = panel.executor
        if ex and ex.running:
            ex.stop()
            while ex.running:
                app.processEvents()
                time.sleep(0.05)
        for name in ("electronic_load", "power_supply"):
            inst = window.instruments.get(name)
            if inst:
                if name == "electronic_load":
                    inst.disable_input()
                    summary["load_off"] = inst.get_input_state() is False
                else:
                    inst.enable_output(False)
                    summary["source_off"] = inst.get_output_state() is False
        summary["success"] = (summary.get("success", False) and summary.get("load_off", False)
                              and summary.get("source_off", False))
        summary["finished_at"] = datetime.now().isoformat()
        (out / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "gui_log.txt").write_text(panel.log.toPlainText(), encoding="utf-8")
        window.close()
        app.processEvents()
    print(f"Verification: {out / 'verification.json'}", flush=True)
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
