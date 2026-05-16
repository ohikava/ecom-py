"""Workspace — обёртка над ECOM Connect-RPC клиентом для агента.

Порт `explore/python_agent/python/workspace.py` (PCM-runtime) под ECOM-runtime.
Добавлены ECOM-only методы `exec` и `stat`. Все ответы конвертируются в dict
с `preserving_proto_field_name=True` (snake_case ключи). Если `result.truncated`,
к релевантному полю добавляется маркер `[TRUNCATED: <hint>]`.

`Workspace.answer(scratchpad, verify)` — гейт-кипер сабмита: запускает verify,
валидирует поля, отсылает в harness через `vm.answer`, после чего поднимает
исключение `AnswerSubmitted` — это сигнал `llm_loop` остановить цикл.
"""

from __future__ import annotations

from typing import Any, Callable

from bitgn.vm.ecom.ecom_pb2 import (
    AnswerRequest,
    ContextRequest,
    DeleteRequest,
    ExecRequest,
    FindRequest,
    ListRequest,
    NodeKind,
    Outcome,
    ReadRequest,
    SearchRequest,
    StatRequest,
    TreeRequest,
    WriteRequest,
)
from google.protobuf.json_format import MessageToDict


OUTCOME_BY_NAME: dict[str, Outcome] = {
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}

_KIND_MAP: dict[str, NodeKind] = {
    "all": NodeKind.NODE_KIND_UNSPECIFIED,
    "files": NodeKind.NODE_KIND_FILE,
    "dirs": NodeKind.NODE_KIND_DIR,
}


class AnswerSubmitted(Exception):
    """Поднимается из Workspace.answer() ПОСЛЕ успешного `vm.answer`.

    llm_loop ловит это исключение и возвращает финальный AgentResult.
    """

    def __init__(self, message: str, outcome: str, refs: list[str]) -> None:
        super().__init__(f"answer submitted: outcome={outcome}")
        self.message = message
        self.outcome = outcome
        self.refs = list(refs or [])


def _to_dict(msg) -> dict:
    return MessageToDict(msg, preserving_proto_field_name=True)


class Workspace:
    """Тонкая обёртка над EcomRuntimeClientSync с трекингом read/write/delete."""

    def __init__(self, vm, scratchpad: dict, *, tracker: dict | None = None) -> None:
        self._vm = vm
        self._scratchpad = scratchpad
        self._tracker = tracker if tracker is not None else {
            "read_paths": [],
            "write_paths": [],
            "delete_paths": [],
        }

    @property
    def tracker(self) -> dict:
        return self._tracker

    # ── helpers ────────────────────────────────────────────────────────

    def _track(self, bucket: str, path: str) -> None:
        paths = self._tracker.setdefault(bucket, [])
        if path not in paths:
            paths.append(path)

    @staticmethod
    def _mark_truncated(body: str, hint: str) -> str:
        marker = f"[TRUNCATED: {hint}]"
        if not body:
            return marker
        return f"{body}\n{marker}"

    # ── methods ────────────────────────────────────────────────────────

    def tree(self, root: str = "", level: int = 0) -> dict:
        """Дерево директорий. level=0 — без ограничения глубины."""
        resp = self._vm.tree(TreeRequest(root=root, level=level))
        d = _to_dict(resp)
        if resp.truncated:
            d["_truncated_note"] = (
                "[TRUNCATED: tree output hit a limit; narrow root or use ws.find / ws.search]"
            )
        return d

    def find(
        self,
        root: str = "/",
        name: str = "",
        kind: str = "all",
        limit: int = 10,
    ) -> dict:
        """Поиск файлов/каталогов по имени. kind: 'all'|'files'|'dirs'."""
        if kind not in _KIND_MAP:
            raise ValueError(f"unknown kind: {kind!r}; expected one of {list(_KIND_MAP)}")
        resp = self._vm.find(
            FindRequest(root=root, name=name, kind=_KIND_MAP[kind], limit=limit)
        )
        d = _to_dict(resp)
        if resp.truncated:
            d["_truncated_note"] = (
                "[TRUNCATED: find hit limit; raise limit or narrow root/name]"
            )
        return d

    def search(self, root: str = "/", pattern: str = "", limit: int = 10) -> dict:
        """Regex-поиск по содержимому. Возвращает {'matches': [{'path','line','line_text'}]}."""
        resp = self._vm.search(
            SearchRequest(root=root, pattern=pattern, limit=limit)
        )
        d = _to_dict(resp)
        if resp.truncated:
            d["_truncated_note"] = (
                "[TRUNCATED: search hit limit; narrow pattern/root or raise limit]"
            )
        return d

    def list(self, path: str = "/") -> dict:
        """Листинг директории. Возвращает {'path', 'entries': [{'name','kind','content_type'}]}."""
        resp = self._vm.list(ListRequest(path=path))
        return _to_dict(resp)

    def read(
        self,
        path: str,
        number: bool = False,
        start_line: int = 0,
        end_line: int = 0,
    ) -> dict:
        """Чтение файла. Трекает путь в tracker.read_paths."""
        self._track("read_paths", path)
        resp = self._vm.read(
            ReadRequest(
                path=path,
                number=number,
                start_line=start_line,
                end_line=end_line,
            )
        )
        d = _to_dict(resp)
        if resp.truncated:
            d["content"] = self._mark_truncated(
                d.get("content", ""),
                "file output hit a limit; use start_line/end_line to read a smaller range",
            )
        return d

    def write(self, path: str, content: str) -> dict:
        """Запись файла. Трекает путь в tracker.write_paths."""
        resp = self._vm.write(WriteRequest(path=path, content=content))
        self._track("write_paths", path)
        return _to_dict(resp)

    def delete(self, path: str) -> dict:
        """Удаление файла/директории. Трекает путь в tracker.delete_paths."""
        resp = self._vm.delete(DeleteRequest(path=path))
        self._track("delete_paths", path)
        return _to_dict(resp)

    def stat(self, path: str) -> dict:
        """ECOM: метаданные пути (kind, content_type, writable, write_schema, description)."""
        resp = self._vm.stat(StatRequest(path=path))
        return _to_dict(resp)

    def exec(
        self,
        path: str,
        args: list[str] | None = None,
        stdin: str = "",
    ) -> dict:
        """ECOM: запуск исполняемого пути (например, /bin/sql, /bin/date).

        Пример SQL: ws.exec('/bin/sql', stdin='SELECT * FROM products LIMIT 10')
        """
        resp = self._vm.exec(
            ExecRequest(path=path, args=list(args or []), stdin=stdin)
        )
        d = _to_dict(resp)
        if resp.truncated:
            d["stdout"] = self._mark_truncated(
                d.get("stdout", ""),
                "exec output hit a limit; narrow args/stdin or fetch via ws.read on a specific file",
            )
        return d

    def context(self) -> dict:
        """Текущее UTC-время с сервера: {'unix_time': int, 'time': 'RFC3339'}."""
        return _to_dict(self._vm.context(ContextRequest()))

    # ── finale ─────────────────────────────────────────────────────────

    def answer(self, scratchpad: dict, verify: Callable[[dict], Any]) -> None:
        """Финальная сабмишн. Гейт-кипер с verify(sp).

        Алгоритм:
          1. verify должен быть callable.
          2. verify(scratchpad) → truthy, иначе ValueError("VERIFICATION FAILED").
          3. Извлечь message/outcome/refs из scratchpad.
          4. Если message выглядит как набор абсолютных путей — заменить на относительные.
          5. Валидировать outcome.
          6. Проверить required fields (answer+outcome всегда; refs для не-OK).
          7. Warning-и: непокрытые refs vs tracker.read_paths; writes на блокирующем outcome.
          8. Отправить vm.answer(AnswerRequest(...)).
          9. Поднять AnswerSubmitted — сигнал llm_loop остановиться.
        """
        if not callable(verify):
            msg = (
                "SUBMISSION BLOCKED: verify must be a callable function.\n"
                "Define `def verify(sp): ...` and pass it as ws.answer(scratchpad, verify)."
            )
            print(msg)
            raise ValueError(msg)

        try:
            verify_result = verify(scratchpad)
        except Exception as exc:
            msg = (
                f"VERIFICATION FUNCTION ERROR: {exc!r}\n"
                f"Fix your verify(sp) function and retry."
            )
            print(msg)
            raise ValueError(msg) from exc

        if not verify_result:
            msg = (
                "VERIFICATION FAILED: verify(scratchpad) returned a falsy value.\n"
                "Fix scratchpad gates/fields and call ws.answer() again."
            )
            print(msg)
            raise ValueError(msg)

        message = scratchpad.get("answer", "")
        outcome = scratchpad.get("outcome", "OUTCOME_OK")
        refs = scratchpad.get("refs", []) or []

        if isinstance(message, str) and message.strip():
            lines = [ln for ln in message.split("\n") if ln.strip()]
            if lines and all(ln.strip().startswith("/") for ln in lines):
                message = "\n".join(ln.strip().lstrip("/") for ln in lines)
                scratchpad["answer"] = message

        if outcome not in OUTCOME_BY_NAME:
            msg = (
                f"SUBMISSION BLOCKED: unknown outcome {outcome!r}. "
                f"Valid: {', '.join(OUTCOME_BY_NAME)}"
            )
            print(msg)
            raise ValueError(msg)

        required = ["answer", "outcome"]
        if outcome != "OUTCOME_OK":
            required.append("refs")
        missing = [k for k in required if k not in scratchpad]
        if missing:
            msg = (
                f"SUBMISSION BLOCKED: scratchpad missing required keys: {missing}.\n"
                f"Populate scratchpad['answer'], scratchpad['outcome']"
                f"{', scratchpad[\"refs\"]' if 'refs' in missing else ''}, then retry."
            )
            print(msg)
            raise ValueError(msg)

        read_paths = list(self._tracker.get("read_paths", []))
        refs_set = set(refs)
        missing_refs = [p for p in read_paths if p not in refs_set]
        if missing_refs:
            sample = missing_refs[:5]
            print(
                f"WARNING: {len(missing_refs)} read path(s) not present in refs: {sample}"
            )

        if outcome != "OUTCOME_OK":
            writes = list(self._tracker.get("write_paths", []))
            if writes:
                print(
                    f"WARNING: outcome={outcome} but {len(writes)} write(s) recorded: "
                    f"{writes[:5]}. Blocked outcomes should produce zero file writes."
                )

        self._vm.answer(
            AnswerRequest(
                message=message,
                outcome=OUTCOME_BY_NAME[outcome],
                refs=list(refs),
            )
        )

        raise AnswerSubmitted(message=message, outcome=outcome, refs=list(refs))
