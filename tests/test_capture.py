import time

import pytest
from PIL import Image

from opal_look.capture import (
    CAPTURE_REGISTRY,
    CaptureRegistry,
    CredentialUnavailable,
    LiveFramePump,
    StreamEnded,
    capture_adapter_for,
    credential_env_name,
    credentialed_locator,
    resolve_credentials,
)


class _StubAdapter:
    source_type = "rtsp"

    def installed(self):
        return True, None


def test_registry_register_and_lookup():
    reg = CaptureRegistry()
    adapter = _StubAdapter()
    reg.register(adapter)
    assert reg.for_type("rtsp") is adapter
    assert reg.for_type("camera") is None
    assert adapter in reg.all()


def test_capture_adapter_for_uses_global_registry():
    assert capture_adapter_for("camera") is CAPTURE_REGISTRY.for_type("camera")


def test_credential_env_name_sanitized():
    assert credential_env_name("driveway-camera") == "OPAL_LOOK_CRED_DRIVEWAY_CAMERA"
    assert credential_env_name("cam.1@yard") == "OPAL_LOOK_CRED_CAM_1_YARD"


def test_resolve_credentials_none_when_no_ref():
    assert resolve_credentials(None) is None


def test_resolve_credentials_missing_env(monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_CRED_CAM1", raising=False)
    with pytest.raises(CredentialUnavailable):
        resolve_credentials("cam1")


def test_resolve_credentials_malformed(monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_CAM1", "no-colon-here")
    with pytest.raises(CredentialUnavailable):
        resolve_credentials("cam1")


def test_resolve_credentials_splits_first_colon(monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_CAM1", "alice:p:a:ss")
    assert resolve_credentials("cam1") == ("alice", "p:a:ss")


def test_credentialed_locator_injects_userinfo(monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_CAM1", "al ice:s@cret")
    url = credentialed_locator("rtsp://192.0.2.1:554/feed?x=1", "cam1")
    assert url == "rtsp://al%20ice:s%40cret@192.0.2.1:554/feed?x=1"


def test_credentialed_locator_no_ref_passthrough():
    assert credentialed_locator("rtsp://h/x", None) == "rtsp://h/x"


def test_credentialed_locator_ipv6(monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_C", "u:p")
    url = credentialed_locator("rtsp://[::1]:554/x", "c")
    assert url == "rtsp://u:p@[::1]:554/x"


class _ScriptedStream:
    def __init__(self, items, block_when_empty=False):
        import threading

        self._items = list(items)
        self._block = block_when_empty
        self._released = threading.Event()
        self.closed = False

    def read(self):
        if not self._items:
            if self._block:
                self._released.wait()
            raise StreamEnded("eof")
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True
        self._released.set()


def _frame():
    return Image.new("RGB", (4, 4))


def test_pump_delivers_frames():
    f1 = _frame()
    pump = LiveFramePump(_ScriptedStream([f1], block_when_empty=True)).start()
    assert pump.get(timeout=2) is f1
    pump.close()
    with pytest.raises(StreamEnded):
        pump.get(timeout=2)


def test_pump_drops_oldest_and_counts():
    frames = [_frame() for _ in range(3)]
    pump = LiveFramePump(
        _ScriptedStream(frames, block_when_empty=True), capacity=1).start()
    deadline = time.monotonic() + 2
    while pump.dropped < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pump.get(timeout=1) is frames[-1]
    assert pump.dropped == 2
    pump.close()


def test_pump_raises_terminal_error():
    pump = LiveFramePump(_ScriptedStream([StreamEnded("gone")])).start()
    with pytest.raises(StreamEnded):
        pump.get(timeout=2)
