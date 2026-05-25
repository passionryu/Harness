from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MCPToolCall:
    server: str
    tool: str
    arguments: dict


@dataclass(frozen=True)
class MCPToolResult:
    ok: bool
    data: dict
    error: str | None = None


class MCPClient(Protocol):
    def call(self, call: MCPToolCall) -> MCPToolResult:
        """Call a tool from a configured MCP server."""


class MCPToolLayer:
    def __init__(self, client: MCPClient | None = None):
        self.client = client

    def call(self, call: MCPToolCall) -> MCPToolResult:
        if self.client is None:
            return MCPToolResult(ok=False, data={}, error="MCP client is not configured")
        return self.client.call(call)

