import numpy as np
import pytest
import supervision as sv

from smartcrossing.config import load_config
from smartcrossing.counting import LineCounter
from smartcrossing.geometry import in_direction, load_calib, save_calib, to_normalized, to_pixels

W, H = 641, 481   # odd sizes: normalized 0.5 falls exactly on pixel 320 / 240
CALIB = {"v": 1, "lines": {"ped": {"start": [0.5, 0.0], "end": [0.5, 1.0]},     # vertical, x = 320
                           "veh": {"start": [0.0, 0.5], "end": [1.0, 0.5]}}}    # horizontal, y = 240


def make_counter(**overrides):
    cfg = load_config()
    cfg["counting"].update(overrides)
    return LineCounter(cfg, CALIB, (W, H))


def frame(*objects):
    """objects: (track_id, x of the bottom centre, y of the bottom edge, role[, valid])."""
    xyxy = np.array([[o[1] - 10, o[2] - 40, o[1] + 10, o[2]] for o in objects], dtype=np.float32)
    tracked = sv.Detections(xyxy=xyxy, confidence=np.full(len(objects), 0.9, np.float32),
                            class_id=np.zeros(len(objects), int),
                            tracker_id=np.array([o[0] for o in objects]))
    roles = [o[3] for o in objects]
    valid = np.array([o[4] if len(o) > 4 else True for o in objects], dtype=bool)
    return tracked, roles, valid


def run(counter, track_id, xs, y=100.0, role="pedestrian"):
    events = []
    for x in xs:
        events += counter.update(*frame((track_id, x, y, role)))
    return events


def test_real_crossing_counts_once_in_the_right_direction():
    counter = make_counter()
    events = run(counter, 1, range(260, 400, 10))            # left -> right across x = 320
    assert events == [{"type": "crossing", "track_id": 1, "cls": "pedestrian", "dir": "in", "line": "ped"}]
    assert run(counter, 2, range(400, 260, -10)) == [
        {"type": "crossing", "track_id": 2, "cls": "pedestrian", "dir": "out", "line": "ped"}]
    assert counter.totals("ped") == {"in": 1, "out": 1}
    assert counter.counts["ped"]["pedestrian"] == {"in": 1, "out": 1}


def test_track_jittering_on_the_line_is_not_counted():
    counter = make_counter()
    xs = [318, 322, 318, 323, 317, 322, 319, 321] * 5         # 1 frame per side: below the threshold
    assert run(counter, 1, xs) == []
    assert counter.totals("ped") == {"in": 0, "out": 0}


def test_each_track_counts_at_most_once_per_direction():
    counter = make_counter()
    forth, back = list(range(260, 400, 10)), list(range(400, 260, -10))
    events = run(counter, 1, forth + back + forth + back)     # crosses 4 times
    assert [e["dir"] for e in events] == ["in", "out"]
    assert counter.totals("ped") == {"in": 1, "out": 1}


def test_lines_only_count_their_own_roles():
    counter = make_counter()
    run(counter, 1, range(260, 400, 10), role="car")          # a car over the pedestrian line
    assert counter.totals("ped") == {"in": 0, "out": 0}
    # The same car moving down across the vehicle line (y = 240).
    events = []
    for y in range(180, 320, 10):
        events += counter.update(*frame((1, 100.0, float(y), "car")))
    assert [(e["line"], e["cls"]) for e in events] == [("veh", "car")]
    assert counter.totals("veh")["in"] + counter.totals("veh")["out"] == 1


def test_ridden_two_wheelers_and_young_tracks_are_not_counted():
    counter = make_counter()
    assert run(counter, 1, range(260, 400, 10), role="ridden") == []
    events = []
    for x in range(260, 400, 10):
        events += counter.update(*frame((2, float(x), 100.0, "pedestrian", False)))   # not valid yet
    assert events == [] and counter.totals("ped") == {"in": 0, "out": 0}


def test_cyclist_and_bicycle_together_count_one():
    counter = make_counter()
    events = []
    for x in range(260, 400, 10):
        events += counter.update(*frame((1, float(x), 100.0, "cyclist"), (2, float(x) + 5, 110.0, "ridden")))
    assert len(events) == 1 and events[0]["cls"] == "cyclist"


def test_only_the_segment_between_the_two_ends_counts():
    # LineZone ignores anchors beyond the ends of the line: here the line stops at 80% of the height.
    cfg = load_config()
    short = {"v": 1, "lines": {"ped": {"start": [0.5, 0.0], "end": [0.5, 0.8]}}}
    counter = LineCounter(cfg, short, (W, H))
    assert run(counter, 1, range(260, 400, 10), y=300.0) != []        # inside the segment
    assert run(counter, 2, range(260, 400, 10), y=float(H - 1)) == []  # below its end


def test_example_calib_counts_a_box_that_touches_the_bottom_of_the_frame():
    # Webcam on a desk: the person's box is cut by the bottom edge of the image.
    cfg = load_config()
    cfg["counting"]["calib_path"] = "does_not_exist.json"
    calib, used = load_calib(cfg)
    assert used.name == "calib.example.json"
    counter = LineCounter(cfg, calib, (W, H))
    events = run(counter, 1, range(260, 400, 10), y=float(H - 1))
    assert [(e["line"], e["dir"]) for e in events] == [("ped", "in")]


def test_uncalibrated_line_is_skipped_and_summary_reads_well():
    cfg = load_config()
    counter = LineCounter(cfg, {"v": 1, "lines": {"ped": CALIB["lines"]["ped"]}}, (W, H))
    assert list(counter.lines) == ["ped"]
    run(counter, 1, range(260, 400, 10))
    assert counter.summary() == "ped: IN 1 OUT 0  (pedestrian 1/0)"
    assert LineCounter(cfg, {"v": 1}, (W, H)).summary() == "no counting lines"


@pytest.mark.parametrize("start, end", [((320, 0), (320, 480)), ((0, 240), (640, 240)),
                                        ((100, 400), (500, 80)), ((600, 50), (40, 430))])
def test_in_direction_matches_linezone(start, end):
    dx, dy = in_direction(start, end)
    mid = np.array([(start[0] + end[0]) / 2, (start[1] + end[1]) / 2])
    zone = sv.LineZone(start=sv.Point(*start), end=sv.Point(*end),
                       triggering_anchors=[sv.Position.BOTTOM_CENTER], minimum_crossing_threshold=1)
    for step in range(-5, 6):
        x, y = mid + np.array([dx, dy]) * step * 10            # walk along the IN direction
        zone.trigger(sv.Detections(xyxy=np.array([[x - 5, y - 20, x + 5, y]], dtype=np.float32),
                                   tracker_id=np.array([1])))
    assert (zone.in_count, zone.out_count) == (1, 0)


def test_pixel_conversion_round_trip():
    assert to_pixels([0.5, 0.5], W, H) == (320, 240)
    assert to_pixels([0.0, 1.0], W, H) == (0, 480)
    assert to_normalized((320, 240), W, H) == [0.5, 0.5]


def test_calib_file_round_trip_and_example_fallback(tmp_path):
    cfg = load_config()
    path = tmp_path / "calib.json"
    save_calib({"lines": CALIB["lines"]}, path)
    calib, used = load_calib(cfg, path)
    assert calib == CALIB and used == path
    # Without calib.json the committed example is used.
    cfg["counting"]["calib_path"] = str(tmp_path / "missing.json")
    calib, used = load_calib(cfg)
    assert used.name == "calib.example.json" and set(calib["lines"]) == {"ped", "veh"}
    with pytest.raises(FileNotFoundError):
        load_calib(cfg, tmp_path / "nope.json")


def test_track_hidden_on_the_line_still_counts():
    # A car seen left of the line, hidden (by a pole) for 8 detector frames, then seen right of it with the same ID.
    def hidden_crossing(counter):
        events = run(counter, 1, [260, 270, 280])
        for _ in range(8):
            events += counter.update(*frame((99, 50.0, 100.0, "pedestrian")))   # someone else, far away
        return events + run(counter, 1, [360, 370, 380, 390])
    assert [e["dir"] for e in hidden_crossing(make_counter(side_memory=30))] == ["in"]
    # supervision's own limit (threshold + 1 = 4 frames) forgot the side: the crossing was lost.
    assert hidden_crossing(make_counter(side_memory=0)) == []
