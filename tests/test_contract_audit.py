"""Offline audit of the pinned opal_look_v0.5.0.yaml contract vs live routes.

These tests are deterministic: they parse the pinned YAML and enumerate the
FastAPI app's routes — no network, camera, GPU, or broker required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opal_look.app import create_app
from opal_look import contract_audit

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "openapi" / "opal_look_v0.5.0.yaml"
CONTRACT_KERNEL = REPO_ROOT / "openapi" / "shared" / "opal_kernel.yaml"
CONTRACT_1_4 = REPO_ROOT / "vendor" / "opal-api" / "opal_look.yaml"


@pytest.fixture()
def app(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    yield app
    app.state.store.close()


# v0.5.0 contract: the migration gap sets track each step and shrink to
# empty as coverage lands.
EXPECTED_MISSING: set[tuple[str, str]] = set()
EXPECTED_LEGACY: set[tuple[str, str]] = set()


def test_pinned_contract_exists_and_is_v0_5():
    assert CONTRACT.is_file(), "openapi/opal_look_v0.5.0.yaml is the pinned contract"
    assert CONTRACT_KERNEL.is_file(), "shared opal_kernel.yaml must ship with it"
    assert CONTRACT_1_4.is_file(), "v1.4.0 contract stays as historical reference"
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.openapi == "3.1.0"
    assert inv.api_version == "0.5.0"


def test_contract_inventory_is_complete():
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.path_count == 35
    assert inv.operation_count == 45
    op_ids = [op.operation_id for op in inv.operations]
    assert len(set(op_ids)) == 45
    # The 0.5.0 kernel retired x-opal-cli: no operation ships a descriptor.
    for op in inv.operations:
        assert not op.cli_command, (
            f"{op.method} {op.path} carries retired x-opal-cli metadata"
        )


def test_contract_has_no_structural_problems():
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.problems == [], "; ".join(inv.problems)


def test_audit_classifies_routes_honestly(app):
    report = contract_audit.audit(app, CONTRACT)
    # Nothing is silently treated as passing: every contract operation is
    # either covered or explicitly listed as missing.
    assert len(report.covered) + len(report.missing) == report.contract.operation_count
    # The kernel-mounted core already implemented stays covered.
    assert ("GET", "/api/v1/health/") in {(op.method, op.path) for op in report.covered}
    # Only the known MVP in-flight gaps remain (see EXPECTED_MISSING).
    assert {(op.method, op.path) for op in report.missing} == EXPECTED_MISSING
    legacy = set(report.legacy_only)
    assert legacy == EXPECTED_LEGACY
    # Convenience endpoints outside /api/v1 are service surface, not violations.
    service = set(report.service_surface)
    assert ("GET", "/health") in service
    for m, p in legacy:
        assert p.startswith("/api/v1")


def test_report_accounts_for_every_implemented_route(app):
    report = contract_audit.audit(app, CONTRACT)
    impl = set(report.implemented)
    covered = {(op.method, op.path) for op in report.covered}
    classified = covered | set(report.legacy_only) | set(report.service_surface)
    assert impl == classified


def test_main_is_nonblocking_by_default_and_strict_on_gaps(app, capsys):
    report = contract_audit.audit(app, CONTRACT)
    expected = 1 if (report.missing or report.legacy_only
                     or report.contract.problems) else 0
    assert contract_audit.main(["--contract", str(CONTRACT)]) == 0
    rc_strict = contract_audit.main(["--contract", str(CONTRACT), "--strict"])
    assert rc_strict == expected
    out = capsys.readouterr().out
    if expected == 0:
        assert "CONFORMANT" in out


def test_main_json_output_is_machine_readable(capsys):
    rc = contract_audit.main(["--contract", str(CONTRACT), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract"]["operations"] == 45
    assert payload["contract"]["paths"] == 35
    assert payload["coverage"]["implemented"] + payload["coverage"]["missing"] == 45


def test_main_missing_contract_returns_2(tmp_path, capsys):
    rc = contract_audit.main(["--contract", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
