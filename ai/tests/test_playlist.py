"""Recorded videos as if from the camera: which video and calibration come next, commands of the page."""
from pathlib import Path

from smartcrossing.playlist import Playlist, calib_for, is_camera, label


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


def test_entries_ahead_come_first_in_their_order_then_the_others_by_name(tmp_path):
    folder = _folder(tmp_path)
    names = sorted(p.name for p in folder.iterdir() if p.suffix == ".mp4")
    ahead = [names[-1].upper(), "camera", "not_here.mp4", names[1]]          # case of the name does not matter
    playlist = Playlist(folder / names[-1], ahead=ahead)
    assert [label(v) for v in playlist.videos[:3]] == [names[-1], "camera dal vivo", names[1]]
    assert [v.name for v in playlist.videos[3:]] == [n for n in names if n not in (names[-1], names[1])]
    assert playlist.index == 0 and len(playlist.videos) == len(names) + 1


def test_the_camera_is_an_entry_like_the_others(tmp_path):
    folder = _folder(tmp_path)
    first = sorted(p for p in folder.iterdir() if p.suffix == ".mp4")[0]
    playlist = Playlist(first, "my_calib.json", ahead=[first.name, "camera"])
    camera = playlist.move(1)
    assert is_camera(camera) and str(camera) == "0"                          # what FrameSource opens as the camera
    assert playlist.calib() is None                                          # the calibration of the node, not by name
    assert playlist.move(-1) == first.resolve() and playlist.calib() == Path("my_calib.json")


def test_without_entries_ahead_the_order_is_by_name_as_before(tmp_path):
    folder = _folder(tmp_path)
    first = sorted(p for p in folder.iterdir() if p.suffix == ".mp4")[0]
    assert Playlist(first).videos == Playlist(first, ahead=[]).videos == sorted(
        (p.resolve() for p in folder.iterdir() if p.suffix == ".mp4"), key=lambda p: p.name)
