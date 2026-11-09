"""Offline contract audit: pinned openapi/opal_look_v1.6.0.yaml (+ shared kernel) vs implemented routes.

Reads the pinned YAML contract and the live FastAPI application, then reports:

* contract inventory (paths, operations, operationIds, x-opal-cli bindings)
* contract operations with no implemented route (missing)
* implemented ``/api/v1`` operations absent from the contract (legacy-only)
* implemented surface outside ``/api/v1`` (service surface; informational)
* structural problems (dangling local ``$ref``s, missing operationId or
  x-opal-cli metadata, wrong OpenAPI version)

Default mode is a nonblocking progress report (exit 0 even with gaps).
``--strict`` exits 1 when any contract operation is missing, any legacy-only
route remains on ``/api/v1``, or the contract itself has structural problems.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)
API_PREFIX = "/api/v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "openapi" / "opal_look_v1.6.0.yaml"


@dataclass(frozen=True)
class ContractOperation:
    method: str
    path: str
    operation_id: str | None
    summary: str
    cli_group: str | None
    cli_command: str | None


@dataclass
class ContractInventory:
    path: Path
    sha256: str
    openapi: str
    api_version: str
    operations: list[ContractOperation]
    problems: list[str] = field(default_factory=list)

    @property
    def path_count(self) -> int:
        return len({op.path for op in self.operations})

    @property
    def operation_count(self) -> int:
        return len(self.operations)


def _walk_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _walk_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_refs(item)


def _resolve_pointer(doc: Any, pointer: str) -> bool:
    """True when a local '/a/b' JSON pointer resolves inside the document."""
    target = doc
    for raw in pointer.split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and token in target:
            target = target[token]
        elif isinstance(target, list) and token.isdigit() and int(token) < len(target):
            target = target[int(token)]
        else:
            return False
    return True


def _doc_at(docs: dict[Path, Any], path: Path) -> Any:
    """Load (and cache) a YAML doc; None when unreadable/not a mapping."""
    resolved = path.resolve()
    if resolved not in docs:
        try:
            docs[resolved] = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        except OSError:
            docs[resolved] = None
    return docs[resolved]


def _split_ref(ref: str) -> tuple[str | None, str]:
    """'./shared/k.yaml#/a/b' -> ('./shared/k.yaml', '/a/b'); '#/a' -> (None, '/a')."""
    file_part, _, frag = ref.partition("#")
    return (file_part or None), frag


def _ref_target(docs: dict[Path, Any], base_dir: Path, owner: Any, ref: str) -> Any:
    """Return the document a $ref points into, or None."""
    file_part, _ = _split_ref(ref)
    if file_part is None:
        return owner
    return _doc_at(docs, base_dir / file_part)


def _ref_resolves(docs: dict[Path, Any], base_dir: Path, owner: Any, ref: str) -> bool:
    file_part, frag = _split_ref(ref)
    target = _ref_target(docs, base_dir, owner, ref) if file_part else owner
    if not isinstance(target, dict):
        return False
    return _resolve_pointer(target, frag)


def _deref_path_item(docs: dict[Path, Any], base_dir: Path, owner: Any,
                     item: dict) -> dict | None:
    """Resolve a path-level '$ref' (e.g. kernel pathItems) to the target mapping."""
    ref = item.get("$ref")
    if not isinstance(ref, str):
        return item
    file_part, frag = _split_ref(ref)
    target_doc = _ref_target(docs, base_dir, owner, ref)
    if not isinstance(target_doc, dict):
        return None
    node: Any = target_doc
    for raw in frag.split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return None
    return node if isinstance(node, dict) else None


def load_contract(path: Path) -> ContractInventory:
    raw = path.read_bytes()
    doc = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: top-level YAML document is not a mapping")
    base_dir = path.parent
    docs: dict[Path, Any] = {path.resolve(): doc}

    operations: list[ContractOperation] = []
    problems: list[str] = []

    openapi = str(doc.get("openapi", ""))
    if not openapi.startswith("3.1"):
        problems.append(f"openapi version {openapi!r} is not 3.1.x")

    for api_path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            problems.append(f"path {api_path}: item is not a mapping")
            continue
        # Path-level "$ref" pulls a pathItem from another document (kernel);
        # a sibling "x-opal-cli" map carries per-method group/command.
        resolved = _deref_path_item(docs, base_dir, doc, item)
        cli_by_method = item.get("x-opal-cli") or {}
        if resolved is None:
            problems.append(f"path {api_path}: unresolved $ref {item['$ref']!r}")
            continue
        for method, op in resolved.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(op, dict):
                problems.append(f"{method.upper()} {api_path}: operation is not a mapping")
                continue
            cli = (cli_by_method.get(method) or {}) if isinstance(cli_by_method, dict) else {}
            if not cli:
                cli = op.get("x-opal-cli") or {}
            op_id = op.get("operationId")
            if not op_id:
                problems.append(f"{method.upper()} {api_path}: missing operationId")
            if not cli.get("group") or not cli.get("command"):
                problems.append(
                    f"{method.upper()} {api_path}: missing x-opal-cli group/command"
                )
            operations.append(
                ContractOperation(
                    method=method.upper(),
                    path=api_path,
                    operation_id=op_id,
                    summary=str(op.get("summary", "")),
                    cli_group=cli.get("group"),
                    cli_command=cli.get("command"),
                )
            )

    seen: set[str] = set()
    for op in operations:
        if op.operation_id:
            if op.operation_id in seen:
                problems.append(f"duplicate operationId {op.operation_id!r}")
            seen.add(op.operation_id)

    dangling: set[str] = set()
    for ref in set(_walk_refs(doc)):
        if not _ref_resolves(docs, base_dir, doc, ref):
            dangling.add(ref)
    # Refs inside externally-loaded docs (e.g. the shared kernel) resolve
    # against that document, not the main contract.
    for doc_path, ext_doc in list(docs.items()):
        if doc_path == path.resolve() or not isinstance(ext_doc, dict):
            continue
        for ref in set(_walk_refs(ext_doc)):
            if not _ref_resolves(docs, doc_path.parent, ext_doc, ref):
                dangling.add(f"{doc_path.name}: {ref}")
    for ref in sorted(dangling):
        problems.append(f"dangling $ref {ref!r}")

    return ContractInventory(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        openapi=openapi,
        api_version=str((doc.get("info") or {}).get("version", "")),
        operations=operations,
        problems=problems,
    )


def _iter_route_operations(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield (method, path) for every leaf route, across FastAPI versions.

    FastAPI >=0.16x wraps included routers in _IncludedRouter objects whose
    ``original_router.routes`` hold the APIRoute leaves; older versions expose
    APIRoute entries directly on ``app.routes``.
    """
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                yield method, prefix + route.path
            continue
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _iter_route_operations(inner.routes, prefix)
            continue
        sub = getattr(route, "routes", None)
        if sub:
            yield from _iter_route_operations(sub, prefix)


def implemented_operations(app: Any) -> list[tuple[str, str]]:
    return sorted(set(_iter_route_operations(app.routes)), key=lambda t: (t[1], t[0]))


@dataclass
class AuditReport:
    contract: ContractInventory
    implemented: list[tuple[str, str]]
    covered: list[ContractOperation]
    missing: list[ContractOperation]
    legacy_only: list[tuple[str, str]]
    service_surface: list[tuple[str, str]]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.legacy_only or self.contract.problems)


def audit(app: Any, contract_path: Path = DEFAULT_CONTRACT) -> AuditReport:
    contract = load_contract(contract_path)
    impl = implemented_operations(app)
    impl_set = set(impl)
    contract_set = {(op.method, op.path) for op in contract.operations}

    covered = [op for op in contract.operations if (op.method, op.path) in impl_set]
    missing = [op for op in contract.operations if (op.method, op.path) not in impl_set]
    extra = [pair for pair in impl if pair not in contract_set]
    legacy_only = [pair for pair in extra if pair[1].startswith(API_PREFIX + "/")
                   or pair[1] == API_PREFIX]
    service_surface = [pair for pair in extra if pair not in legacy_only]

    return AuditReport(
        contract=contract,
        implemented=impl,
        covered=covered,
        missing=missing,
        legacy_only=legacy_only,
        service_surface=service_surface,
    )


def report_dict(report: AuditReport) -> dict[str, Any]:
    c = report.contract
    return {
        "contract": {
            "file": str(c.path),
            "sha256": c.sha256,
            "openapi": c.openapi,
            "api_version": c.api_version,
            "paths": c.path_count,
            "operations": c.operation_count,
        },
        "coverage": {
            "implemented": len(report.covered),
            "missing": len(report.missing),
            "total": c.operation_count,
        },
        "missing": [
            {"method": op.method, "path": op.path, "operation_id": op.operation_id}
            for op in report.missing
        ],
        "legacy_only": [
            {"method": m, "path": p} for m, p in report.legacy_only
        ],
        "service_surface": [
            {"method": m, "path": p} for m, p in report.service_surface
        ],
        "implemented_operations": len(report.implemented),
        "contract_problems": report.contract.problems,
        "ok": report.ok,
    }


def format_text(report: AuditReport) -> str:
    c = report.contract
    cov = report_dict(report)["coverage"]
    lines = [
        "OPAL Look contract audit",
        f"contract: {c.path.name} (openapi {c.openapi}, api {c.api_version}, "
        f"sha256 {c.sha256[:12]}...)",
        f"inventory: {c.path_count} paths / {c.operation_count} operations",
        f"implemented routes (all methods): {len(report.implemented)}",
        f"coverage: {cov['implemented']}/{cov['total']} contract operations "
        f"implemented; {cov['missing']} missing",
        "",
    ]
    if report.missing:
        lines.append(f"MISSING ({len(report.missing)}) -- contract ops without a route:")
        for op in report.missing:
            lines.append(f"  {op.method:6} {op.path}  [{op.operation_id}]")
        lines.append("")
    if report.legacy_only:
        lines.append(
            f"LEGACY-ONLY ({len(report.legacy_only)}) -- implemented /api/v1 ops "
            "absent from v1.6.0:"
        )
        for m, p in report.legacy_only:
            lines.append(f"  {m:6} {p}")
        lines.append("")
    if report.service_surface:
        lines.append(
            f"SERVICE SURFACE ({len(report.service_surface)}) -- outside the "
            "/api/v1 contract prefix (informational):"
        )
        for m, p in report.service_surface:
            lines.append(f"  {m:6} {p}")
        lines.append("")
    if c.problems:
        lines.append(f"CONTRACT PROBLEMS ({len(c.problems)}):")
        for p in c.problems:
            lines.append(f"  {p}")
        lines.append("")
    else:
        lines.append("contract structure: ok (3.1.x, unique operationIds, "
                     "x-opal-cli complete, all local $refs resolve)")
        lines.append("")
    lines.append("RESULT: " + ("CONFORMANT" if report.ok else "GAPS PRESENT"))
    return "\n".join(lines)


def _build_app(data_dir: Path | None) -> Any:
    from .app import create_app

    return create_app(data_dir=data_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opal-look-audit",
        description="Audit implemented routes against the pinned v1.6.0 contract.",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT,
                        help="pinned OpenAPI YAML (default: openapi/opal_look_v1.6.0.yaml)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on missing/legacy routes or contract problems")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="data dir for app construction (default: a temp dir)")
    args = parser.parse_args(argv)

    if not args.contract.is_file():
        print(f"contract file not found: {args.contract}", file=sys.stderr)
        return 2
    try:
        if args.data_dir is not None:
            app = _build_app(args.data_dir)
            try:
                report = audit(app, args.contract)
            finally:
                app.state.store.close()
        else:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                app = _build_app(Path(tmp))
                try:
                    report = audit(app, args.contract)
                finally:
                    app.state.store.close()
    except Exception as exc:  # noqa: BLE001 - surface as exit 2, not a crash dump
        print(f"audit error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report_dict(report), indent=2) if args.as_json
          else format_text(report))
    return 0 if (report.ok or not args.strict) else 1


if __name__ == "__main__":
    raise SystemExit(main())
