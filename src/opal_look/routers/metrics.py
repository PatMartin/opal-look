"""v1.5 operational surfaces: GET /metrics/ and GET /events/status."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..dependencies import StoreDep
from ..settings import effective_settings

router = APIRouter()


@router.get("/api/v1/metrics/")
def get_api_v1_metrics(request: Request, store: StoreDep) -> dict:
    """Counters + gauges (flat numeric maps, no cardinality labels)."""
    stats = (request.app.state.event_publisher.stats()
             if getattr(request.app.state, "event_publisher", None)
             else {"published": 0, "dropped": 0, "rate_limited": 0,
                   "queue_depth": 0})
    monitors_running = sum(
        1 for rt in getattr(request.app.state, "monitor_runtimes", {}).values()
        if rt.alive)
    recordings_active = store.recordings.count_active()
    jobs_nonterminal = store.jobs.count_nonterminal()
    sessions_active = store.sessions.count_nonterminal() \
        if hasattr(store.sessions, "count_nonterminal") else 0
    viewers_active = sum(getattr(request.app.state, "viewer_counts", {}).values())
    obs_total = store.observations.count() if hasattr(
        store.observations, "count") else 0
    # upstream Metrics: flat counters/gauges
    processed = dropped = reconnects = 0
    try:
        for r in store._conn.execute(
                "SELECT frames_analyzed, frames_dropped, tracking_epoch "
                "FROM sessions"):
            processed += r["frames_analyzed"]
            dropped += r["frames_dropped"]
            reconnects += r["tracking_epoch"]
    except Exception:
        pass
    active_streams = monitors_running + sessions_active
    return {
        "captured_frames": processed + dropped,
        "processed_frames": processed,
        "dropped_frames": dropped,
        "observations_total": obs_total,
        "event_publish_drops": int(stats.get("dropped", 0)
                                   + stats.get("rate_limited", 0)),
        "active_sessions": sessions_active,
        "queued_jobs": store.jobs.count_queued()
            if hasattr(store.jobs, "count_queued") else jobs_nonterminal,
        "mean_inference_ms": 0.0,
        "inference_skipped_frames": 0,
        "active_source_streams": active_streams,
        "mean_processing_ms": 0.0,
        "source_reconnections": reconnects,
    }


@router.get("/api/v1/events/status")
def get_api_v1_events_status(request: Request, store: StoreDep) -> dict:
    """Publisher status: enabled, allowlisted topics, capacity, drops,
    transport string."""
    app_settings = effective_settings(store)
    publisher = getattr(request.app.state, "event_publisher", None)
    stats = publisher.stats() if publisher else {
        "published": 0, "dropped": 0, "rate_limited": 0, "queue_depth": 0}
    enabled = bool(getattr(app_settings, "events_enabled", False))
    transport = getattr(request.app.state, "event_transport", None)
    return {
        "enabled": enabled,
        "topics": list(getattr(app_settings, "event_topics_allowlist", []) or []),
        "queue_capacity": int(getattr(app_settings, "event_queue_capacity", 0)
                              or 0),
        "drops": int(stats.get("dropped", 0) + stats.get("rate_limited", 0)),
        "transport_status": (
            "provisioned" if enabled and transport
            else "unprovisioned" if enabled
            else "disabled"),
    }
