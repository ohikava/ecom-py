"""HTTP shim that lets Codex CLI 0.130 talk to OpenRouter for MCP-tool tasks.

Why this exists
---------------
Codex 0.121+ sends MCP server tools to the `/v1/responses` endpoint grouped
under a `{"type":"namespace","name":"mcp__<server>__","tools":[...]}` wrapper.
The built-in OpenAI Responses endpoint understands this, but the OpenRouter
proxy passes it through untouched to upstream models like DeepSeek V4, which
do NOT understand `type: "namespace"` and silently ignore those tools.

Result: Codex shows the MCP server as enabled, the model receives an empty
tool inventory, and answers "no MCP tools available". See
https://github.com/router-for-me/CLIProxyAPI/issues/3298 (still open).

This proxy listens on 127.0.0.1, accepts the Codex /v1/responses POST,
walks `payload["tools"]`, and rewrites every namespace wrapper into a flat
list of `{"type":"function", "name":"mcp__<server>__<tool>", ...}` entries.
The flat names are exactly what Codex already uses internally to dispatch
MCP calls, so function_calls in the streamed reply round-trip back without
any response-side rewriting.

Run it from the same shell that has OPENROUTER_API_KEY exported:
    python -m codex_namespace_proxy            # binds 127.0.0.1:18088

Then point Codex at it:
    -c 'model_providers.<name>.base_url="http://127.0.0.1:18088/v1"'
    -c 'model_providers.<name>.wire_api="responses"'
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx


UPSTREAM_BASE = os.environ.get(
    "PROXY_UPSTREAM_BASE", "https://openrouter.ai/api/v1"
)
UPSTREAM_KEY_ENV = os.environ.get("PROXY_UPSTREAM_KEY_ENV", "OPENROUTER_API_KEY")
PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "18088"))
PROXY_LOG = os.environ.get("PROXY_LOG", "")


def _log(msg: str) -> None:
    line = f"[proxy {time.strftime('%H:%M:%S')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    if PROXY_LOG:
        try:
            with open(PROXY_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _flatten_tools(
    tools: list[Any],
) -> tuple[list[dict[str, Any]], int, dict[str, tuple[str, str]]]:
    """Walk Codex tools array; expand any `type=namespace` into flat functions.

    Returns (new_tools, expanded_count, name_map). `name_map` maps the flat
    name we present to the upstream model (`mcp__server__tool`) back to
    `(namespace, sub_name)` so we can restore the namespace field on the
    response side — Codex's `ResponseItem::FunctionCall` requires it to
    dispatch the call into the right MCP server.
    """
    out: list[dict[str, Any]] = []
    expanded = 0
    name_map: dict[str, tuple[str, str]] = {}
    for t in tools:
        if not isinstance(t, dict):
            out.append(t)
            continue
        if t.get("type") == "namespace":
            ns_name = t.get("name", "")
            for sub in t.get("tools", []):
                if not isinstance(sub, dict):
                    continue
                new = dict(sub)
                sub_name = sub.get("name", "")
                flat = f"{ns_name}{sub_name}"
                new["name"] = flat
                out.append(new)
                name_map[flat] = (ns_name, sub_name)
                expanded += 1
        else:
            out.append(t)
    return out, expanded, name_map


# Per-request state shared between request flatten and response SSE rewrite.
# Keyed by item_id so we can intercept argument delta/done events that follow
# a renamed output_item.added/done.
class _ResponseRewriter:
    """Stateful SSE rewriter: scans `response.output_item.{added,done}` events
    for function_call items whose `name` is a flat `mcp__<server>__<tool>` we
    flattened on the request side, and splits it back into
    `{name: tool, namespace: mcp__<server>__}` — the form Codex's protocol
    parser actually dispatches.
    """

    def __init__(self, name_map: dict[str, tuple[str, str]]):
        self.name_map = name_map
        self._renamed_items: set[str] = set()  # item_ids we've rewritten

    def rewrite_event(self, event_obj: dict[str, Any]) -> dict[str, Any]:
        etype = event_obj.get("type", "")
        # `output_item.added` and `output_item.done` carry the full item object
        if etype in (
            "response.output_item.added",
            "response.output_item.done",
        ):
            item = event_obj.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                self._maybe_rewrite_item(item)
        # `response.completed` includes the full response.output array
        elif etype == "response.completed":
            resp = event_obj.get("response")
            if isinstance(resp, dict):
                out = resp.get("output")
                if isinstance(out, list):
                    for it in out:
                        if isinstance(it, dict) and it.get("type") == "function_call":
                            self._maybe_rewrite_item(it)
        return event_obj

    def _maybe_rewrite_item(self, item: dict[str, Any]) -> None:
        flat = item.get("name") or ""
        ns_and_tool = self.name_map.get(flat)
        if not ns_and_tool:
            return
        ns, sub_name = ns_and_tool
        item["name"] = sub_name
        item["namespace"] = ns
        item_id = item.get("id")
        if isinstance(item_id, str):
            self._renamed_items.add(item_id)


def _stream_with_rewrite(
    resp: "httpx.Response",
    wfile: Any,
    rewriter: "_ResponseRewriter | None",
    sse_dump: Any | None,
) -> None:
    """Forward SSE bytes from `resp` to `wfile`, parsing per-event so we can
    surgically rewrite `data:` JSON when needed.

    SSE event boundary = blank line (\\n\\n). Events split across chunks are
    held in `buf` until a full event is collected. If `rewriter` is None this
    degenerates to a plain pass-through pipe.
    """
    buf = b""
    for chunk in resp.iter_bytes():
        if not chunk:
            continue
        if rewriter is None:
            wfile.write(chunk)
            wfile.flush()
            if sse_dump:
                sse_dump.write(chunk)
                sse_dump.flush()
            continue
        buf += chunk
        # Split on \n\n event boundaries; the final piece may be partial.
        while b"\n\n" in buf:
            raw_event, _, buf = buf.partition(b"\n\n")
            rewritten = _rewrite_sse_event(raw_event, rewriter)
            wfile.write(rewritten + b"\n\n")
            wfile.flush()
            if sse_dump:
                sse_dump.write(rewritten + b"\n\n")
                sse_dump.flush()
    if buf:
        # tail (no trailing boundary) — pass through
        wfile.write(buf)
        wfile.flush()
        if sse_dump:
            sse_dump.write(buf)
            sse_dump.flush()


def _rewrite_sse_event(raw: bytes, rewriter: _ResponseRewriter) -> bytes:
    """Parse one SSE event block, rewrite `data:` JSON when needed, re-serialise.

    Per spec, an SSE event is a sequence of lines like `field: value`.
    We only touch lines that start with `data:` — everything else (event:,
    id:, retry:) is passed through verbatim.
    """
    lines = raw.split(b"\n")
    out_lines: list[bytes] = []
    for line in lines:
        if not line.startswith(b"data:"):
            out_lines.append(line)
            continue
        # Preserve the original whitespace after the colon (typically one space).
        payload = line[len(b"data:") :].lstrip(b" ")
        if not payload or payload == b"[DONE]":
            out_lines.append(line)
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            out_lines.append(line)
            continue
        obj = rewriter.rewrite_event(obj)
        out_lines.append(b"data: " + json.dumps(obj).encode("utf-8"))
    return b"\n".join(out_lines)


class _Handler(BaseHTTPRequestHandler):
    server_version = "CodexNamespaceProxy/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence default access log
        return

    def do_GET(self) -> None:  # pragma: no cover — only used for /healthz
        if self.path in ("/", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404, "only /v1/* is proxied")
            return
        length = int(self.headers.get("content-length") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON body")
            return

        rewriter: _ResponseRewriter | None = None
        if self.path.startswith("/v1/responses") and isinstance(
            payload.get("tools"), list
        ):
            new_tools, expanded, name_map = _flatten_tools(payload["tools"])
            if expanded:
                _log(
                    f"flattened {expanded} MCP namespace tools "
                    f"(tools_in={len(payload['tools'])} → out={len(new_tools)})"
                )
            payload["tools"] = new_tools
            if name_map:
                rewriter = _ResponseRewriter(name_map)

        # Optional: dump full outgoing body for diagnostics. Set PROXY_DUMP=/tmp/x.json
        dump_path = os.environ.get("PROXY_DUMP", "")
        if dump_path:
            try:
                with open(dump_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                _log(f"dumped outgoing payload → {dump_path}")
            except OSError as exc:
                _log(f"dump failed: {exc}")

        upstream_key = os.environ.get(UPSTREAM_KEY_ENV, "")
        if not upstream_key:
            self.send_error(500, f"missing env {UPSTREAM_KEY_ENV}")
            return

        url = UPSTREAM_BASE.rstrip("/") + self.path[len("/v1") :]
        is_stream = bool(payload.get("stream"))
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if is_stream else "application/json",
        }

        try:
            timeout = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
            with httpx.Client(timeout=timeout) as client:
                if is_stream:
                    with client.stream(
                        "POST", url, json=payload, headers=headers
                    ) as resp:
                        self.send_response(resp.status_code)
                        ct = resp.headers.get("content-type", "text/event-stream")
                        self.send_header("Content-Type", ct)
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        sse_dump_path = os.environ.get("PROXY_SSE_DUMP", "")
                        sse_dump = (
                            open(sse_dump_path, "ab") if sse_dump_path else None
                        )
                        try:
                            _stream_with_rewrite(
                                resp,
                                self.wfile,
                                rewriter,
                                sse_dump,
                            )
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        finally:
                            if sse_dump:
                                sse_dump.close()
                else:
                    resp = client.post(url, json=payload, headers=headers)
                    self.send_response(resp.status_code)
                    self.send_header(
                        "Content-Type",
                        resp.headers.get("content-type", "application/json"),
                    )
                    self.end_headers()
                    self.wfile.write(resp.content)
        except httpx.HTTPError as exc:
            _log(f"upstream error: {exc}")
            self.send_error(502, f"upstream error: {exc}")
        except Exception as exc:  # pragma: no cover
            _log("unexpected error:\n" + traceback.format_exc())
            try:
                self.send_error(500, f"proxy crashed: {exc}")
            except Exception:
                pass


def serve_forever() -> None:
    srv = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), _Handler)
    srv.daemon_threads = True
    _log(
        f"listening on http://{PROXY_HOST}:{PROXY_PORT}  upstream={UPSTREAM_BASE} "
        f"key_env={UPSTREAM_KEY_ENV}"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve_forever()
