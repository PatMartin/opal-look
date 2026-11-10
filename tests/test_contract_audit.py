"""Offline audit of the pinned opal_look_v1.7.1.yaml contract vs live routes.

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
CONTRACT = REPO_ROOT / "openapi" / "opal_look_v1.7.1.yaml"
CONTRACT_KERNEL = REPO_ROOT / "openapi" / "shared" / "opal_kernel.yaml"
CONTRACT_1_4 = REPO_ROOT / "vendor" / "opal-api" / "opal_look.yaml"


@pytest.fixture()
def app(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    yield app
    app.state.store.close()


# v1.7.1 migration: these sets tracked the in-flight gaps; both are empty
# now that the REST surface is conformant.
EXPECTED_MISSING: set[tuple[str, str]] = set()
EXPECTED_LEGACY: set[tuple[str, str]] = set()


def test_pinned_contract_exists_and_is_v1_7():
    assert CONTRACT.is_file(), "openapi/opal_look_v1.7.1.yaml is the pinned contract"
    assert CONTRACT_KERNEL.is_file(), "shared opal_kernel.yaml must ship with it"
    assert CONTRACT_1_4.is_file(), "v1.4.0 contract stays as historical reference"
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.openapi == "3.1.0"
    assert inv.api_version == "1.7.1"


def test_contract_inventory_is_complete():
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.path_count == 70
    assert inv.operation_count == 105
    op_ids = [op.operation_id for op in inv.operations]
    assert len(set(op_ids)) == 105
    for op in inv.operations:
        assert op.cli_command, (
            f"{op.method} {op.path} missing x-opal-cli metadata"
        )


def test_contract_has_no_structural_problems():
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.problems == [], "; ".join(inv.problems)


def test_audit_classifies_routes_honestly(app):
    report = contract_audit.audit(app, CONTRACT)
    # Nothing is silently treated as passing: every contract operation is
    # either covered or explicitly listed as missing.
    assert len(report.covered) + len(report.missing) == report.contract.operation_count
    # The simplified-draft surface still implements the shared core.
    assert ("GET", "/api/v1/source/") in {(op.method, op.path) for op in report.covered}
    # All upstream resource families are implemented; only the known
    # v1.7.1 in-flight gaps remain (see EXPECTED_MISSING).
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
    assert rc_strict == expected == 0, (
        "strict must pass now that v1.7.1 is conformant"
    )
    out = capsys.readouterr().out
    assert "CONFORMANT" in out


def test_main_json_output_is_machine_readable(capsys):
    rc = contract_audit.main(["--contract", str(CONTRACT), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract"]["operations"] == 105
    assert payload["contract"]["paths"] == 70
    assert payload["coverage"]["implemented"] + payload["coverage"]["missing"] == 105
    assert payload["ok"] is True


def test_main_missing_contract_returns_2(tmp_path, capsys):
    rc = contract_audit.main(["--contract", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
