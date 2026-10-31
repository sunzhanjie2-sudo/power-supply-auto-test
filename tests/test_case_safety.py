"""A declined multi-output probe change must stop before any DUT action."""

import unittest
from types import SimpleNamespace

from auto_test.test_case.test_case_generator import OutputSpec, PowerSpec
from auto_test.test_case.test_case_runner import CaseExecutor


class CaseSafetyTest(unittest.TestCase):
    def test_declined_channel_change_skips_execution(self):
        spec = PowerSpec(outputs=[OutputSpec(name="CH1"), OutputSpec(name="CH2")])
        task = SimpleNamespace(sheet="ripple", channel=1, name="第二路轻载", test_item="纹波")
        executed = []
        executor = CaseExecutor(
            spec, {}, None, [task], "", on_confirm=lambda message: False,
        )
        executor._execute = lambda step: executed.append(step)
        executor._save = lambda: None
        executor.run_blocking()

        self.assertEqual(executed, [])
        self.assertTrue(executor.was_stopped)

    def test_multi_output_requires_a_switch_confirmation_handler(self):
        spec = PowerSpec(outputs=[OutputSpec(name="CH1"), OutputSpec(name="CH2")])
        task = SimpleNamespace(sheet="ripple", channel=1, name="第二路轻载", test_item="纹波")
        executor = CaseExecutor(spec, {}, None, [task], "")
        self.assertFalse(executor._confirm_channel(task))


if __name__ == "__main__":
    unittest.main()
