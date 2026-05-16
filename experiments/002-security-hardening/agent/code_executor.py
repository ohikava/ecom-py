"""CodeExecutor — in-process замена runtime-exec.ts.

Один namespace на task. exec(code) запускает строку Python в shared globals,
ловит stdout/stderr через redirect_stdout/redirect_stderr, конвертирует ошибки
в форматированный текст. `AnswerSubmitted` пробрасывается наверх в llm_loop;
KeyboardInterrupt — тоже, чтобы Ctrl+C работал.

В отличие от оригинала (subprocess + tmpfile + atexit), здесь scratchpad — это
обычный dict, переданный по ссылке. Переменные между вызовами живут в self._ns.
"""

from __future__ import annotations

import io
import json
import traceback
from contextlib import redirect_stderr, redirect_stdout

from workspace import AnswerSubmitted


_MAX_OUTPUT = 32_000  # символов; обрезаем длинный stdout/stderr перед отдачей модели


def _build_prelude_namespace(ws, scratchpad: dict) -> dict:
    """Соберём словарь, эквивалентный оригинальному Python prelude.

    Из `runtime-exec.ts` (buildPythonPrelude) — без atexit и без файлов.
    """
    import base64
    import csv
    import hashlib
    import json as _json
    import math
    import os
    import re
    import sys
    from collections import Counter, defaultdict
    from datetime import date, datetime, timedelta
    from pathlib import PurePosixPath

    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore

    try:
        from dateutil import parser as dateutil_parser  # type: ignore
        from dateutil.relativedelta import relativedelta  # type: ignore
    except ImportError:
        dateutil_parser = None  # type: ignore
        relativedelta = None  # type: ignore

    ns: dict = {
        "__name__": "__execute_code__",
        "__builtins__": __builtins__,
        # стандартные модули
        "json": _json,
        "sys": sys,
        "os": os,
        "re": re,
        "csv": csv,
        "math": math,
        "hashlib": hashlib,
        "base64": base64,
        "yaml": yaml,
        # datetime/collections/pathlib
        "datetime": datetime,
        "timedelta": timedelta,
        "date": date,
        "defaultdict": defaultdict,
        "Counter": Counter,
        "PurePosixPath": PurePosixPath,
        # dateutil (опционально)
        "dateutil_parser": dateutil_parser,
        "relativedelta": relativedelta,
        # workspace + scratchpad
        "ws": ws,
        "scratchpad": scratchpad,
    }
    return ns


class CodeExecutor:
    """Один CodeExecutor на task. Namespace персистится между execute()-вызовами."""

    def __init__(self, ws, scratchpad: dict) -> None:
        self._ns = _build_prelude_namespace(ws, scratchpad)
        self._scratchpad = scratchpad
        # фиксируем имена prelude — на будущее, если захочется чистить ns
        self._prelude_names = set(self._ns.keys())

    @property
    def namespace(self) -> dict:
        return self._ns

    def execute(self, code: str) -> tuple[str, bool]:
        """Запустить code в shared namespace. Возвращает (output, is_error).

        Пробрасывает `AnswerSubmitted` и `KeyboardInterrupt`. Любые другие
        исключения ловятся, форматируются как traceback и возвращаются текстом.
        """
        out_buf, err_buf = io.StringIO(), io.StringIO()
        is_error = False

        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                try:
                    compiled = compile(code, "<execute_code>", "exec")
                except SyntaxError:
                    err_buf.write(traceback.format_exc())
                    is_error = True
                else:
                    try:
                        exec(compiled, self._ns, self._ns)
                    except AnswerSubmitted:
                        raise
                    except KeyboardInterrupt:
                        raise
                    except SystemExit as exc:
                        err_buf.write(f"SystemExit({exc.code!r})\n")
                        is_error = True
                    except BaseException:
                        err_buf.write(traceback.format_exc())
                        is_error = True
        except AnswerSubmitted:
            raise
        except KeyboardInterrupt:
            raise

        return self._format_output(out_buf.getvalue(), err_buf.getvalue(), is_error)

    def _format_output(
        self, stdout: str, stderr: str, is_error: bool
    ) -> tuple[str, bool]:
        parts: list[str] = []
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append("[stderr]\n" + stderr.rstrip())

        # эхо scratchpad (как _print_scratchpad_state в оригинале)
        if self._scratchpad:
            try:
                pad = json.dumps(self._scratchpad, default=str)
                parts.append(f"[scratchpad: {pad}]")
            except (TypeError, ValueError):
                parts.append("[scratchpad: <non-serializable>]")

        text = "\n".join(parts) if parts else "ok"

        if len(text) > _MAX_OUTPUT:
            head = text[: _MAX_OUTPUT // 2]
            tail = text[-_MAX_OUTPUT // 2 :]
            text = (
                f"{head}\n[TRUNCATED: output exceeded {_MAX_OUTPUT} chars; "
                f"narrow scope or print less]\n{tail}"
            )

        return text, is_error
