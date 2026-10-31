"""Regression for the DS1000E polarity found on the 12 V BUCK bench."""

import unittest

import numpy as np

from auto_test.instruments.oscilloscope import Oscilloscope


class ScopeWaveformTest(unittest.TestCase):
    def test_ds1000e_uses_its_documented_single_sweep_and_edge_polarity(self):
        scope = Oscilloscope()
        scope._model = "DS1152E"
        commands = []
        scope._send = lambda command: commands.append(command) or True
        scope.set_trigger_slope("FALLING")
        scope.single()
        self.assertEqual(commands, [":TRIG:EDGE:SLOP NEG", ":TRIG:EDGE:SWE SINGLE", ":RUN"])

    def test_transition_preserves_the_instrument_offset_and_zero_reference(self):
        scope = Oscilloscope()
        scope._model = "DS1152E"
        scope.get_waveform_data = lambda channel: np.array([125., 125., 65., 65.])
        scope.get_channel_scale = lambda channel: 5.0
        scope.get_channel_offset = lambda channel: 0.0
        scope.get_measurement = lambda measurement, source: 6.2
        volts = scope.get_waveform_data_volts(1)
        np.testing.assert_allclose(volts, [0., 0., 12., 12.])

    def test_ds1000e_waveform_uses_scope_dc_average_and_correct_polarity(self):
        scope = Oscilloscope()
        scope._model = "DS1152E"
        scope.get_waveform_data = lambda channel: np.array([63.0, 64.0, 65.0])
        scope.get_channel_scale = lambda channel: 5.0
        scope.get_measurement = lambda measurement, source: 12.2
        scope.get_channel_offset = lambda channel: 0.0

        volts = scope.get_waveform_data_volts(1)

        self.assertAlmostEqual(float(np.mean(volts)), 12.2)
        self.assertGreater(volts[0], volts[2])


if __name__ == "__main__":
    unittest.main()
