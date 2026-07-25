"""Minimal MCP echo server for tests."""

from mcp.server.fastmcp import FastMCP

app = FastMCP("echo-test")


@app.tool()
def echo(msg: str) -> str:
    """Echo the input message."""
    return f"echo: {msg}"


if __name__ == "__main__":
    app.run()
