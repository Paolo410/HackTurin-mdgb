// The Things Network → Application → Payload formatters → Uplink → Custom JavaScript formatter
// Messaggi C4-B di docs/CONTRACTS.md v1 (fPort = type), stesso layout di comms/node/payload.py e app/decoder.py.
// Solo per vederli leggibili nella console TTN: la centrale (app/ingest.py) decodifica frm_payload con decoder.py.
function decodeUplink(input) {
  var b = input.bytes, p = input.fPort;
  var u16 = function (i) { return b[i] | (b[i + 1] << 8); };
  var u32 = function (i) { return (b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)) >>> 0; };
  var na = function (v, n) { return v === n ? null : v; };
  var need = function (n) { return b.length >= n ? null : { errors: ["fPort " + p + ": " + b.length + " byte, attesi " + n] }; };
  var err;
  if (p === 1) {
    if ((err = need(26))) return err;
    var tc = b[19] > 127 ? b[19] - 256 : b[19];
    return { data: {
      kind: "agg", version: b[0] >> 4, ts_quality: (b[0] >> 2) & 3, degraded: (b[0] & 2) !== 0,
      t0: u32(1), t1: u32(1) + 60 * b[5], pedestrian: { "in": u16(6), out: u16(8) }, cyclist: u16(10),
      vehicles: u16(12), animals: b[14], vulnerable: b[15], near_miss: b[16], incident: b[17],
      yield_rate: b[18] === 255 ? null : b[18] / 100,
      env: { t_c: na(tc, -128), rh: na(b[20], 255), lux: na(u16(21), 65535) },
      backlog: u16(23) * 10, batt: na(b[25], 255)
    } };
  }
  if (p === 2) {
    if ((err = need(12))) return err;
    var states = ["IDLE", "PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN", "ANIMAL_WARN", "ANIMAL_ALERT", "DEGRADED"];
    var modes = ["normal", "degraded", "failsafe"];
    return { data: {
      kind: "hb", version: b[0] >> 4, mode: modes[(b[0] >> 2) & 3] || "unknown", ts_quality: b[0] & 3,
      ts: u32(1), state: b[5] < states.length ? states[b[5]] : null, backlog: u16(6) * 10,
      batt: na(b[8], 255), disk_free_pct: na(b[9], 255), offline_min: u16(10)
    } };
  }
  if (p === 9) return { data: { kind: "alarm", alarm: "dead" } };
  if (p === 10 || p === 11 || p === 12) {
    if ((err = need(5))) return err;
    return { data: { kind: "alarm", alarm: p === 10 ? "tamper" : p === 11 ? "incident" : "fault", ts: u32(0), code: b[4] } };
  }
  return { errors: ["fPort " + p + " sconosciuta"] };
}
