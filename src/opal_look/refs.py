"""Cross-resource reference checks for 409 conflict semantics.

Each function answers whether a resource is referenced by nonterminal
sessions or other configuration. Stubs return empty results until the
corresponding store tables land in later steps.
"""

from __future__ import annotations

from .store import Store


def nonterminal_sessions_referencing(store: Store, kind: str, resource_id: str) -> int:
    """Count of nonterminal sessions referencing the resource.

    kind: 'engine' | 'model' | 'source' | 'media' | 'profile'.
    """
    return store.sessions.count_nonterminal(kind, str(resource_id))


def profiles_referencing_model(store: Store, model_id: str) -> int:
    return store.profiles.count_for_model(model_id)


def media_dependencies(store: Store, model_id: str) -> int:
    """Media-backed source dependencies land with media sources."""
    return 0


def media_exists(store: Store, media_id: str) -> bool:
    """Unexpired registered media exists (used for source availability/refs)."""
    from .timeutil import expired

    row = store.media.get(media_id)
    return bool(row is not None and not expired(row["expires_at"]))
