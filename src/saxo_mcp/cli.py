"""CLI: `saxo-mcp login | status | logout | serve`."""

from __future__ import annotations

import json

import click

from . import auth, server


@click.group()
def cli() -> None:
    """Saxo MCP — local OAuth + MCP server for Saxo OpenAPI."""


@cli.command()
def login() -> None:
    """Run OAuth2 Code flow and cache tokens to ~/.saxo-mcp/tokens.json."""
    auth.login()


@cli.command()
def status() -> None:
    """Show current authentication status."""
    click.echo(json.dumps(auth.status(), indent=2))


@cli.command()
def logout() -> None:
    """Delete cached tokens."""
    auth.logout()
    click.echo("Logged out.")


@cli.command()
def serve() -> None:
    """Run the MCP server over stdio (for use by Claude Code / other MCP clients)."""
    server.main()


if __name__ == "__main__":
    cli()
