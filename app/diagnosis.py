"""Diagnosi dei nodi in centrale (docs/CONTRACTS.md v1, "Diagnosi in centrale"): incrocia il canale MQTT (`hb`)
con il canale di backup (BLE/LoRa, messaggi C4-B già decodificati da decoder.py)."""

TEXT = {
    "ok": "nodo OK",
    "faulty": "nodo guasto",
    "network_down": "rete giù, nodo sano",
    "checking": "Wi-Fi perso, attendo il Bluetooth",
    "linux_hung": "Linux bloccato, MCU vivo",
    "tampered": "manomissione (probabile)",
    "battery_low": "batteria scarica (probabile)",
    "destroyed": "nodo distrutto o senza alimentazione",
    "unknown": "mai visto",
}


# dettagli in italiano (codici del contratto C4-B / C5), usati anche dalla dashboard
LABELS = {
    "person_down": "persona a terra", "collision": "collisione", "hard_brake": "frenata brusca",
    "vehicle_on_crosswalk": "veicolo fermo sulle strisce",
    "shock_or_tilt": "urto o inclinazione", "door_open": "sportello aperto",
    "authorized_badge": "apertura autorizzata (badge tecnico)",
    "lamp_fault": "guasto lampada", "video_lost": "video assente", "lens_covered": "lente coperta",
    "glare": "abbagliamento", "firmware_failsafe": "fail-safe del firmware", "dead": "Linux bloccato (watchdog MCU)",
    "degraded": "visione degradata", "failsafe": "semaforo in fail-safe",
}


def _result(code, via=None, detail=None, last_contact=None):
    detail = LABELS.get(detail, detail)
    return {"code": code, "text": TEXT[code] + (f" ({detail})" if detail else ""), "via": via,
            "last_contact": last_contact}


def diagnose(now, hb=None, hb_rx=None, backup=(), mqtt_window_s=30, backup_window_s=660, alarm_window_s=600,
             backup_grace_s=20):
    """hb: ultimo `hb` MQTT (dict) ricevuto all'istante hb_rx (Last Will compreso: online = false).
    backup: [(rx_at, via, decoded)] dei messaggi di backup recenti. Ritorna {"code", "text", "via", "last_contact"}."""
    backup = sorted(backup, key=lambda x: x[0])
    mqtt_ok = bool(hb) and hb.get("online") is not False and hb_rx is not None and now - hb_rx <= mqtt_window_s
    recent = [(t, v, d) for t, v, d in backup if now - t <= backup_window_s]
    last_contact = max([hb_rx or 0] + [t for t, _, _ in backup]) or None
    if last_contact is None:
        return _result("unknown")

    # stato del nodo dall'informazione più recente (hb MQTT o HB del backup)
    states = [(hb_rx, hb.get("mode"), hb.get("batt"))] if hb and hb_rx is not None and "mode" in hb else []
    states += [(t, d.get("mode"), d.get("batt")) for t, _, d in backup if d.get("kind") == "hb"]
    mode = max(states, key=lambda x: x[0])[1] if states else None
    batts = [(t, b) for t, _, b in states if b is not None]
    batts += [(t, d["batt"]) for t, _, d in backup if d.get("kind") == "agg" and d.get("batt") is not None]
    alarms = [(t, d) for t, _, d in backup if d.get("kind") == "alarm"]

    faults = [d for t, d in alarms if d["alarm"] == "fault" and now - t <= alarm_window_s]
    if mode in ("degraded", "failsafe") or faults:
        return _result("faulty", detail=faults[-1]["detail"] if faults else mode, last_contact=last_contact)
    if mqtt_ok:
        return _result("ok", "mqtt", last_contact=last_contact)
    if recent:
        return _result("network_down", recent[-1][1], last_contact=last_contact)
    # MQTT appena perso e ancora niente dal backup: il nodo accende il backup dopo 30 s senza conferme MQTT e il
    # Last Will del broker può arrivare prima del primo beacon (provato sulla UNO Q: 5 s prima). Prima di dire
    # "distrutto" si aspettano backup_grace_s dal momento in cui MQTT è stato perso.
    if hb and hb_rx is not None:
        lost_at = hb_rx if hb.get("online") is False else hb_rx + mqtt_window_s
        if now - lost_at <= backup_grace_s:
            return _result("checking", last_contact=last_contact)

    # entrambi i canali muti: si guarda cosa è successo prima del silenzio
    before = [(t, d) for t, d in alarms if last_contact - t <= alarm_window_s]
    if any(d["alarm"] == "dead" for _, d in before):
        return _result("linux_hung", last_contact=last_contact)
    badge = [t for t, d in alarms if d["alarm"] == "tamper" and d.get("code") == 3]
    tampers = [(t, d) for t, d in before if d["alarm"] == "tamper" and d.get("code") in (1, 2)
               and not (d.get("code") == 2 and any(0 <= t - b <= alarm_window_s for b in badge))]
    if tampers:
        return _result("tampered", detail=tampers[-1][1].get("detail"), last_contact=last_contact)
    if batts and max(batts)[1] < 20:
        return _result("battery_low", detail=f"{max(batts)[1]}%", last_contact=last_contact)
    return _result("destroyed", last_contact=last_contact)
