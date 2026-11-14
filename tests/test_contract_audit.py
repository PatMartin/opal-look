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


# MVP replacement contract (still versioned 1.7.1): these sets track the
# in-flight migration gaps and shrink to empty as steps land.
EXPECTED_MISSING: set[tuple[str, str]] = {
    ("GET", "/api/v1/engine/{engine_id}/capabilities"),
    ("GET", "/api/v1/hardware/"),
    ("GET", "/api/v1/hardware/{device_id}"),
    ("GET", "/api/v1/stream/"),
    ("GET", "/api/v1/stream/{stream_id}"),
    ("GET", "/api/v1/stream/{stream_id}/events"),
    ("GET", "/api/v1/stream/{stream_id}/metrics"),
    ("GET", "/api/v1/stream/{stream_id}/snapshot"),
    ("GET", "/api/v1/stream/{stream_id}/video"),
    ("POST", "/api/v1/engine/discover"),
    ("POST", "/api/v1/model/{model_id}/load"),
    ("POST", "/api/v1/model/{model_id}/unload"),
    ("POST", "/api/v1/predict"),
    ("POST", "/api/v1/stream/"),
    ("POST", "/api/v1/stream/{stream_id}/stop"),
}
EXPECTED_LEGACY: set[tuple[str, str]] = {
    ("DELETE", "/api/v1/artifact/{artifact_id}"),
    ("DELETE", "/api/v1/capture/{capture_id}"),
    ("DELETE", "/api/v1/media/{media_id}"),
    ("DELETE", "/api/v1/model/{model_id}"),
    ("DELETE", "/api/v1/monitor/{monitor_id}"),
    ("DELETE", "/api/v1/persona/{persona_id}"),
    ("DELETE", "/api/v1/pipeline/{pipeline_id}"),
    ("DELETE", "/api/v1/rule/{rule_id}"),
    ("DELETE", "/api/v1/source/{source_id}"),
    ("DELETE", "/api/v1/zone/{zone_id}"),
    ("GET", "/api/v1/artifact/"),
    ("GET", "/api/v1/artifact/{artifact_id}"),
    ("GET", "/api/v1/artifact/{artifact_id}/content"),
    ("GET", "/api/v1/capabilities/"),
    ("GET", "/api/v1/capture/"),
    ("GET", "/api/v1/capture/{capture_id}"),
    ("GET", "/api/v1/capture/{capture_id}/content"),
    ("GET", "/api/v1/events/status"),
    ("GET", "/api/v1/job/"),
    ("GET", "/api/v1/job/{job_id}"),
    ("GET", "/api/v1/media/"),
    ("GET", "/api/v1/media/{media_id}"),
    ("GET", "/api/v1/metrics/"),
    ("GET", "/api/v1/monitor/"),
    ("GET", "/api/v1/monitor/{monitor_id}"),
    ("GET", "/api/v1/observation/"),
    ("GET", "/api/v1/observation/{observation_id}"),
    ("GET", "/api/v1/persona/"),
    ("GET", "/api/v1/persona/{persona_id}"),
    ("GET", "/api/v1/pipeline/"),
    ("GET", "/api/v1/pipeline/{pipeline_id}"),
    ("GET", "/api/v1/recording/"),
    ("GET", "/api/v1/recording/{recording_id}"),
    ("GET", "/api/v1/rule/"),
    ("GET", "/api/v1/rule/{rule_id}"),
    ("GET", "/api/v1/session/"),
    ("GET", "/api/v1/session/{session_id}"),
    ("GET", "/api/v1/session/{session_id}/preview"),
    ("GET", "/api/v1/session/{session_id}/stream"),
    ("GET", "/api/v1/source/"),
    ("GET", "/api/v1/source/{source_id}"),
    ("GET", "/api/v1/source/{source_id}/frame"),
    ("GET", "/api/v1/source/{source_id}/status"),
    ("GET", "/api/v1/source/{source_id}/stream"),
    ("GET", "/api/v1/zone/"),
    ("GET", "/api/v1/zone/{zone_id}"),
    ("PATCH", "/api/v1/model/{model_id}"),
    ("PATCH", "/api/v1/monitor/{monitor_id}"),
    ("PATCH", "/api/v1/persona/{persona_id}"),
    ("PATCH", "/api/v1/pipeline/{pipeline_id}"),
    ("PATCH", "/api/v1/rule/{rule_id}"),
    ("PATCH", "/api/v1/source/{source_id}"),
    ("PATCH", "/api/v1/zone/{zone_id}"),
    ("POST", "/api/v1/analyze/"),
    ("POST", "/api/v1/analyze/image"),
    ("POST", "/api/v1/job/"),
    ("POST", "/api/v1/job/{job_id}/cancel"),
    ("POST", "/api/v1/media/"),
    ("POST", "/api/v1/model/"),
    ("POST", "/api/v1/monitor/"),
    ("POST", "/api/v1/persona/"),
    ("POST", "/api/v1/persona/{persona_id}/validate"),
    ("POST", "/api/v1/pipeline/"),
    ("POST", "/api/v1/pipeline/validate"),
    ("POST", "/api/v1/recording/"),
    ("POST", "/api/v1/recording/{recording_id}/stop"),
    ("POST", "/api/v1/rule/"),
    ("POST", "/api/v1/session/"),
    ("POST", "/api/v1/session/{session_id}/stop"),
    ("POST", "/api/v1/source/"),
    ("POST", "/api/v1/source/{source_id}/capture/"),
    ("POST", "/api/v1/source/{source_id}/probe"),
    ("POST", "/api/v1/zone/"),
}


def test_pinned_contract_exists_and_is_v1_7():
    assert CONTRACT.is_file(), "openapi/opal_look_v1.7.1.yaml is the pinned contract"
    assert CONTRACT_KERNEL.is_file(), "shared opal_kernel.yaml must ship with it"
    assert CONTRACT_1_4.is_file(), "v1.4.0 contract stays as historical reference"
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.openapi == "3.1.0"
    assert inv.api_version == "1.7.1"


def test_contract_inventory_is_complete():
    inv = contract_audit.load_contract(CONTRACT)
    assert inv.path_count == 39
    assert inv.operation_count == 47
    op_ids = [op.operation_id for op in inv.operations]
    assert len(set(op_ids)) == 47
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
    assert rc_strict == expected == 1, (
        "strict fails until the MVP migration removes legacy routes and adds the new ops"
    )
    out = capsys.readouterr().out
    assert "GAPS PRESENT" in out


def test_main_json_output_is_machine_readable(capsys):
    rc = contract_audit.main(["--contract", str(CONTRACT), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract"]["operations"] == 47
    assert payload["contract"]["paths"] == 39
    assert payload["coverage"]["implemented"] + payload["coverage"]["missing"] == 47
    assert payload["ok"] is False  # in-flight gaps until migration completes


def test_main_missing_contract_returns_2(tmp_path, capsys):
    rc = contract_audit.main(["--contract", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
