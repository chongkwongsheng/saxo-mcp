# tests/conftest.py
"""Shared fixtures: FakeClient mimics SaxoClient's contract offline.

Queue responses per (METHOD, path). A queued entry is either a body dict
(status 200) or a (status_code, body) tuple. get/post/delete raise
RuntimeError on status >= 400 (same contract as SaxoClient._request);
request_raw never raises and returns (status, body).
"""
from __future__ import annotations

from collections import deque

import pytest


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self._queues: dict[tuple[str, str], deque] = {}

    def queue(self, method: str, path: str, *responses):
        q = self._queues.setdefault((method.upper(), path), deque())
        for r in responses:
            q.append(r)

    def _next(self, method: str, path: str, payload):
        self.calls.append((method.upper(), path, payload))
        q = self._queues.get((method.upper(), path))
        if not q:
            raise AssertionError(f"FakeClient: no response queued for {method} {path}")
        item = q.popleft()
        if isinstance(item, tuple):
            return item  # (status, body)
        return (200, item)

    # --- SaxoClient-contract methods (raise on error status) ---
    def get(self, path, params=None):
        status, body = self._next("GET", path, params)
        if status >= 400:
            raise RuntimeError(f"Saxo API GET {path} failed: {status} {body}")
        return body

    def post(self, path, json=None):
        status, body = self._next("POST", path, json)
        if status >= 400:
            raise RuntimeError(f"Saxo API POST {path} failed: {status} {body}")
        return body

    def delete(self, path, params=None):
        status, body = self._next("DELETE", path, params)
        if status >= 400:
            raise RuntimeError(f"Saxo API DELETE {path} failed: {status} {body}")
        return body

    # --- status-aware variant (added to the real client in Task 2) ---
    def request_raw(self, method, path, *, params=None, json=None):
        return self._next(method, path, json if json is not None else params)


@pytest.fixture
def fake_client():
    return FakeClient()
