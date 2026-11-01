"""UTC timestamp helpers; canonical RFC3339 'Z' form for stored values."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utcnow())


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def expired(expires_at: str) -> bool:
    return parse_iso(expires_at) <= utcnow()


def plus_hours(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)
