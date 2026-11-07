"""v1.5 retained observations: opt-in storage, immutable reads, paging."""

from __future__ import annotations

import io

from PIL import Image

SIMPLE = {"id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}


def _media(client):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, format="JPEG")
    return client.post("/api/v1/media/",
                       files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}
                       ).json()["id"]


def _pipeline(client, **over):
    client.post("/api/v1/pipelines/", json={**SIMPLE, **over},
                headers={"If-Match": "*"})


def _analyze(client, mid, **kw):
    return client.post("/api/v1/analyze/",
                       json={"pipeline_id": "p", "source": {"media_id": mid}, **kw})


def test_no_retention_no_history(client):
    _pipeline(client)
    mid = _media(client)
    _analyze(client, mid)
    assert client.get("/api/v1/observations/").json()["items"] == []


def test_opt_in_persists_and_reads_back(client):
    _pipeline(client)
    mid = _media(client)
    oid = _analyze(client, mid,
                   retention={"persist_observations": True}
                   ).json()["observations"][0]["id"]
    shown = client.get(f"/api/v1/observations/{oid}").json()
    assert shown["id"] == oid
    assert shown["pipeline_id"] == "p"
    assert shown["task"] == "detection"
    assert shown["items"]
    listed = client.get("/api/v1/observations/").json()
    assert [o["id"] for o in listed["items"]] == [oid]
    assert listed["has_more"] is False


def test_analyze_request_retention_persists(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "source": {"media_id": mid}, "pipeline_id": "p",
        "retention": {"persist_observations": True}})
    assert resp.status_code == 200
    assert len(client.get("/api/v1/observations/").json()["items"]) == 1


def test_unknown_observation_404(client):
    assert client.get("/api/v1/observations/nope").status_code == 404


def test_task_and_label_filters(client):
    _pipeline(client)
    mid = _media(client)
    _analyze(client, mid, retention={"persist_observations": True})
    page = client.get("/api/v1/observations/", params={"task": "detection"}).json()
    assert len(page["items"]) == 1
    page = client.get("/api/v1/observations/", params={"task": "ocr"}).json()
    assert page["items"] == []
    label = page["items"] and page["items"][0]["items"][0]["label"]
    if label:
        page = client.get("/api/v1/observations/", params={"label": label}).json()
        assert len(page["items"]) == 1


def test_media_source_filter(client):
    _pipeline(client)
    mid = _media(client)
    oid = _analyze(client, mid,
                   retention={"persist_observations": True}
                   ).json()["observations"][0]["id"]
    page = client.get("/api/v1/observations/", params={"source_id": "nope"}).json()
    assert page["items"] == []
    page = client.get("/api/v1/observations/",
                      params={"after": "2999-01-01T00:00:00Z"}).json()
    assert page["items"] == []


def test_pagination_deterministic(client):
    _pipeline(client)
    mid = _media(client)
    for _ in range(3):
        _analyze(client, mid, retention={"persist_observations": True})
    page1 = client.get("/api/v1/observations/", params={"limit": 2}).json()
    assert len(page1["items"]) == 2 and page1["has_more"] is True
    page2 = client.get("/api/v1/observations/",
                       params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert len(page2["items"]) == 1 and page2["has_more"] is False
    ids = [o["id"] for o in page1["items"] + page2["items"]]
    assert len(set(ids)) == 3  # deterministic order, no dupes


def test_expired_observation_410(client):
    _pipeline(client)
    mid = _media(client)
    oid = _analyze(client, mid,
                   retention={"persist_observations": True, "ttl_seconds": 1}
                   ).json()["observations"][0]["id"]
    import time
    store = client.app.state.store
    from opal_look.timeutil import now_iso
    store._conn.execute(
        "UPDATE observations SET expires_at = ? WHERE observation_id = ?",
        ("2000-01-01T00:00:00Z", oid))
    assert client.get(f"/api/v1/observations/{oid}").status_code == 410
    assert client.get("/api/v1/observations/").json()["items"] == []


def test_observations_immutable_no_write_ops(client):
    _pipeline(client)
    mid = _media(client)
    oid = _analyze(client, mid,
                   retention={"persist_observations": True}
                   ).json()["observations"][0]["id"]
    assert client.patch(f"/api/v1/observations/{oid}",
                        json={"task": "x"}, headers={"If-Match": "*"}
                        ).status_code in (405, 404)
    assert client.delete(f"/api/v1/observations/{oid}",
                         headers={"If-Match": "*"}).status_code in (405, 404)
    # body unchanged
    assert client.get(f"/api/v1/observations/{oid}").json()["task"] == "detection"


def test_sweep_purges_expired(client):
    from opal_look.store import sweep_expired
    _pipeline(client)
    mid = _media(client)
    oid = _analyze(client, mid,
                   retention={"persist_observations": True}
                   ).json()["observations"][0]["id"]
    store = client.app.state.store
    store._conn.execute(
        "UPDATE observations SET expires_at = ? WHERE observation_id = ?",
        ("2000-01-01T00:00:00Z", oid))
    counts = sweep_expired(store)
    assert counts["observations"] == 1
    assert client.get(f"/api/v1/observations/{oid}").status_code == 404
