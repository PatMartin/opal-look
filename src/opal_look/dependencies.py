"""FastAPI dependency providers (injection seams for API <-> infrastructure)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .store import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


StoreDep = Annotated[Store, Depends(get_store)]
