import cv2
import numpy as np
import pytest

from smartcrossing.config import load_config
from smartcrossing.sources import FrameSource, default_source

FPS, N_FRAMES, WIDTH, HEIGHT = 30, 30, 320, 240


@pytest.fixture
def video(tmp_path):
    """Synthetic clip (grey frames) written to pytest's temporary folder."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        pytest.skip("no MJPG encoder available")
    for i in range(N_FRAMES):
        writer.write(np.full((HEIGHT, WIDTH, 3), i * 8, dtype=np.uint8))
    writer.release()
    return path


def _read_all(source):
    items = []
    while (item := source.read()) is not None:
        items.append(item)
    source.release()
    return items


def test_file_timestamps_follow_the_video_timeline(video):
    cfg = load_config()
    source = FrameSource(str(video), cfg, realtime=False)
    assert not source.is_live and source.fps == pytest.approx(FPS)
    items = _read_all(source)
    assert len(items) == N_FRAMES
    times = [t for _, t in items]
    assert np.diff(times) == pytest.approx(1 / FPS)


def test_max_fps_skips_frames_like_a_live_camera(video):
    cfg = load_config(emulate_unoq=True)   # max_fps = 10 on a 30 FPS file -> 1 frame out of 3
    source = FrameSource(str(video), cfg, realtime=False)
    assert source.fps == pytest.approx(10)
    items = _read_all(source)
    assert len(items) == N_FRAMES // 3
    assert np.diff([t for _, t in items]) == pytest.approx(3 / FPS)


def test_wide_frames_are_downscaled(video):
    cfg = load_config()
    cfg["source"]["resize_width"] = 160
    frame, _ = FrameSource(str(video), cfg, realtime=False).read()
    assert frame.shape[:2] == (120, 160)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        FrameSource("does_not_exist.mp4", load_config())


def test_default_source_prefers_samples_then_webcam(tmp_path):
    cfg = load_config()
    cfg["source"]["samples_dir"] = str(tmp_path)
    assert default_source(cfg) == "0"
    (tmp_path / "b.mp4").touch()
    (tmp_path / "a.mov").touch()
    (tmp_path / "notes.txt").touch()
    assert default_source(cfg).endswith("a.mov")
