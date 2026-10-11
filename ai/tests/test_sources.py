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


def test_a_rate_that_is_not_a_divisor_of_the_video_rate_is_kept_on_average(video):
    # 7.5 FPS out of 30: steps of 4 frames; 12 FPS: steps of 2 and 3 in turn (2.5 on average), not always 2 or 3.
    cfg = load_config()
    cfg["source"]["max_fps"] = 12
    source = FrameSource(str(video), cfg, realtime=False)
    assert source.fps == pytest.approx(12)
    times = [t for _, t in _read_all(source)]
    steps = np.round(np.diff(times) * FPS).astype(int)
    assert set(steps) == {2, 3} and np.mean(steps) == pytest.approx(2.5, abs=0.1)


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


def test_a_looped_file_starts_again_and_its_timeline_goes_on(video):
    source = FrameSource(str(video), load_config(), realtime=False, loop=True)
    items = [source.read() for _ in range(N_FRAMES * 2 + N_FRAMES // 2)]
    assert all(item is not None for item in items) and source.loops == 2
    assert np.diff([t for _, t in items]) == pytest.approx(1 / FPS)        # no jump back in time at the restart


class SlowClock:
    """Fake time for the source: every frame handed over costs `cost` seconds of processing."""

    def __init__(self, cost):
        self.now, self.cost = 1000.0, cost

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_in_real_time_a_slow_reader_gets_the_frames_a_camera_would_give(video, monkeypatch):
    """A board slower than the video does not see it in slow motion: late frames are skipped."""
    from smartcrossing import sources
    clock = SlowClock(cost=0.1)                                             # 10 frames per second at most
    monkeypatch.setattr(sources, "time", clock)
    source = FrameSource(str(video), load_config(), realtime=True)
    times = []
    while (item := source.read()) is not None:
        times.append(item[1])
        clock.now += clock.cost
    assert len(times) <= N_FRAMES // 3 + 1 and source.dropped >= N_FRAMES // 2
    assert times[-1] - times[0] == pytest.approx(clock.now - clock.cost - 1000.0, abs=2 / FPS)  # video time = wall time


def test_back_and_forward_in_a_video_without_going_back_in_time(video):
    source = FrameSource(str(video), load_config(), realtime=False)
    assert source.duration_s == pytest.approx(N_FRAMES / FPS)
    for _ in range(10):
        _, t_before = source.read()
    assert source.position_s == pytest.approx(9 / FPS)
    source.seek(-1.0)                                   # back past the start: the first frame
    frame, t = source.read()
    assert source.position_s == 0 and frame.mean() == pytest.approx(0, abs=4) and t > t_before
    source.seek(0.5)
    frame, _ = source.read()
    assert source.position_s == pytest.approx(15 / FPS) and frame.mean() == pytest.approx(15 * 8, abs=4)
