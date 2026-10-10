"""Explicit rule: from who is where and how fast, to the state of the signal (contract C1).

Pure Python, no OpenCV, no numpy: every decision can be reproduced by hand from the numbers in `reason`.

    d_stop = v * reaction_time + v^2 / (2 * deceleration)      stopping distance of the vehicle
    T_need = W / v_ped + margin                                time the pedestrian needs to cross
    TTC    = d / v                                             time before the vehicle reaches the stripes

Priority: DEGRADED > WARN_PEDESTRIAN > ANIMAL_ALERT > WARN_DRIVER > ANIMAL_WARN > PRESENCE > IDLE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

PRIORITY = ("DEGRADED", "WARN_PEDESTRIAN", "ANIMAL_ALERT", "WARN_DRIVER", "ANIMAL_WARN", "PRESENCE", "IDLE")
_RANK = {state: rank for rank, state in enumerate(PRIORITY)}   # 0 = most important

WAITING_ZONES = ("waiting_zone_left", "waiting_zone_right")
CROSSWALK = "crosswalk"
KMH = 3.6
LCD_ROW = 16
# Reasons of DEGRADED that come from the self-check or from the MCU.
FAULT_TEXT = {
    "lens_covered": "lente coperta",
    "glare": "camera abbagliata",
    "tamper": "nodo urtato: calibrazione non valida",
    "lamp_fault": "lampada guasta",
}


@dataclass
class PedestrianInfo:
    track_id: int
    zone: str | None                      # waiting_zone_left | waiting_zone_right | crosswalk | other
    waiting_s: float = 0.0                # time spent in the waiting zone
    toward_road_ms: float = 0.0           # speed component towards the carriageway
    walk_speed_ms: float | None = None    # measured walking speed, when known
    child: bool | None = None
    slow: bool | None = None
    aid: str | None = None                # None | normal | wheelchair | walking_aid | stroller
    thermal_only: bool = False            # seen by the thermal camera only


@dataclass
class VehicleInfo:
    track_id: int
    d: float                              # distance to the stripes, metres
    v: float                              # speed towards the stripes, m/s
    a: float = 0.0                        # acceleration along the motion, m/s^2 (negative = braking)
    role: str = "car"


@dataclass
class Scene:
    W: float                              # road width, metres
    pedestrians: list[PedestrianInfo] = field(default_factory=list)
    vehicles: list[VehicleInfo] = field(default_factory=list)
    video_age_s: float = 0.0              # time since the last frame
    fault: str | None = None              # see FAULT_TEXT


@dataclass
class Decision:
    state: str
    reason: str
    pedestrian: PedestrianInfo | None = None
    vehicle: VehicleInfo | None = None
    v_ped: float | None = None
    t_need: float | None = None
    ttc: float | None = None
    d_stop: float | None = None


def stopping_distance(v: float, cfg: dict) -> float:
    r = cfg["rules"]
    return v * float(r["reaction_time_s"]) + v * v / (2 * float(r["deceleration_ms2"]))


def time_needed(width: float, v_ped: float, cfg: dict) -> float:
    return width / v_ped + float(cfg["rules"]["crossing_margin_s"])


def time_to_collision(d: float, v: float) -> float:
    return d / v if v > 0 else math.inf


def green_time(width: float, v_ped: float, cfg: dict) -> float:
    """Pedestrian green needed by this pedestrian, capped."""
    r = cfg["rules"]
    needed = max(width / float(r["v_ped_default_ms"]), width / v_ped) + float(r["green_margin_s"])
    return min(float(r["green_max_s"]), needed)


def is_vulnerable(ped: PedestrianInfo) -> bool:
    return bool(ped.child or ped.slow or ped.aid not in (None, "normal") or ped.thermal_only)


def pedestrian_speed(ped: PedestrianInfo, cfg: dict) -> float:
    """v_ped: default, lower for vulnerable pedestrians, lower still if measured so."""
    r = cfg["rules"]
    v = float(r["v_ped_vulnerable_ms"]) if is_vulnerable(ped) else float(r["v_ped_default_ms"])
    if ped.walk_speed_ms is not None and ped.walk_speed_ms < v:
        v = max(ped.walk_speed_ms, float(r["v_ped_min_ms"]))
    return v


def is_present(ped: PedestrianInfo) -> bool:
    return ped.zone == CROSSWALK or ped.zone in WAITING_ZONES


def has_intention(ped: PedestrianInfo, cfg: dict) -> bool:
    """On the stripes, or on the pavement and either waiting for a while or walking towards the road."""
    r = cfg["rules"]
    if ped.zone == CROSSWALK:
        return True
    return ped.zone in WAITING_ZONES and (
        ped.waiting_s > float(r["intention_wait_s"]) or ped.toward_road_ms > float(r["toward_road_min_ms"]))


def describe(ped: PedestrianInfo) -> str:
    if ped.thermal_only:
        return "pedone non classificato"
    if ped.aid not in (None, "normal"):
        return f"pedone con ausilio ({ped.aid})"
    if ped.child:
        return "bambino"
    if ped.slow:
        return "pedone lento"
    return "pedone"


def evaluate(scene: Scene, cfg: dict) -> Decision:
    """The state the scene calls for, without memory (see RuleEngine for the hold time)."""
    r = cfg["rules"]
    if scene.video_age_s > float(r["video_timeout_s"]):
        return Decision("DEGRADED", f"video assente da {scene.video_age_s:.1f} s")
    if scene.fault:
        return Decision("DEGRADED", FAULT_TEXT.get(scene.fault, scene.fault))

    present = [p for p in scene.pedestrians if is_present(p)]
    if not present:
        return Decision("IDLE", "nessun pedone")

    margin = float(r["stop_margin_m"])
    best: Decision | None = None
    for ped in present:
        if not has_intention(ped, cfg):
            continue
        v_ped = pedestrian_speed(ped, cfg)
        t_need = time_needed(scene.W, v_ped, cfg)
        for veh in scene.vehicles:
            if veh.v < float(r["vehicle_min_speed_ms"]) or veh.d < 0:
                continue   # not approaching
            d_stop = stopping_distance(veh.v, cfg)
            ttc = time_to_collision(veh.d, veh.v)
            who = f"{describe(ped)} {v_ped:.1f} m/s; {veh.role} {veh.v * KMH:.0f} km/h a {veh.d:.0f} m"
            if veh.d <= d_stop + margin:
                if veh.a <= float(r["not_braking_ms2"]):
                    continue   # close but braking: the driver is yielding
                state = "WARN_PEDESTRIAN"
                reason = f"{who}; non frena e d <= d_stop + {margin:.0f} m ({d_stop + margin:.1f} m)"
            elif ttc < t_need:
                state = "WARN_DRIVER"
                reason = f"{who}; TTC {ttc:.1f} s < T_need {t_need:.1f} s"
            else:
                continue
            candidate = Decision(state, reason, ped, veh, v_ped, t_need, ttc, d_stop)
            if best is None or (_RANK[state], ttc) < (_RANK[best.state], best.ttc):
                best = candidate
    if best is not None:
        return best

    slowest = min(present, key=lambda p: pedestrian_speed(p, cfg))
    where = "sulle strisce" if any(p.zone == CROSSWALK for p in present) else "in attesa"
    return Decision("PRESENCE", f"{describe(slowest)} {where}", slowest, None, pedestrian_speed(slowest, cfg))


def lcd_text(row1: str, row2: str = "") -> str:
    """Two rows of 16 ASCII characters for the drivers' display, as one string."""
    text = row1[:LCD_ROW].ljust(LCD_ROW) + row2[:LCD_ROW]
    return text.rstrip()


def command(decision: Decision, scene: Scene, cfg: dict) -> dict:
    """The C1 fields decided by the rule (seq, t_ms and v are added when the command is sent)."""
    r = cfg["rules"]
    state = decision.state
    present = [p for p in scene.pedestrians if is_present(p)] if state != "DEGRADED" else []
    on_stripes = any(p.zone == CROSSWALK for p in present)

    green_s = extend_s = 0
    if present:
        v_ped = min(pedestrian_speed(p, cfg) for p in present)
        green = green_time(scene.W, v_ped, cfg)
        standard = green_time(scene.W, float(r["v_ped_default_ms"]), cfg)
        green_s = round(green)
        # Never ask for more than the controller accepts (fixed limit in the firmware).
        extend_s = min(int(r["ped_green_extend_max_s"]), max(0, round(green - standard)))

    kmh = round(decision.vehicle.v * KMH) if decision.vehicle else 0
    lcd = oled = ""
    if state == "PRESENCE":
        lcd = lcd_text("PEDONE", "SULLE STRISCE" if on_stripes else "IN ATTESA")
        # The AI does not know the phase of the signal: it never tells a pedestrian to cross.
        oled = f"TEMPO VERDE {green_s} s"
    elif state == "WARN_DRIVER":
        lcd = lcd_text(f"PEDONE {kmh:3d} km/h", "RALLENTA")
        oled = f"ATTENDI auto {kmh}km/h"
    elif state == "WARN_PEDESTRIAN":
        lcd = lcd_text(f"FRENA! {kmh:3d} km/h", "PEDONE")
        oled = f"FERMO! auto {kmh}km/h"
    elif state in ("ANIMAL_WARN", "ANIMAL_ALERT"):
        lcd = lcd_text("ANIMALE", "IN STRADA")
    lcd = lcd[:int(r["lcd_max_chars"])]

    return {
        "state": state,
        "led": r["led"][state],
        "green_s": green_s,
        "req": {
            "ped_green_extend_s": extend_s,
            "veh_red_hold": state in ("WARN_DRIVER", "WARN_PEDESTRIAN") or on_stripes,
            "flash": state == "ANIMAL_ALERT",
        },
        "lcd": lcd,
        "oled": oled,
        "reason": decision.reason,
    }


class RuleEngine:
    """State machine: steps up at once, steps down only after `hold_s` (no flicker on the lamps)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.hold_s = float(cfg["rules"]["hold_s"])
        self.state = "IDLE"
        self.decision = Decision("IDLE", "avvio")
        self._output: dict | None = None
        self._last_true = -math.inf   # last time the current state was what the scene called for

    def step(self, scene: Scene, t: float = 0.0) -> dict:
        decision = evaluate(scene, self.cfg)
        if decision.state == self.state:
            self._last_true = t
        steps_down = _RANK[decision.state] > _RANK[self.state]
        if self._output is not None and steps_down and t - self._last_true < self.hold_s:
            return self._output   # hold the more important state a little longer
        if decision.state != self.state:
            self.state = decision.state
            self._last_true = t
        self.decision = decision
        self._output = command(decision, scene, self.cfg)
        return self._output
