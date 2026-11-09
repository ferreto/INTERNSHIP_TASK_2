import json
import re
import subprocess
import sys
import pytest
from apply_zoom import build_zoom_filter, load_sidecar


def _eval_zoom_at(z_expr, on_frame):
    def between(x, lo, hi):
        return 1 if lo <= x <= hi else 0
    return eval(z_expr, {"on": on_frame, "between": between})


def _eval_px_at(expr, on_frame, iw=1280, ih=720, zoom=1.0):
    def between(x, lo, hi):
        return 1 if lo <= x <= hi else 0
    def max_(a, b):
        return max(a, b)
    def min_(a, b):
        return min(a, b)
    return eval(expr, {
        "on": on_frame, "between": between, "iw": iw, "ih": ih,
        "zoom": zoom, "max": max_, "min": min_,
    })


# --- String-based tests ---

def test_ramp_calculation():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [{"t": 1.0, "x": 100, "y": 100, "type": "in"}]
    }
    result = build_zoom_filter(data)
    assert "zoompan" in result
    assert "((on-25)/12)" in result


def test_clamping():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [{"t": 1.0, "x": 640, "y": 360, "type": "in"}]
    }
    result = build_zoom_filter(data)
    assert "max(0,min(iw-iw/zoom," in result
    assert "max(0,min(ih-ih/zoom," in result


def test_open_ended_zoom_string():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [{"t": 2.0, "x": 200, "y": 300, "type": "in"}]
    }
    result = build_zoom_filter(data)
    assert "(on-50)" in result
    assert "between(on,62,999987)" in result


def test_multiple_pairs_string():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 500, "type": "in"},
            {"t": 7.0, "x": 500, "y": 500, "type": "out"},
        ]
    }
    result = build_zoom_filter(data)
    assert result.count("zoompan") == 1
    assert "(on-25)" in result
    assert "(on-125)" in result
    assert "100*between" in result
    assert "500*between" in result


def test_no_events():
    assert build_zoom_filter({"events": []}) is None


def test_load_sidecar_missing_file():
    assert load_sidecar("nonexistent.webm") is None


def test_sidecar_parsing(tmp_path):
    video_path = tmp_path / "test.webm"
    video_path.touch()
    sidecar_path = tmp_path / "test.webm.zoom.json"
    sidecar_data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [{"t": 1.0, "x": 100, "y": 100, "type": "in"}]
    }
    sidecar_path.write_text(json.dumps(sidecar_data), encoding="utf-8")
    loaded = load_sidecar(str(video_path))
    assert loaded is not None
    assert loaded["fps"] == 25


def test_old_sidecar_without_type():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "events": [{"t": 1.0, "x": 100, "y": 100}]
    }
    assert build_zoom_filter(data) is None


# --- Value-based tests ---

def test_zoom_values_before_during_after():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "viewport": {"width": 1280, "height": 720},
        "events": [
            {"t": 4.0, "x": 640, "y": 360, "type": "in"},
            {"t": 6.0, "x": 640, "y": 360, "type": "out"},
        ]
    }
    z_expr = re.search(r"zoompan=z='([^']+)'", build_zoom_filter(data)).group(1)

    assert abs(_eval_zoom_at(z_expr, 0) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 99) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 106) - 1.5) < 0.05
    assert abs(_eval_zoom_at(z_expr, 112) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 120) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 138) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 144) - 1.5) < 0.05
    assert abs(_eval_zoom_at(z_expr, 150) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 200) - 1.0) < 0.01


def test_zoom_values_open_ended():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "viewport": {"width": 1280, "height": 720},
        "events": [{"t": 2.0, "x": 200, "y": 300, "type": "in"}],
    }
    z_expr = re.search(r"zoompan=z='([^']+)'", build_zoom_filter(data)).group(1)

    assert abs(_eval_zoom_at(z_expr, 0) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 49) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 56) - 1.5) < 0.05
    assert abs(_eval_zoom_at(z_expr, 62) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 100) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 10000) - 2.0) < 0.01


def test_zoom_boundaries_multiple_pairs():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "viewport": {"width": 1280, "height": 720},
        "events": [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 100, "y": 100, "type": "out"},
            {"t": 5.0, "x": 500, "y": 500, "type": "in"},
            {"t": 7.0, "x": 500, "y": 500, "type": "out"},
        ]
    }
    z_expr = re.search(r"zoompan=z='([^']+)'", build_zoom_filter(data)).group(1)

    assert abs(_eval_zoom_at(z_expr, 87) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 50) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 150) - 2.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 175) - 1.0) < 0.01
    assert abs(_eval_zoom_at(z_expr, 200) - 1.0) < 0.01


def test_zoom_x_y_values():
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "viewport": {"width": 1280, "height": 720},
        "events": [
            {"t": 2.0, "x": 400, "y": 200, "type": "in"},
            {"t": 4.0, "x": 400, "y": 200, "type": "out"},
        ]
    }
    result = build_zoom_filter(data)
    x_expr = re.search(r"zoompan=z='[^']+':x='([^']+)'", result).group(1)
    y_expr = re.search(r":y='([^']+)'", result).group(1)

    assert _eval_px_at(x_expr, 0, zoom=1.0) == 0
    assert _eval_px_at(y_expr, 0, zoom=1.0) == 0

    assert abs(_eval_px_at(x_expr, 62, zoom=2.0) - 80) < 1
    assert abs(_eval_px_at(y_expr, 62, zoom=2.0) - 20) < 1


def test_zoom_repeated_in_closes_previous():
    """A new 'in' while already zoomed should close the previous open-ended zoom."""
    data = {
        "fps": 25, "zoom_factor": 2.0, "ramp_sec": 0.5,
        "viewport": {"width": 1280, "height": 720},
        "events": [
            {"t": 1.0, "x": 100, "y": 100, "type": "in"},
            {"t": 3.0, "x": 500, "y": 500, "type": "in"},
            {"t": 5.0, "x": 500, "y": 500, "type": "out"},
        ]
    }
    z_expr = re.search(r"zoompan=z='([^']+)'", build_zoom_filter(data)).group(1)

    # First hold (frame 50)
    assert abs(_eval_zoom_at(z_expr, 50) - 2.0) < 0.01
    # Second hold (frame 100)
    assert abs(_eval_zoom_at(z_expr, 100) - 2.0) < 0.01
    # After second out at t=5.0 (frame 125) - back to 1.0
    assert abs(_eval_zoom_at(z_expr, 137) - 1.0) < 0.01
    # Far end
    assert abs(_eval_zoom_at(z_expr, 200) - 1.0) < 0.01


# --- Copy unchanged tests ---

def test_no_events_copy_unchanged(tmp_path, monkeypatch):
    """With no zoom events, main() should copy the video unchanged."""
    import apply_zoom
    import shutil as _shutil

    video_path = tmp_path / "input.webm"
    video_path.write_text("fake video content")
    output_path = tmp_path / "out.webm"

    def mock_run(*args, **kwargs):
        raise AssertionError("ffmpeg should not be called when there are no events")
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(sys, "argv", [
        "apply_zoom.py", "--video", str(video_path), "--output", str(output_path)
    ])

    result = apply_zoom.main()
    assert result == 0
    assert output_path.exists()
    assert output_path.read_text() == "fake video content"


def test_no_events_dry_run_does_not_copy(tmp_path, monkeypatch):
    """With --dry-run and no events, no output file should be created."""
    import apply_zoom

    video_path = tmp_path / "input.webm"
    video_path.write_text("fake video content")
    output_path = tmp_path / "out.webm"

    def mock_run(*args, **kwargs):
        raise AssertionError("ffmpeg should not be called")
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(sys, "argv", [
        "apply_zoom.py", "--video", str(video_path),
        "--output", str(output_path), "--dry-run"
    ])

    result = apply_zoom.main()
    assert result == 0
    assert not output_path.exists()


def test_copy_failure_returns_1_in_no_zoom_filter_branch(tmp_path, monkeypatch):
    """In the 'not zoom_filter' branch, a copy failure must return 1, not raise."""
    import apply_zoom
    import shutil as _shutil

    video_path = tmp_path / "input.webm"
    video_path.write_text("fake video content")
    # Sidecar with events but no "type" → build_zoom_filter returns None
    sidecar_path = tmp_path / "input.webm.zoom.json"
    sidecar_data = {"fps": 25, "events": [{"t": 1.0, "x": 100, "y": 100}]}
    sidecar_path.write_text(json.dumps(sidecar_data), encoding="utf-8")

    output_path = tmp_path / "out.webm"

    def mock_copy2(src, dst):
        raise PermissionError("Permission denied")
    monkeypatch.setattr(_shutil, "copy2", mock_copy2)
    monkeypatch.setattr(sys, "argv", [
        "apply_zoom.py", "--video", str(video_path), "--output", str(output_path)
    ])

    result = apply_zoom.main()
    assert result == 1
    assert not output_path.exists()