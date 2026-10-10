// The Things Network → Application → Payload formatters → Uplink → Custom JavaScript formatter
// Stesso layout di crosswalk-node/python/payload.py (28 byte, little-endian).
function decodeUplink(input) {
  var b = input.bytes;
  if (input.fPort === 9) return { data: { alarm: "mpu_silent" } };
  if (b.length !== 28) return { errors: ["payload di " + b.length + " byte, attesi 28"] };
  var u16 = function (i) { return b[i] | (b[i + 1] << 8); };
  var u32 = function (i) { return (b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)) >>> 0; };
  var cats = ["person", "wheelchair", "bicycle", "stroller", "other"];
  var dir0 = {}, dir1 = {};
  for (var k = 0; k < 5; k++) { dir0[cats[k]] = u16(5 + 2 * k); dir1[cats[k]] = u16(15 + 2 * k); }
  return {
    data: {
      version: b[0] >> 4,
      offline: ((b[0] >> 2) & 3) === 1,
      ts_quality: b[0] & 3,
      window_start: u32(1),
      dir0: dir0,
      dir1: dir1,
      backlog: u16(25) * 10,
      disk_free_pct: b[27]
    }
  };
}
