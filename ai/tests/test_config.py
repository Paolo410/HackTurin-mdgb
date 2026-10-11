import pytest

from smartcrossing.config import load_config


def test_default_profile_has_spec_values():
    cfg = load_config()
    assert cfg["profile"] == "pc"
    assert cfg["model"]["pad_value"] == 114
    assert cfg["model"]["input_size"] == 320   # (spec) 320, 416 optional
    assert cfg["tracking"]["min_track_age"] == 5
    assert set(cfg["model"]["keep_classes"]) == {
        "person", "bicycle", "car", "motorcycle", "bus", "truck",
        "dog", "cat", "horse", "sheep", "cow", "bear", "bird",
    }
    assert "profiles" not in cfg and "emulate_unoq" in cfg and cfg["emulate_unoq"] is False


def test_emulate_unoq_applies_spec_limits():
    # (spec) --emulate-unoq: 10 FPS, input 320, 4 onnxruntime threads.
    cfg = load_config(emulate_unoq=True)
    assert cfg["source"]["max_fps"] == 10
    assert cfg["model"]["input_size"] == 320
    assert cfg["model"]["intra_op_num_threads"] == 4
    # At 10 FPS five frames are half a second: a track must count sooner, or passing cars are not counted.
    assert cfg["tracking"]["min_track_age"] == 2
    # Values not overridden are kept.
    assert cfg["model"]["conf"] == load_config()["model"]["conf"]


def test_unoq_profile_overrides():
    cfg = load_config(profile="unoq")
    assert cfg["model"]["input_size"] == 320
    # Measured on the board (11/10): the detector on every frame gives 5.9 FPS, all analysed; one frame out of two
    # 8.4 FPS but only 4.2 analysed per second, and fewer crossings counted (ai/docs/BENCHMARK.md).
    assert cfg["model"]["detect_every_n"] == 1 and cfg["source"]["max_fps"] == 12
    assert cfg["model"]["intra_op_num_threads"] == 3
    assert cfg["tracking"]["min_track_age"] == 2


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        load_config(profile="nope")
