"""Delayed acknowledgement and failed transition must remain distinguishable."""
import unittest
from unittest.mock import patch
from auto_test.instruments.electronic_load import ElectronicLoad


class LoadTransitionTest(unittest.TestCase):
    def test_command_processing_gap_applies_after_queries_as_well_as_writes(self):
        load = ElectronicLoad()
        load.connected = True
        clock = [1.]
        events = []
        class Comm:
            def send_command(self, command, response, *args):
                events.append((command, clock[0]))
                return '4' if response else None
        load.comm = Comm()
        with patch('auto_test.instruments.electronic_load.time.monotonic', side_effect=lambda: clock[0]), \
             patch('auto_test.instruments.electronic_load.time.sleep', side_effect=lambda gap: clock.__setitem__(0, clock[0]+gap)):
            load.query('FUNC?')
            load.send_command('INP ON')
            load.query('INP?')
        self.assertAlmostEqual(events[1][1]-events[0][1], .15)
        self.assertAlmostEqual(events[2][1]-events[1][1], .15)

    def test_dynamic_start_is_not_repeated_while_waiting_for_acknowledgement(self):
        load = ElectronicLoad()
        replies = iter([False, False, True])
        writes = []
        load.send_command = lambda command, **kw: writes.append(command)
        load.get_input_state = lambda: next(replies)
        load._reapply_setpoint = lambda: None
        with patch('auto_test.instruments.electronic_load.time.sleep'):
            self.assertTrue(load.enable_input(True))
        self.assertEqual(writes, ['INP ON'])
        self.assertEqual([item['state'] for item in load.last_input_trace], [False, False, True])

    def test_failed_input_transition_keeps_an_error_and_protection_status(self):
        load = ElectronicLoad()
        load.send_command = lambda command, **kw: None
        load.get_input_state = lambda: False
        load.query = lambda command: '2'
        with patch('auto_test.instruments.electronic_load.time.sleep'):
            self.assertFalse(load.enable_input(True))
        self.assertEqual(load.last_input_trace[-1]['questionable_status'], '2')
        self.assertFalse(load.last_input_trace[-1]['state'])

    def test_an_ignored_command_is_retried_after_the_settling_window(self):
        load = ElectronicLoad()
        replies = iter([False, False, False, True])
        writes = []
        load.send_command = lambda command, **kw: writes.append(command)
        load.get_input_state = lambda: next(replies)
        load.query = lambda command: '0'
        load._reapply_setpoint = lambda: None
        with patch('auto_test.instruments.electronic_load.time.sleep'):
            self.assertTrue(load.enable_input(True))
        self.assertEqual(writes, ['INP ON', 'INP ON'])
        self.assertEqual(load.last_input_trace[-1]['attempt'], 2)

    def test_empty_response_does_not_confirm_a_safe_off_state(self):
        load = ElectronicLoad()
        load.query = lambda command: ''
        self.assertIsNone(load.get_input_state())


if __name__ == '__main__':
    unittest.main()
