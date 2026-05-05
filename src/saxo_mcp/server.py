"""FastMCP server entrypoint. Registers read tools always, write tools conditionally."""

from __future__ import annotations

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from . import tools_read, tools_write

load_dotenv()

mcp = FastMCP("saxo-mcp")
tools_read.register(mcp)
tools_write.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
