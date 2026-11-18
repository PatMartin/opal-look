"""Outbound source policy and bounded source reads.

Sources the service dereferences — predict image paths/URIs and stream
locators — are checked against configured policy before any read or
decode (contract: "validate target network and redirects"):

- local paths must resolve under ``source_local_roots`` (empty = no local
  file sources permitted),
- network destinations must be public, or explicitly permitted via
  ``source_allowed_hosts`` (name, name:port, IP, or CIDR entries) or
  ``source_allow_private`` (RFC1918/ULA/loopback). Link-local, multicast,
  unspecified, and reserved ranges are denied unless the address itself
  is allowlisted,
- unresolvable DNS names are permitted to admission — the class of an
  address cannot be proven — and fail naturally at connect time,
- HTTP(S) redirects are followed hop by hop and each target is
  re-checked (RTSP protocol redirects happen inside the decoder and are
  not interceptable),
- reads are bounded as bytes arrive and image dimensions are checked
  after header parse, before full decode.

Error responses never echo the source, its credentials, or resolved
addresses; denials are logged without sensitive detail.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

from .errors import ApiError
from .settings import ServiceSettings

_log = logging.getLogger(__name__)

_FETCH_TIMEOUT = 10.0
_MAX_REDIRECTS = 3
_CHUNK = 64 * 1024

HTTP_SCHEMES = ("http", "https")
RTSP_SCHEMES = ("rtsp", "rtsps")
_DEFAULT_PORT = {"http": 80, "https": 443, "rtsp": 554, "rtsps": 322}

_Network = (ipaddress.IPv4Network, ipaddress.IPv6Network)


def _deny(kind: str) -> ApiError:
    return ApiError(422, f"{kind} source is not permitted by the service "
                       "source policy.")


def _too_large(max_bytes: int) -> ApiError:
    return ApiError(413, f"Image exceeds max_upload_bytes ({max_bytes}).")


def _parse_host_entry(entry: str) -> Any:
    """Allowlist entry -> ip_network | (lowercase-name, port|None)."""
    e = entry.strip()
    if not e:
        return None
    try:
        return ipaddress.ip_network(e, strict=False)
    except ValueError:
        pass
    host, port = e.lower(), None
    if e.startswith("[") and "]:" in e:
        h, _, raw = e.rpartition(":")
        if raw.isdigit():
            host, port = h[1:-1].lower(), int(raw)
    elif e.count(":") == 1:
        h, _, raw = e.partition(":")
        if h and raw.isdigit():
            host, port = h.lower(), int(raw)
    return (host, port)


class SourcePolicy:
    """Parsed view of the source-* settings; rebuilt per request."""

    def __init__(self, local_roots: tuple[Path, ...],
                 allowed: tuple[Any, ...], allow_private: bool) -> None:
        self._roots = local_roots
        self._nets = tuple(e for e in allowed if isinstance(e, _Network))
        self._names = tuple(e for e in allowed
                            if not isinstance(e, _Network))
        self._allow_private = allow_private

    @classmethod
    def from_settings(cls, settings: ServiceSettings) -> "SourcePolicy":
        roots: list[Path] = []
        for raw in settings.source_local_roots:
            try:
                roots.append(Path(raw).expanduser().resolve())
            except OSError:
                _log.warning("ignoring unresolvable source_local_roots entry")
        allowed = [e for e in
                   (_parse_host_entry(v) for v in settings.source_allowed_hosts)
                   if e is not None]
        return cls(tuple(roots), tuple(allowed),
                   bool(settings.source_allow_private))

    # -- local files -----------------------------------------------------

    def local_path(self, source: str) -> Path:
        """Resolved path under a configured root, else a sanitized 422."""
        try:
            path = Path(source).expanduser().resolve()
        except (OSError, RuntimeError):
            raise _deny("Local image")
        for root in self._roots:
            try:
                if path.is_relative_to(root):
                    return path
            except OSError:
                continue
        _log.info("source policy: local image source denied")
        raise _deny("Local image")

    # -- network destinations ---------------------------------------------

    def check_network(self, url: str, schemes: tuple[str, ...],
                      kind: str) -> None:
        """Validate a remote destination; raises a sanitized 422 on denial."""
        try:
            parts = urlsplit(url)
            host = parts.hostname
        except ValueError:
            host = None
        if host is None or parts.scheme.lower() not in schemes:
            _log.info("source policy: %s source denied (malformed/scheme)",
                      kind.lower())
            raise _deny(kind)
        host = host.split("%", 1)[0].rstrip(".").lower()
        port = parts.port or _DEFAULT_PORT.get(parts.scheme.lower())
        if self._name_allowed(host, port):
            return
        ips = self._resolve(host)
        if not ips:
            # Unresolvable: the address class cannot be proven; the
            # downstream connect fails on its own.
            return
        if all(self._ip_allowed(ip) for ip in ips):
            return
        _log.info("source policy: %s source denied (address class)",
                  kind.lower())
        raise _deny(kind)

    def _name_allowed(self, host: str, port: int | None) -> bool:
        return any(host == name and (p is None or p == port)
                   for name, p in self._names)

    def _ip_allowed(self, ip: Any) -> bool:
        if any(ip in net for net in self._nets):
            return True
        if (ip.is_link_local or ip.is_multicast or ip.is_unspecified
                or ip.is_reserved):
            return False
        if ip.is_loopback or ip.is_private:
            return self._allow_private
        return True

    @staticmethod
    def _resolve(host: str) -> set:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except OSError:
            return set()
        out = set()
        for info in infos:
            try:
                out.add(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        return out


# -- bounded reads ---------------------------------------------------------


def read_local(path: Path, max_bytes: int) -> bytes:
    """Bounded local read: stat cap first, then a capped read."""
    try:
        if not path.is_file():
            raise ApiError(422, "Image source not found.")
        if path.stat().st_size > max_bytes:
            raise _too_large(max_bytes)
        with path.open("rb") as fh:
            data = fh.read(max_bytes + 1)
    except ApiError:
        raise
    except OSError:
        raise ApiError(422, "Image source could not be read.")
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def fetch_http(policy: SourcePolicy, url: str, max_bytes: int) -> bytes:
    """Bounded HTTP(S) fetch with per-hop redirect policy checks."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        policy.check_network(current, HTTP_SCHEMES, "Image")
        try:
            with httpx.stream("GET", current, timeout=_FETCH_TIMEOUT,
                              follow_redirects=False) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise ApiError(422, "Image source could not be "
                                            "fetched.")
                    current = urljoin(current, location)
                    continue
                if resp.status_code != 200:
                    raise ApiError(422, f"Image source returned HTTP "
                                        f"{resp.status_code}.")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() \
                        and int(declared) > max_bytes:
                    raise _too_large(max_bytes)
                parts: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes(_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise _too_large(max_bytes)
                    parts.append(chunk)
                return b"".join(parts)
        except ApiError:
            raise
        except httpx.HTTPError:
            raise ApiError(422, "Image source could not be fetched.")
    raise ApiError(422, "Image source redirected too many times.")


def decode_image(data: bytes, max_pixels: int):
    """Header-parse -> pixel bound -> full decode."""
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
    except Exception:
        raise ApiError(422, "Source is not a decodable image.")
    if width * height > max_pixels:
        raise ApiError(413, f"Image exceeds max_image_pixels ({max_pixels}).")
    try:
        img.load()
    except Exception:
        raise ApiError(422, "Source is not a decodable image.")
    return img
