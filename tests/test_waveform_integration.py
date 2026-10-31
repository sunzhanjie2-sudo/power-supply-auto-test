"""Data fidelity, frozen settings, peak rendering and offline GUI regressions."""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from auto_test.instruments.oscilloscope import Oscilloscope
from auto_test.waveforms.archive import load_archive
from auto_test.waveforms.model import ChannelSettings, Coupling, TimebaseSettings, TriggerSettings, Waveform
from auto_test.waveforms.record import WaveformRecord
from auto_test.waveforms.screen_render import CH_COLORS, render_scope_screen


def sample_record():
    y = np.full(600, 12.)
    y[301] = 13.2
    wf = Waveform("CH1", y, -.029, .0001, raw=np.arange(600, dtype=np.uint8))
    ch = ChannelSettings(scale=2, offset=-6, offset_polarity=1)
    return WaveformRecord({"CH1": wf}, {"channels": {"CH1": ch},
        "timebase": TimebaseSettings(scale=.005, position=.001, horizontal_divisions=12),
        "trigger": TriggerSettings(level=6)}, "Rigol,DS1152E", {"task": {"vin": 42, "temp": 25, "name": "动态响应"}})


class WaveformIntegrationTest(unittest.TestCase):
    def test_archive_and_csv_preserve_values_raw_codes_and_time_axis(self):
        record = sample_record()
        with tempfile.TemporaryDirectory() as directory:
            paths = record.save(Path(directory)/"CH1_Iout0.1A_20261006_123456")
            self.assertIn("0.1A_20261006_123456", paths['npz'])
            waveforms, settings, meta = load_archive(paths['npz'])
            np.testing.assert_array_equal(waveforms['CH1'].y, record.waveforms['CH1'].y)
            np.testing.assert_array_equal(waveforms['CH1'].raw, record.waveforms['CH1'].raw)
            np.testing.assert_array_equal(waveforms['CH1'].x, record.waveforms['CH1'].x)
            self.assertEqual(settings['channels']['CH1'].offset, -6)
            self.assertEqual(meta['test_context']['task']['vin'], 42)
            csv = np.loadtxt(paths['csv'], delimiter=',', skiprows=1)
            np.testing.assert_allclose(csv[:, 1], waveforms['CH1'].x, rtol=0, atol=1e-16)
            np.testing.assert_array_equal(csv[:, 2], waveforms['CH1'].y)
            self.assertTrue(Path(paths['png']).read_bytes().startswith(b'\x89PNG'))

    def test_renderer_preserves_a_one_sample_spike_between_pixel_centers(self):
        y = np.zeros(100000)
        y[50117] = 3
        wf = Waveform('CH1', y, -.5, 1e-5)
        ch = ChannelSettings(scale=1, offset=0, offset_polarity=1)
        tb = TimebaseSettings(scale=.1, horizontal_divisions=10)
        image = render_scope_screen({'CH1': wf}, {'CH1': ch}, tb, width=400, height=320)
        yellow = np.all(image == CH_COLORS[0], axis=2)
        self.assertTrue(np.any(yellow[:60, 199:205]), 'narrow overshoot must remain visible')
        self.assertEqual(float(np.max(wf.y)), 3.)

    def test_settings_are_read_before_acquisition_resumes(self):
        scope = Oscilloscope()
        scope._model = 'DS1152E'
        scope.connected = True
        scope.comm = object()
        stopped = []
        scope.get_trigger_status = lambda: 'RUN'
        scope.stop = lambda: stopped.append(True)
        scope.run = lambda: stopped.pop()
        scope.get_waveform_data = lambda channel: np.array([125., 125., 65., 65.])
        scope.get_channel_scale = lambda channel: 5.
        scope.get_channel_offset = lambda channel: 0.
        scope.get_measurement = lambda measurement, source: 6.
        scope.get_timebase_scale = lambda: .001 if stopped else 99.
        responses = {':TIM:OFFS?': '.002', ':CHAN1:COUP?': 'DC', ':TRIG:EDGE:SOUR?': 'CHAN1',
                     ':TRIG:EDGE:SLOP?': 'POS', ':TRIG:EDGE:SWE?': 'AUTO', ':TRIG:EDGE:LEV?': '6',
                     ':CHAN1:PROB?': '1', ':CHAN1:BWL?': 'ON'}
        def query(command):
            self.assertTrue(stopped, 'metadata must be queried on the frozen frame')
            return responses[command]
        scope.query = query
        record = scope.get_waveform_capture()
        self.assertFalse(stopped)
        self.assertEqual(record.settings['timebase'].scale, .001)
        self.assertAlmostEqual(record.waveforms['CH1'].x_start, -.004)
        np.testing.assert_array_equal(record.waveforms['CH1'].y, [0, 0, 12, 12])

    def test_offline_viewer_zoom_cursor_and_fft_leave_record_unchanged(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from PyQt5.QtCore import Qt, QPoint
        from auto_test.waveforms.ui.viewer import WaveformViewer
        self.app = QApplication.instance() or QApplication([])
        record = sample_record()
        before = record.waveforms['CH1'].y.copy()
        with tempfile.TemporaryDirectory() as directory:
            paths = record.save(Path(directory)/'record')
            viewer = WaveformViewer()
            viewer.load_file(paths['npz'])
            viewer.show()
            self.app.processEvents()
            viewer.zoom.setChecked(True)
            viewer.cursors.setChecked(True)
            viewer.fft.setChecked(True)
            viewer.gain.setCurrentIndex(2)
            viewer._scale_changed(.001)
            viewer._position_changed(.004)
            QTest.mousePress(viewer.view, Qt.LeftButton, pos=QPoint(350, 180))
            QTest.mouseMove(viewer.view, QPoint(370, 180))
            QTest.mouseRelease(viewer.view, Qt.LeftButton, pos=QPoint(370, 180))
            self.app.processEvents()
            image = viewer.grab()
            self.assertFalse(image.isNull())
            np.testing.assert_array_equal(viewer.record.waveforms['CH1'].y, before)
            self.assertEqual(viewer.record.settings['timebase'].scale, .005)
            self.assertIn('Vmax', viewer.stats.text())
            self.assertEqual(viewer.view.cursor_times, viewer.zoom_view.cursor_times)
            viewer.close()


if __name__ == '__main__':
    unittest.main()
