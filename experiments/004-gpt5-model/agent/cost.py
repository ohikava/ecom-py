"""TaskMetrics — собирает токены и время для одного `run_agent`-вызова.

Удовлетворяет требованию CLAUDE.md о трекинге времени ответа и токенов.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TaskMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    iterations: int = 0
    started_at: float = field(default_factory=time.time)
    elapsed_ms: int = 0

    def add_response(self, resp) -> None:
        """Извлечь usage из OpenAI ChatCompletion response."""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.output_tokens += getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            self.cached_tokens += getattr(details, "cached_tokens", 0) or 0
        self.iterations += 1

    def finalize(self) -> None:
        self.elapsed_ms = int((time.time() - self.started_at) * 1000)

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "iterations": self.iterations,
            "elapsed_ms": self.elapsed_ms,
        }
