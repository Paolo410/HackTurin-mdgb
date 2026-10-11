"""The numbers of the benchmark: pairing counted crossings with the reference ones."""
from smartcrossing.scoring import add_up, match_crossings, sentence


def crossing(t, cls="pedestrian", line="ped", d="in", x=None, y=None):
    return {"t": t, "cls": cls, "line": line, "dir": d, "x": x, "y": y}


def test_counted_missed_extra_and_direction():
    reference = [crossing(1.0), crossing(5.0, d="out"), crossing(9.0), crossing(3.0, "car", "veh")]
    counted = [crossing(1.4), crossing(5.3, d="in"),             # the same person counted the wrong way...
               crossing(5.5, d="out"),                            # ...and the right way
               crossing(20.0),                                    # nobody there in the reference
               crossing(3.1, "bus", "veh")]                       # a bus is a vehicle like a car
    r = match_crossings(reference, counted, window_s=2.0)
    ped, veh = r["pedestrian"], r["vehicle"]
    assert (ped["reference"], ped["counted"], ped["matched"]) == (3, 4, 2)
    assert ped["missed"] == 1 and ped["missed_idx"] == [2] and ped["extra"] == 2
    assert ped["same_dir"] == 2                       # same direction first: 5.5 "out" is paired with the person,
                                                      # the count the wrong way (5.3) is the extra one
    assert (veh["reference"], veh["matched"], veh["same_dir"], veh["extra"]) == (1, 1, 1, 0)


def test_closest_in_time_wins_and_each_crossing_counts_once():
    reference = [crossing(10.0), crossing(11.0)]
    counted = [crossing(10.9), crossing(10.2)]
    r = match_crossings(reference, counted)["pedestrian"]
    assert sorted(r["pairs"]) == [(0, 1), (1, 0)] and r["missed"] == 0 and r["extra"] == 0


def test_other_line_too_late_or_too_far_is_not_a_match():
    reference = [crossing(1.0, x=100, y=100)]
    assert match_crossings(reference, [crossing(1.0, line="veh")])["pedestrian"]["matched"] == 0
    assert match_crossings(reference, [crossing(3.5)], window_s=2.0)["pedestrian"]["matched"] == 0
    far = [crossing(1.0, x=400, y=100)]
    assert match_crossings(reference, far, max_px=80)["pedestrian"]["matched"] == 0
    assert match_crossings(reference, far)["pedestrian"]["matched"] == 1            # without a distance limit


def test_totals_and_the_sentence_for_everybody():
    a = match_crossings([crossing(1.0), crossing(2.0)], [crossing(1.1)])
    b = match_crossings([crossing(1.0, d="out")], [crossing(1.2, d="out"), crossing(8.0)])
    total = add_up([a, b])["pedestrian"]
    assert (total["reference"], total["matched"], total["same_dir"], total["extra"]) == (3, 2, 2, 1)
    text = sentence("pedestrian", total)
    assert text == "Pedoni: su 3 passaggi la scheda ne ha contati 2 (67%), 2 nel verso giusto (100%); 1 conteggi in più (doppioni o falsi)."
