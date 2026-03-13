"""Fake MCP server for testing tool registration and invocation without MCP protocol."""


class FakeMCP:
    """Minimal stand-in for FastMCP that captures registered tool functions."""

    def __init__(self):
        self.tools: dict[str, callable] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator

    async def call(self, tool_name: str, **kwargs):
        if tool_name not in self.tools:
            raise KeyError(f"Tool {tool_name!r} not registered. Available: {sorted(self.tools)}")
        return await self.tools[tool_name](**kwargs)
