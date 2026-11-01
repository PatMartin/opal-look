"""Cross-resource reference checks for 409 conflict semantics.

Each function answers whether a resource is referenced by nonterminal
sessions or other configuration. Stubs return empty results until the
corresponding store tables land in later steps.
"""

from __future__ import annotations

from .store import Store


def nonterminal_sessions_referencing(store: Store, kind: str, resource_id: str) -> int:
    """Count of nonterminal sessions referencing the resource.

    kind: 'engine' | 'model' | 'source' | 'media'. Sessions land in P6.
    """
    return 0


def profiles_referencing_model(store: Store, model_id: str) -> int:
    """Profiles land in Step 4; wired there."""
    return 0


def media_dependencies(store: Store, model_id: str) -> int:
    """Media-backed source dependencies land with media sources."""
    return 0
