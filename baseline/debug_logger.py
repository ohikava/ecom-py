import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlDebugLogger:
    def __init__(self, directory: str | Path = ".") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self._next_log_path()
        self._handle = self.path.open("a", encoding="utf-8")

    def _next_log_path(self) -> Path:
        prefix = datetime.now().strftime("%d-%m-%y")
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)\.jsonl$")

        max_iteration = 0
        for candidate in self.directory.glob(f"{prefix}-*.jsonl"):
            match = pattern.match(candidate.name)
            if not match:
                continue
            max_iteration = max(max_iteration, int(match.group(1)))

        return self.directory / f"{prefix}-{max_iteration + 1}.jsonl"

    def log(self, event: str, **payload: Any) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "event": event,
            **payload,
        }
        line = json.dumps(record, ensure_ascii=False, default=self._json_default)
        self._handle.write(f"{line}\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    @staticmethod
    def _json_default(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return str(value)
