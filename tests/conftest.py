import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opal_look.app import create_app
from opal_look.capture import (
    CAPTURE_REGISTRY,
    CaptureError,
    StreamEnded,
)


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


class _FakeStream:
    """Scripted FrameStream: serves `count` frames (None = infinite), then
    raises `error` (default StreamEnded)."""

    def __init__(self, count, size, delay, error):
        self._remaining = count
        self._size = size
        self._delay = delay
        self._error = error
        self.closed = False

    def read(self):
        if self.closed:
            raise StreamEnded("closed")
        if self._delay:
            time.sleep(self._delay)
        if self._remaining is not None:
            if self._remaining <= 0:
                raise self._error or StreamEnded("ended")
            self._remaining -= 1
        return Image.new("RGB", self._size, (3, 5, 7))

    def close(self):
        self.closed = True


class FakeCaptureAdapter:
    """Deterministic RTSP-adapter stand-in; no network access."""

    source_type = "rtsp"

    def __init__(self):
        self.probe_result = {
            "available": True,
            "message": None,
            "width": 320,
            "height": 240,
            "fps": 15.0,
            "duration_ms": None,
        }
        self.open_calls = []          # credentialed locators, per open_stream
        self.probe_calls = []
        self.grab_calls = []
        self.open_error = None        # always raised by open_stream
        self.fail_on_open = 0         # first N opens raise CaptureError
        self.frames_per_open = []     # script of frame counts per open (None = infinite)
        self.frame_size = (16, 12)
        self.frame_delay = 0.0
        self.stream_error = None      # raised by read() once frames exhausted
        self.grab_image = Image.new("RGB", (16, 16), (7, 7, 7))
        self.grab_error = None

    def installed(self):
        return True, None

    def probe_stream(self, locator, options, credentialed_locator):
        self.probe_calls.append(credentialed_locator)
        return dict(self.probe_result)

    def open_stream(self, locator, options, credentialed_locator):
        self.open_calls.append(credentialed_locator)
        if len(self.open_calls) <= self.fail_on_open:
            raise CaptureError("connect refused")
        if self.open_error:
            raise self.open_error
        if self.frames_per_open:
            idx = min(len(self.open_calls) - 1 - self.fail_on_open,
                      len(self.frames_per_open) - 1)
            count = self.frames_per_open[idx]
        else:
            count = 3
        return _FakeStream(count, self.frame_size, self.frame_delay, self.stream_error)

    def grab(self, locator, options, credentialed_locator):
        self.grab_calls.append(credentialed_locator)
        if self.grab_error:
            raise self.grab_error
        return self.grab_image


@pytest.fixture()
def fake_rtsp(monkeypatch):
    fake = FakeCaptureAdapter()
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", fake)
    return fake
