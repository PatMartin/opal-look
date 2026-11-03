"""If-Match/ETag precondition matrix, revision atomicity, and txn nesting.

Covers the v1.5 shared semantics: missing -> 428, malformed -> 422,
stale -> 412, '*' allowed; config writes bump the global revision inside
an atomic transaction while runtime activity must not move it.
"""

from __future__ import annotations

import threading

import pytest

from opal_look.errors import ApiError
from opal_look.precondition import check_if_match, require_if_match
from opal_look.store import Store


class _Req:
    """Minimal request stub exposing .headers.get for precondition helpers."""

    def __init__(self, headers):
        self.headers = headers


def _etag(client):
    return client.get("/api/v1/settings/").headers["etag"]


def test_missing_if_match_is_428(client):
    resp = client.patch("/api/v1/settings/", json={"max_upload_bytes": 1})
    assert resp.status_code == 428
    assert resp.json()["error"]["code"] == "precondition_required"


@pytest.mark.parametrize("value", [
    'W/"abc"',           # weak entity-tag rejected
    '"a", "b"',          # lists rejected
    "unquoted",          # bare token rejected
    '"',                 # unterminated
])
def test_malformed_if_match_is_422(client, value):
    resp = client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 1},
        headers={"If-Match": value},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


def test_stale_if_match_is_412(client):
    old = _etag(client)
    client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 5},
        headers={"If-Match": "*"},
    )
    resp = client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 6},
        headers={"If-Match": old},
    )
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "precondition_failed"


def test_star_and_matching_etag_accepted(client):
    before = _etag(client)
    resp = client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 7},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    current = resp.headers["etag"]
    assert current != before

    resp2 = client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 8},
        headers={"If-Match": current},
    )
    assert resp2.status_code == 200
    assert resp2.headers["etag"] != current


def test_check_if_match_inside_txn_semantics(tmp_path):
    store = Store(tmp_path / "data")
    try:
        revision = store.config_revision()
        with store.write_txn():
            check_if_match(_Req({"if-match": revision}), store)
            store.meta.set("k", "v")
            store.bump_revision()
        with pytest.raises(ApiError) as exc:
            with store.write_txn():
                check_if_match(_Req({"if-match": revision}), store)
        assert exc.value.status_code == 412
        with store.write_txn():
            check_if_match(_Req({"if-match": "*"}), store)  # always allowed
    finally:
        store.close()


def test_concurrent_writers_single_winner(tmp_path):
    """Two writers racing on one ETag: exactly one commits, loser sees 412."""
    store = Store(tmp_path / "data")
    try:
        revision = store.config_revision()
        barrier = threading.Barrier(2)
        outcomes = []

        def writer(name):
            barrier.wait()
            try:
                with store.write_txn():
                    check_if_match(_Req({"if-match": revision}), store)
                    store.meta.set("winner", name)
                    store.bump_revision()
                outcomes.append(("committed", name))
            except ApiError as exc:
                outcomes.append(("rejected", exc.status_code))

        threads = [threading.Thread(target=writer, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        committed = [o for o in outcomes if o[0] == "committed"]
        rejected = [o for o in outcomes if o[0] == "rejected"]
        assert len(committed) == 1
        assert rejected == [("rejected", 412)]
        assert store.meta.get("winner") == committed[0][1]
    finally:
        store.close()


def test_nested_write_txn_commit(tmp_path):
    store = Store(tmp_path / "data")
    try:
        with store.write_txn():
            store.meta.set("outer", "1")
            with store.write_txn():
                store.meta.set("inner", "2")
        assert store.meta.get("outer") == "1"
        assert store.meta.get("inner") == "2"
    finally:
        store.close()


def test_inner_failure_rolls_back_only_inner_writes(tmp_path):
    store = Store(tmp_path / "data")
    try:
        with store.write_txn():
            store.meta.set("outer", "1")
            with pytest.raises(RuntimeError):
                with store.write_txn():
                    store.meta.set("inner", "2")
                    raise RuntimeError("inner boom")
        assert store.meta.get("outer") == "1"
        assert store.meta.get("inner") is None
    finally:
        store.close()


def test_outer_failure_rolls_back_everything(tmp_path):
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(RuntimeError):
            with store.write_txn():
                store.meta.set("outer", "1")
                with store.write_txn():
                    store.meta.set("inner", "2")
                raise RuntimeError("outer boom")
        assert store.meta.get("outer") is None
        assert store.meta.get("inner") is None
    finally:
        store.close()


def test_import_with_stale_etag_fails_atomically(client):
    payload = client.get("/api/v1/backup/export").json()
    stale = _etag(client)
    client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 555},
        headers={"If-Match": "*"},
    )
    resp = client.post(
        "/api/v1/backup/import", json=payload, headers={"If-Match": stale}
    )
    assert resp.status_code == 412
    # No partial import occurred.
    assert client.get("/api/v1/settings/max_upload_bytes").json()["value"] == 555


def test_import_advances_revision(client):
    payload = client.get("/api/v1/backup/export").json()
    before = _etag(client)
    resp = client.post(
        "/api/v1/backup/import", json=payload, headers={"If-Match": "*"}
    )
    assert resp.status_code == 200
    assert resp.headers["etag"] != before
    assert resp.headers["etag"] == _etag(client)


def test_runtime_activity_does_not_bump_revision(client, tmp_path):
    import io

    from PIL import Image

    etag = _etag(client)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
    resp = client.post(
        "/api/v1/media/", files={"file": ("x.jpg", buf.getvalue(), "image/jpeg")}
    )
    assert resp.status_code == 201
    media_id = resp.json()["media_id"]
    assert _etag(client) == etag, "media upload must not move config ETag"
    assert client.delete(f"/api/v1/media/{media_id}").status_code == 204
    assert _etag(client) == etag, "media delete must not move config ETag"


def test_require_if_match_unit():
    assert require_if_match(_Req({"if-match": "*"})) == "*"
    assert require_if_match(_Req({"if-match": ' "abc" '})) == '"abc"'
    with pytest.raises(ApiError) as exc:
        require_if_match(_Req({}))
    assert exc.value.status_code == 428
    with pytest.raises(ApiError) as exc:
        require_if_match(_Req({"if-match": "weak"}))
    assert exc.value.status_code == 422


def test_idempotency_key_bounds():
    from opal_look.idempotency import request_idempotency_key

    assert request_idempotency_key(_Req({})) is None
    # Contract bounds are length-only: any 1..128-char value is accepted.
    assert request_idempotency_key(_Req({"Idempotency-Key": "k=+~./abc"})) == "k=+~./abc"
    assert request_idempotency_key(_Req({"Idempotency-Key": "x" * 128})) == "x" * 128
    with pytest.raises(ApiError) as exc:
        request_idempotency_key(_Req({"Idempotency-Key": "x" * 129}))
    assert exc.value.status_code == 422
    with pytest.raises(ApiError) as exc:
        request_idempotency_key(_Req({"Idempotency-Key": ""}))
    assert exc.value.status_code == 422

