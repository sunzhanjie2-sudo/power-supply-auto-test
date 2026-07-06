import time
import json
import threading
from typing import List, Dict, Callable, Optional
from datetime import datetime


class TimingStep:
    def __init__(self, step_id: int, instrument: str, command: str, parameters: Dict = None, 
                 delay: float = 0.0, description: str = ""):
        self.step_id = step_id
        self.instrument = instrument
        self.command = command
        self.parameters = parameters or {}
        self.delay = delay
        self.description = description
        self.status = 'pending'
        self.result = None
        self.execution_time = None

    def to_dict(self) -> Dict:
        return {
            'step_id': self.step_id,
            'instrument': self.instrument,
            'command': self.command,
            'parameters': self.parameters,
            'delay': self.delay,
            'description': self.description
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'TimingStep':
        return cls(
            step_id=data.get('step_id', 0),
            instrument=data.get('instrument', ''),
            command=data.get('command', ''),
            parameters=data.get('parameters', {}),
            delay=data.get('delay', 0.0),
            description=data.get('description', '')
        )


class TimingSequence:
    def __init__(self, name: str = "", steps: List[TimingStep] = None):
        self.name = name
        self.steps = steps or []
        self.created_at = datetime.now()
        self.modified_at = datetime.now()

    def add_step(self, step: TimingStep):
        self.steps.append(step)
        self.modified_at = datetime.now()

    def insert_step(self, index: int, step: TimingStep):
        self.steps.insert(index, step)
        self.modified_at = datetime.now()

    def remove_step(self, step_id: int):
        self.steps = [s for s in self.steps if s.step_id != step_id]
        self.modified_at = datetime.now()

    def reorder_steps(self, new_order: List[int]):
        step_dict = {s.step_id: s for s in self.steps}
        self.steps = [step_dict[sid] for sid in new_order if sid in step_dict]
        self.modified_at = datetime.now()

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'steps': [step.to_dict() for step in self.steps],
            'created_at': self.created_at.isoformat(),
            'modified_at': self.modified_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'TimingSequence':
        sequence = cls(name=data.get('name', ''))
        sequence.created_at = datetime.fromisoformat(data.get('created_at', datetime.now().isoformat()))
        sequence.modified_at = datetime.fromisoformat(data.get('modified_at', datetime.now().isoformat()))
        for step_data in data.get('steps', []):
            sequence.add_step(TimingStep.from_dict(step_data))
        return sequence

    def save_to_file(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_from_file(cls, filepath: str) -> 'TimingSequence':
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)


class TimingEngine:
    def __init__(self):
        self.instruments: Dict[str, object] = {}
        self.running = False
        self.current_sequence: Optional[TimingSequence] = None
        self.current_step_index = 0
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.completion_callback: Optional[Callable[[bool, str], None]] = None
        self._thread: Optional[threading.Thread] = None

    def register_instrument(self, name: str, instrument):
        self.instruments[name] = instrument

    def unregister_instrument(self, name: str):
        if name in self.instruments:
            del self.instruments[name]

    def execute_step(self, step: TimingStep) -> bool:
        instrument = self.instruments.get(step.instrument)
        if not instrument:
            step.status = 'failed'
            step.result = f"仪器 {step.instrument} 未注册"
            return False

        try:
            method = getattr(instrument, step.command, None)
            if method:
                if step.parameters:
                    result = method(**step.parameters)
                else:
                    result = method()
                step.status = 'success'
                step.result = str(result)
            else:
                raw_command = step.command
                if step.parameters:
                    params_str = ' '.join([f"{k}={v}" for k, v in step.parameters.items()])
                    raw_command = f"{raw_command} {params_str}"
                result = instrument.send_command(raw_command, wait_response=True)
                step.status = 'success'
                step.result = str(result)

            step.execution_time = time.time()
            return True
        except Exception as e:
            step.status = 'failed'
            step.result = str(e)
            return False

    def run_sequence(self, sequence: TimingSequence):
        if self.running:
            return

        self.current_sequence = sequence
        self.current_step_index = 0
        self.running = True

        self._thread = threading.Thread(target=self._execute_sequence, daemon=True)
        self._thread.start()

    def _execute_sequence(self):
        if not self.current_sequence:
            self.running = False
            if self.completion_callback:
                self.completion_callback(False, "没有可执行的时序")
            return

        total_steps = len(self.current_sequence.steps)

        for i, step in enumerate(self.current_sequence.steps):
            if not self.running:
                break

            self.current_step_index = i

            if self.progress_callback:
                self.progress_callback(i + 1, total_steps, f"执行步骤 {step.step_id}: {step.description}")

            if step.delay > 0:
                time.sleep(step.delay)

            self.execute_step(step)

        self.running = False

        if self.completion_callback:
            all_success = all(s.status == 'success' for s in self.current_sequence.steps)
            message = "执行完成" if all_success else "部分步骤失败"
            self.completion_callback(all_success, message)

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def get_status(self) -> Dict:
        return {
            'running': self.running,
            'current_sequence': self.current_sequence.name if self.current_sequence else None,
            'current_step': self.current_step_index,
            'total_steps': len(self.current_sequence.steps) if self.current_sequence else 0
        }

    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        self.progress_callback = callback

    def set_completion_callback(self, callback: Callable[[bool, str], None]):
        self.completion_callback = callback