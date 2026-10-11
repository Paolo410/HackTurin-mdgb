"""How well the vision counts, compared with a reference: the numbers of the benchmark (scripts/benchmark.py).

A crossing is one event {"t", "line", "dir", "cls"} (plus "x", "y" in pixels when known): the time in seconds from the
start of the video, the counting line ("ped" or "veh"), the direction ("in" / "out") and the class.
Each counted crossing is paired with at most one reference crossing of the same line and kind (pedestrian, vehicle,
cyclist, animal), the closest in time within window_s (and, with positions, within max_px pixels); a crossing in the
same direction is preferred, so a person counted twice (once each way) is one right count plus one extra. A person on
foot and one on a bike may be paired too (two models often disagree on whether a person rides): the pair belongs to
the kind of the reference crossing and "same_kind" says how often the kinds agree. From the pairs:
- counted: reference crossings that the vision counted too (recall);
- right direction: of those, how many with the same direction;
- missed: reference crossings the vision did not count;
- extra: crossings the vision counted that have no reference crossing (double counts or false ones).
Pure Python, no video: tested in tests/test_scoring.py.
"""
from __future__ import annotations

KINDS = {
    "pedestrian": ("pedestrian",),
    "vehicle": ("car", "bus", "truck", "motorcyclist", "motorcycle"),
    "cyclist": ("cyclist", "bicycle"),
    "animal": ("animal", "dog", "cat", "horse", "sheep", "cow", "bear", "bird"),
}
KIND_OF = {cls: kind for kind, classes in KINDS.items() for cls in classes}
PEOPLE = {"pedestrian", "cyclist"}          # kinds that may be paired with each other
LABELS = {"pedestrian": ("pedone", "pedoni"), "vehicle": ("veicolo", "veicoli"), "cyclist": ("ciclista", "ciclisti"),
          "animal": ("animale", "animali")}


def kind_of(cls: str) -> str | None:
    return KIND_OF.get(cls)


def match_crossings(reference: list[dict], counted: list[dict], window_s: float = 2.0,
                    max_px: float | None = None) -> dict[str, dict]:
    """Per kind: {"reference", "counted", "matched", "same_dir", "same_kind", "missed", "extra", "pairs", "missed_idx",
    "extra_idx"}.
    Pairs are (reference index, counted index); the indexes refer to the lists given."""
    candidates = []
    for i, ref in enumerate(reference):
        for j, got in enumerate(counted):
            kind_ref, kind_got = kind_of(ref["cls"]), kind_of(got["cls"])
            if ref["line"] != got["line"] or kind_ref is None or kind_got is None:
                continue
            if kind_ref != kind_got and not {kind_ref, kind_got} <= PEOPLE:
                continue
            dt = abs(float(ref["t"]) - float(got["t"]))
            if dt > window_s:
                continue
            dist = 0.0
            if max_px is not None and None not in (ref.get("x"), got.get("x")):
                dist = ((ref["x"] - got["x"]) ** 2 + (ref["y"] - got["y"]) ** 2) ** 0.5
                if dist > max_px:
                    continue
            wrong_way = 1.0 if ref["dir"] != got["dir"] else 0.0   # same direction first, then the same kind,
            other_kind = 0.5 if kind_ref != kind_got else 0.0       # then the closest
            candidates.append((wrong_way + other_kind + dt + dist / 1000.0, i, j))
    used_ref, used_got, pairs = set(), set(), []
    for _, i, j in sorted(candidates):          # closest first, each crossing used once
        if i not in used_ref and j not in used_got:
            used_ref.add(i)
            used_got.add(j)
            pairs.append((i, j))
    out = {}
    for kind in KINDS:
        refs = [i for i, e in enumerate(reference) if kind_of(e["cls"]) == kind]
        gots = [j for j, e in enumerate(counted) if kind_of(e["cls"]) == kind]
        kind_pairs = [(i, j) for i, j in pairs if kind_of(reference[i]["cls"]) == kind]
        if not refs and not gots:
            continue
        extra_idx = [j for j in gots if j not in used_got]
        out[kind] = {
            "reference": len(refs), "counted": len(gots), "matched": len(kind_pairs),
            "same_dir": sum(reference[i]["dir"] == counted[j]["dir"] for i, j in kind_pairs),
            "same_kind": sum(kind_of(counted[j]["cls"]) == kind for _, j in kind_pairs),
            "missed": len(refs) - len(kind_pairs), "extra": len(extra_idx), "pairs": kind_pairs,
            "missed_idx": [i for i in refs if i not in used_ref], "extra_idx": extra_idx,
        }
    return out


def add_up(results: list[dict[str, dict]]) -> dict[str, dict]:
    """The numbers of several videos added together (without the indexes, which belong to one video each)."""
    total: dict[str, dict] = {}
    for result in results:
        for kind, r in result.items():
            t = total.setdefault(kind, {"reference": 0, "counted": 0, "matched": 0, "same_dir": 0, "same_kind": 0,
                                        "missed": 0, "extra": 0})
            for key in t:
                t[key] += r[key]
    return total


def pct(part: float, whole: float) -> str:
    return "-" if not whole else f"{100.0 * part / whole:.0f}%"


def sentence(kind: str, r: dict) -> str:
    """One line anybody can read, e.g. "Pedoni: su 40 attraversamenti la scheda ne ha contati 36 (90%), 35 nel verso
    giusto (97%); 2 conteggi in più (doppioni o falsi)"."""
    one, many = LABELS[kind]
    name = many.capitalize()
    if not r["reference"]:
        return f"{name}: nessun passaggio nel riferimento; la scheda ne ha contati {r['counted']} (in più)."
    text = (f"{name}: su {r['reference']} passaggi la scheda ne ha contati {r['matched']} ({pct(r['matched'], r['reference'])}), "
            f"{r['same_dir']} nel verso giusto ({pct(r['same_dir'], r['matched'])})")
    if r["extra"]:
        text += f"; {r['extra']} conteggi in più (doppioni o falsi)"
    return text + "."
