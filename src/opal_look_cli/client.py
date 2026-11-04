"""Minimal httpx wrapper: requests, ETag handling, error surfacing."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None,
                 inner: httpx.Client | None = None) -> None:
        if inner is None:
            headers = {}
            token = os.environ.get("OPAL_LOOK_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            inner = httpx.Client(
                base_url=base_url, transport=transport, timeout=30.0,
                headers=headers)
        self._client = inner

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def etag_for(self, path: str) -> str:
        resp = self.get(path)
        return resp.headers.get("etag", '"*"')

    def mutate(self, method: str, path: str, etag_path: str | None = None, **kwargs):
        etag = self.etag_for(etag_path or "/api/v1/settings/")
        return self.request(method, path, headers={"If-Match": etag}, **kwargs)

    def close(self) -> None:
        self._client.close()


def unwrap(resp: httpx.Response) -> Any:
    """Return parsed body or raise a terse error for OpalError responses."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("error", {})
            raise SystemExit(
                f"{resp.status_code} {detail.get('code', 'error')}: {detail.get('message', resp.text)}"
            )
        except SystemExit:
            raise
        except Exception:
            raise SystemExit(f"{resp.status_code}: {resp.text}")
    if resp.status_code == 204:
        return None
    ctype = resp.headers.get("content-type", "")
    if "application/json" in ctype:
        return resp.json()
    return resp.content
