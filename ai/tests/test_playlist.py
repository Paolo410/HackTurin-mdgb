"""Recorded videos as if from the camera: which video and calibration come next, commands of the page."""
from pathlib import Path

from smartcrossing.playlist import Playlist, calib_for


def _folder(tmp_path):
    for name in ("01_strisce_nyc.mp4", "Torino_1.mp4", "Torino_night_1.mp4", "mdgb_mixkit_4194.mp4", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "calib").mkdir()
    for name in ("01", "torino_1", "4194"):
        (tmp_path / "calib" / f"{name}.json").write_text("{}")
    return tmp_path


def test_each_sample_video_finds_its_calibration_by_name(tmp_path):
    folder = _folder(tmp_path)
    assert calib_for(folder / "Torino_1.mp4").name == "torino_1.json"
    assert calib_for(folder / "01_strisce_nyc.mp4").name == "01.json"
    assert calib_for(folder / "mdgb_mixkit_4194.mp4").name == "4194.json"
    assert calib_for(folder / "Torino_night_1.mp4") is None          # "1" is not a calibration: none


def test_previous_and_next_go_round_the_videos_of_the_folder(tmp_path):
    folder = _folder(tmp_path)
    playlist = Playlist(folder / "Torino_1.mp4", "my_calib.json")
    assert [p.name for p in playlist.videos] == ["01_strisce_nyc.mp4", "Torino_1.mp4", "Torino_night_1.mp4",
                                                  "mdgb_mixkit_4194.mp4"]
    assert playlist.current.name == "Torino_1.mp4" and playlist.calib() == Path("my_calib.json")   # --calib kept
    assert playlist.move(1).name == "Torino_night_1.mp4" and playlist.calib() is None
    playlist.move(1)
    assert playlist.move(1).name == "01_strisce_nyc.mp4"              # after the last, the first
    assert playlist.move(-1).name == "mdgb_mixkit_4194.mp4"


def test_commands_of_the_page_reach_the_vision_loop_in_order(tmp_path):
    playlist = Playlist(_folder(tmp_path) / "Torino_1.mp4")
    assert playlist.request("fwd") and playlist.request("next") and not playlist.request("rm -rf")
    assert playlist.take() == ["fwd", "next"] and playlist.take() == []
