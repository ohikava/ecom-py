"""OpenAI function-tool schema для единственного инструмента execute_code."""

EXECUTE_CODE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_code",
        "description": (
            "Execute Python 3 code against the ECOM workspace. "
            "Pre-loaded names: `ws` (Workspace — tree, find, search, list, read, write, "
            "delete, stat, exec, context, answer), `scratchpad` (persistent dict, "
            "rendered every turn into the system prompt). Variables you define persist "
            "between calls. To submit: populate scratchpad['answer'], scratchpad['outcome'], "
            "scratchpad['refs'], define `def verify(sp): ...`, then call "
            "ws.answer(scratchpad, verify). Use ws.exec('/bin/sql', stdin='SELECT ...') "
            "for SQL. Use print() for output."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python 3 source to execute.",
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}

TOOLS = [EXECUTE_CODE_TOOL]
