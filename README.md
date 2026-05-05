# saxo-mcp

Local MCP server for the Saxo Bank OpenAPI. Defaults to the **SIM**
(simulation) environment. Read tools are always on. Write tools
(place/cancel/modify order) are gated behind an explicit env flag **and**
a `confirm=True` argument on each call.

## One-time setup

### 1. Register a Saxo developer app

1. Sign up at <https://www.developer.saxo/accounts/sim/signup> (same email
   as your SaxoTraderGO demo login is fine).
2. Go to <https://www.developer.saxo/openapi/appmanagement#/> and create
   an application:
   - **Redirect URLs**: `http://localhost:52736/callback`
   - **Grant Type**: `Code`
   - **Environment**: SIM
3. Open the created app and copy **AppKey** and **AppSecret**. The secret
   is typically shown only once — grab it immediately.

### 2. Install

```bash
git clone https://github.com/<your-user>/saxo-mcp.git
cd saxo-mcp
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -e .
```

> **Python 3.14 note.** This repo declares `requires-python = ">=3.10"`,
> but Python 3.14 is very new and some dependency wheels may not yet exist
> for it on Windows. If `pip install -e .` fails to build something,
> install Python 3.12 and create the venv with
> `py -3.12 -m venv .venv` instead.

### 3. Configure

```bash
copy .env.example .env
```

Open `.env` and fill in:

```
SAXO_APP_KEY=<from developer.saxo>
SAXO_APP_SECRET=<from developer.saxo>
SAXO_ENV=sim
SAXO_REDIRECT_PORT=52736
SAXO_WRITES_ENABLED=          # leave blank for read-only
```

### 4. Log in

```bash
saxo-mcp login
```

This opens your browser to the Saxo SIM login page. After you sign in,
Saxo redirects to `http://localhost:52736/callback`, a small local HTTP
server catches the code, exchanges it for access + refresh tokens, and
saves them to `%USERPROFILE%\.saxo-mcp\tokens.json`.

Check status anytime:

```bash
saxo-mcp status
```

## Running the MCP server

```bash
saxo-mcp serve
```

That's the stdio entrypoint — you don't run it manually in normal use;
Claude Code launches it. See below.

## Wire into Claude Code

Create `.mcp.json` in whichever project you want Saxo available, or add
to `~/.claude/settings.json` under `mcpServers`:

Use the absolute path to the `saxo-mcp` executable inside your venv.

**Windows** (`.venv\Scripts\saxo-mcp.exe`):

```json
{
  "mcpServers": {
    "saxo": {
      "command": "C:\\path\\to\\saxo-mcp\\.venv\\Scripts\\saxo-mcp.exe",
      "args": ["serve"]
    }
  }
}
```

**macOS / Linux** (`.venv/bin/saxo-mcp`):

```json
{
  "mcpServers": {
    "saxo": {
      "command": "/path/to/saxo-mcp/.venv/bin/saxo-mcp",
      "args": ["serve"]
    }
  }
}
```

Then `/mcp` inside Claude Code should list the `saxo` server and its tools.

## Tool inventory

### Read (always registered)

| Tool | Endpoint |
|---|---|
| `get_user_info` | `/port/v1/users/me` |
| `get_accounts` | `/port/v1/accounts/me` |
| `get_balances` | `/port/v1/balances/me` |
| `get_positions` | `/port/v1/positions/me` |
| `get_closed_positions` | `/port/v1/closedpositions/me` |
| `get_orders` | `/port/v1/orders/me` |
| `search_instruments` | `/ref/v1/instruments` |
| `get_instrument_details` | `/ref/v1/instruments/details/{uic}/{asset}` |
| `get_info_price` | `/trade/v1/infoprices` |
| `get_price_history` | `/chart/v1/charts` |

### Write (gated)

- `precheck_order` — always registered, calls Saxo's `/trade/v2/orders/precheck`
  (read-only on their side; returns estimated cost, margin, validation errors).
- `place_order` — registered only when `SAXO_WRITES_ENABLED=1` (SIM) or
  `live-i-mean-it` (LIVE). Requires `confirm=True`.
- `cancel_order` — same gate + `confirm=True`.
- `modify_order` — same gate + `confirm=True`.

**Enabling writes on SIM**:

```
SAXO_WRITES_ENABLED=1
```

**Enabling writes on LIVE** (don't, unless you're really sure):

```
SAXO_ENV=live
SAXO_WRITES_ENABLED=live-i-mean-it
```

## Persistence caveat

Saxo's SIM refresh tokens are short-lived and *roll* — each refresh returns
a new refresh token that replaces the old one. If the server doesn't call
Saxo within the refresh window, the tokens expire and you'll need to rerun
`saxo-mcp login`. In practice, once the MCP server is active in a Claude
session it stays logged in; across multi-day gaps, expect to re-login.

## Files

```
saxo-mcp/
├── .env.example
├── .gitignore
├── LICENSE
├── pyproject.toml
├── README.md
└── src/saxo_mcp/
    ├── __init__.py
    ├── auth.py         # OAuth2 Code flow, local callback, token cache + refresh
    ├── client.py       # httpx wrapper with bearer injection + 401 retry
    ├── server.py       # FastMCP entrypoint
    ├── tools_read.py   # 10 read tools
    ├── tools_write.py  # precheck + gated place/cancel/modify
    └── cli.py          # login / status / logout / serve
```

## Security notes

- **Never commit `.env`** — it holds your `SAXO_APP_KEY` / `SAXO_APP_SECRET`.
  The provided `.gitignore` excludes it; verify with `git status` before
  every commit.
- OAuth tokens are written to `%USERPROFILE%\.saxo-mcp\tokens.json`
  (Windows) or `~/.saxo-mcp/tokens.json` (macOS/Linux), **outside** the
  repo. They never enter version control.
- Saxo SIM credentials cannot move money, but treat them with the same
  care as production keys: revoke and rotate via
  [developer.saxo](https://www.developer.saxo/openapi/appmanagement#/) if
  ever exposed.
- The write-tools gate (`SAXO_WRITES_ENABLED`) is intentionally
  three-layered: env flag, `confirm=True` argument, and an explicit
  `live-i-mean-it` token for live mode. Don't disable any layer.

## License

MIT — see [`LICENSE`](LICENSE).

This project is **not affiliated with Saxo Bank**. "Saxo" is a trademark
of Saxo Bank A/S; this is a third-party API client.
