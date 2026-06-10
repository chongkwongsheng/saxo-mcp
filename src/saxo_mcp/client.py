"""Thin httpx wrapper around the Saxo OpenAPI.

Handles:
  - base URL selection (sim vs live) via auth.api_base()
  - bearer token injection (auth.get_access_token())
  - one-shot retry on 401 after a forced refresh
"""

from __future__ import annotations

from typing import Any

import httpx

from . import auth


def _body_of(r: httpx.Response) -> dict:
    """Decode a response body the same way request_raw does: empty -> {},
    JSON when parseable, else {"raw": text}. Used for the H4 early-return on
    refresh failure so the 401 body is shaped consistently."""
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


class SaxoClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=auth.api_base(), timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.get_access_token()}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any | None = None,
    ) -> dict:
        r = self._client.request(
            method, path, headers=self._headers(), params=params, json=json
        )
        if r.status_code == 401:
            # Token might have been invalidated server-side; try one refresh.
            tokens = auth._load_tokens()  # type: ignore[attr-defined]
            if tokens:
                auth._refresh(tokens)  # type: ignore[attr-defined]
                r = self._client.request(
                    method, path, headers=self._headers(), params=params, json=json
                )
        if r.is_error:
            raise RuntimeError(
                f"Saxo API {method} {path} failed: {r.status_code} {r.text}"
            )
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any | None = None,
    ) -> tuple[int, dict]:
        """Like _request but NEVER raises on HTTP error status — returns
        (status_code, body_dict). Callers that need to branch on 2xx/4xx/5xx
        (e.g. OCO placement status discipline) use this; everything else
        keeps the raising convenience methods. Still does the one-shot
        401 refresh retry."""
        r = self._client.request(
            method, path, headers=self._headers(), params=params, json=json
        )
        if r.status_code == 401:
            # H4: request_raw must NEVER raise. auth._refresh can raise on a
            # failed/expired refresh chain — swallow that and return the
            # ORIGINAL 401 rather than propagating (callers map 4xx ->
            # REJECTED). _request (the raising twin) keeps its own behaviour.
            tokens = auth._load_tokens()  # type: ignore[attr-defined]
            if tokens:
                try:
                    auth._refresh(tokens)  # type: ignore[attr-defined]
                except Exception:
                    return r.status_code, _body_of(r)
                r = self._client.request(
                    method, path, headers=self._headers(), params=params, json=json
                )
        if not r.content:
            return r.status_code, {}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text}

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Any | None = None) -> dict:
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: Any | None = None) -> dict:
        return self._request("PATCH", path, json=json)

    def put(self, path: str, json: Any | None = None) -> dict:
        return self._request("PUT", path, json=json)

    def delete(self, path: str, params: dict | None = None) -> dict:
        return self._request("DELETE", path, params=params)


_client: SaxoClient | None = None


def get_client() -> SaxoClient:
    global _client
    if _client is None:
        _client = SaxoClient()
    return _client
