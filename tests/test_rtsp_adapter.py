import types
from fractions import Fraction

import pytest
from PIL import Image

from opal_look import capture_rtsp
from opal_look.capture import CaptureError, StreamEnded, StreamError
from opal_look.capture_rtsp import RtspAvAdapter, _av_options


class _FakeVideoStream:
    width = 640
    height = 480
    average_rate = Fraction(25, 1)


class _FakeFrame:
    def to_image(self):
        return Image.new("RGB", (8, 8), (1, 2, 3))


class _FakeContainer:
    def __init__(self, frames=None, duration=None):
        self.streams = types.SimpleNamespace(video=[_FakeVideoStream()])
        self.duration = duration
        self._frames = frames if frames is not None else [_FakeFrame()]
        self.closed = False

    def decode(self, video=0):
        return iter(self._frames)

    def close(self):
        self.closed = True


class _FakeAv:
    def __init__(self, container=None, error=None):
        self.calls = []
        self._container = container or _FakeContainer()
        self._error = error

    def open(self, url, options=None):
        self.calls.append((url, options))
        if self._error:
            raise self._error
        return self._container


@pytest.fixture()
def adapter():
    return RtspAvAdapter()


def test_installed_with_av(adapter):
    assert adapter.installed() == (True, None)


def test_installed_missing_av(adapter, monkeypatch):
    monkeypatch.setattr(capture_rtsp, "_import_av", lambda: None)
    ok, message = adapter.installed()
    assert ok is False
    assert "PyAV" in message


def test_av_options_mapping():
    opts = _av_options({"transport": "tcp", "timeout_ms": 2000})
    assert opts["rtsp_transport"] == "tcp"
    assert opts["stimeout"] == "2000000"
    assert opts["timeout"] == "2000000"


def test_av_options_defaults():
    opts = _av_options({})
    assert "rtsp_transport" not in opts
    assert opts["stimeout"] == "5000000"


def test_probe_stream_reports_geometry(adapter, monkeypatch):
    fake = _FakeAv(container=_FakeContainer())
    monkeypatch.setattr(capture_rtsp, "_import_av", lambda: fake)
    result = adapter.probe_stream(
        "rtsp://h/x", {"transport": "tcp"}, "rtsp://u:p@h/x")
    assert result["available"] is True
    assert result["width"] == 640 and result["height"] == 480
    assert result["fps"] == 25.0
    url, options = fake.calls[0]
    assert url == "rtsp://u:p@h/x"
    assert options["rtsp_transport"] == "tcp"


def test_probe_stream_unreachable(adapter, monkeypatch):
    fake = _FakeAv(error=RuntimeError("connection refused"))
    monkeypatch.setattr(capture_rtsp, "_import_av", lambda: fake)
    result = adapter.probe_stream("rtsp://h/x", {}, "rtsp://h/x")
    assert result["available"] is False
    assert "connection refused" in result["message"]


def test_open_stream_reads_frames_until_end(adapter, monkeypatch):
    container = _FakeContainer(frames=[_FakeFrame(), _FakeFrame()])
    fake = _FakeAv(container=container)
    monkeypatch.setattr(capture_rtsp, "_import_av", lambda: fake)
    stream = adapter.open_stream("rtsp://h/x", {}, "rtsp://h/x")
    assert stream.read().size == (8, 8)
    assert stream.read().size == (8, 8)
    with pytest.raises(StreamEnded):
        stream.read()
    stream.close()
    assert container.closed


def test_grab_returns_first_frame(adapter, monkeypatch):
    container = _FakeContainer(frames=[_FakeFrame()])
    monkeypatch.setattr(capture_rtsp, "_import_av", lambda: _FakeAv(container=container))
    image = adapter.grab("rtsp://h/x", {}, "rtsp://h/x")
    assert image.size == (8, 8)
    assert container.closed


def test_grab_empty_stream(adapter, monkeypatch):
    monkeypatch.setattr(
        capture_rtsp, "_import_av", lambda: _FakeAv(container=_FakeContainer(frames=[])))
    with pytest.raises(StreamEnded):
        adapter.grab("rtsp://h/x", {}, "rtsp://h/x")


def test_grab_open_failure(adapter, monkeypatch):
    monkeypatch.setattr(
        capture_rtsp, "_import_av", lambda: _FakeAv(error=RuntimeError("nope")))
    with pytest.raises(CaptureError):
        adapter.grab("rtsp://h/x", {}, "rtsp://h/x")
