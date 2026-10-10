// MDGB technician's panel. python/vision.py sends a "vision" message a few times a second: the frame as JPEG
// (field jpg, base64), the boxes of the tracks in frame pixels, the counting lines and zones, the rule, the
// sensors of the sketch and the last events. Everything is drawn here; nothing is stored.

const GROUP_COLORS = {
  person: "#50c850",      // pedestrians
  two_wheeler: "#ffc800", // cyclists, motorcyclists
  vehicle: "#00a0ff",     // cars, buses, trucks
  animal: "#c850c8",
  pending: "#969696",     // track not yet valid (younger than min_track_age), or a ridden two-wheeler
};
const STATE_COLORS = {
  IDLE: "#7a828c", PRESENCE: "#d0d4d9", WARN_DRIVER: "#ffaa00", WARN_PEDESTRIAN: "#ff4d4f",
  ANIMAL_WARN: "#ffaa00", ANIMAL_ALERT: "#ff7a1a", DEGRADED: "#ffe14d",
};
const STATE_NAMES = {
  IDLE: "Nessuno", PRESENCE: "Presenza", WARN_DRIVER: "Avviso conducenti", WARN_PEDESTRIAN: "Avviso pedoni",
  ANIMAL_WARN: "Animale vicino", ANIMAL_ALERT: "Animale in strada", DEGRADED: "Degradato",
};
const ROLE_NAMES = {
  pedestrian: "pedoni", cyclist: "ciclisti", motorcyclist: "motociclisti", car: "auto", bus: "bus",
  truck: "camion", bicycle: "bici", motorcycle: "moto", animal: "animali", bird: "uccelli",
};
const PHASE_NAMES = { detect: "rileva", track: "traccia", rules: "regola", act: "invio" };
const PHASE_SCALE_MS = 120;   // full bar
const STALE_MS = 3000;        // no message for longer: the vision is restarting or the camera is missing

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
const image = new Image();

const opts = loadOpts();
let paused = false;
let lastMsg = null;
let lastSeen = 0;
let clearedBefore = 0;   // log lines older than this are hidden ("Pulisci")

// ---------- connection ----------
const ui = new WebUI();
ui.on_connect(() => setPill("pill-page", "ok", "Pagina"));
ui.on_disconnect(() => setPill("pill-page", "bad", "Pagina"));
ui.on_message("config", (cfg) => {
  $("privacy").textContent = cfg.live
    ? "Le immagini non vengono mai salvate: si producono solo mentre questa pagina è aperta."
    : "Vista dal vivo disattivata (MDGB_LIVE_VIEW=0): solo riquadri e numeri.";
});
ui.on_message("vision", onVision);

function setPill(id, cls, text) {
  const el = $(id);
  el.className = "pill " + cls;
  el.textContent = text;
}

// ---------- options (remembered in this browser only) ----------
function loadOpts() {
  const base = { labels: true, scene: true, groups: { person: true, two_wheeler: true, vehicle: true, animal: true, pending: true } };
  try {
    const saved = JSON.parse(localStorage.getItem("mdgb-opts") || "null");
    if (saved) return { ...base, ...saved, groups: { ...base.groups, ...(saved.groups || {}) } };
  } catch (e) { /* storage not available: defaults */ }
  return base;
}
function saveOpts() {
  try { localStorage.setItem("mdgb-opts", JSON.stringify(opts)); } catch (e) { /* ignore */ }
}
document.querySelectorAll("#filters input").forEach((input) => {
  if (input.dataset.opt) input.checked = opts[input.dataset.opt];
  if (input.dataset.group) input.checked = opts.groups[input.dataset.group];
  input.addEventListener("change", () => {
    if (input.dataset.opt) opts[input.dataset.opt] = input.checked;
    if (input.dataset.group) opts.groups[input.dataset.group] = input.checked;
    saveOpts();
    if (lastMsg) render(lastMsg, lastMsg.jpg ? image : null);
  });
});

$("btn-pause").addEventListener("click", () => {
  paused = !paused;
  $("btn-pause").setAttribute("aria-pressed", String(paused));
  $("btn-pause").textContent = paused ? "▶ Riprendi" : "⏸ Pausa";
  showBanner();
});
$("btn-full").addEventListener("click", () => {
  const stage = $("stage");
  if (document.fullscreenElement) document.exitFullscreen();
  else if (stage.requestFullscreen) stage.requestFullscreen();
});
$("btn-clear").addEventListener("click", () => {
  clearedBefore = Date.now() / 1000;
  if (lastMsg) showLog(lastMsg.log || []);
});

// ---------- messages ----------
function onVision(msg) {
  lastSeen = Date.now();
  showPanels(msg);
  if (paused || !msg.w) return;        // frozen by the technician, or no frame (camera missing)
  if (msg.jpg) {
    image.onload = () => { if (lastMsg === msg) render(msg, image); };
    lastMsg = msg;
    image.src = "data:image/jpeg;base64," + msg.jpg;
  } else {
    lastMsg = msg;
    render(msg, null);
  }
}

// ---------- live view ----------
function render(msg, img) {
  if (canvas.width !== msg.w || canvas.height !== msg.h) {
    canvas.width = msg.w;
    canvas.height = msg.h;
  }
  if (img) ctx.drawImage(img, 0, 0, msg.w, msg.h);
  else { ctx.fillStyle = "#000"; ctx.fillRect(0, 0, msg.w, msg.h); }

  const font = Math.max(11, Math.round(msg.w / 55));
  ctx.font = `600 ${font}px system-ui, sans-serif`;
  ctx.textBaseline = "top";
  if (opts.scene && msg.scene) drawScene(msg.scene, font);

  for (const b of msg.boxes || []) {
    if (!opts.groups[b.group]) continue;
    const color = GROUP_COLORS[b.group] || GROUP_COLORS.animal;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(2, msg.w / 320);
    ctx.setLineDash(b.group === "pending" ? [6, 4] : []);
    ctx.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    ctx.setLineDash([]);
    if (!opts.labels) continue;
    const tw = ctx.measureText(b.label).width + 8;
    const top = b.y1 - font - 6 >= 0 ? b.y1 - font - 6 : b.y1;
    ctx.fillStyle = color;
    ctx.fillRect(b.x1, top, tw, font + 6);
    ctx.fillStyle = "#000";
    ctx.fillText(b.label, b.x1 + 4, top + 3);
  }
}

function drawScene(scene, font) {
  for (const z of scene.zones || []) {
    if (z.points.length < 3) continue;
    ctx.beginPath();
    z.points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = z.name === "crosswalk" ? "rgba(255, 255, 255, 0.10)" : "rgba(0, 200, 255, 0.10)";
    ctx.fill();
    ctx.strokeStyle = "rgba(0, 200, 255, 0.7)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  for (const l of scene.lines || []) {
    ctx.strokeStyle = "#00ffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(l.a[0], l.a[1]);
    ctx.lineTo(l.b[0], l.b[1]);
    ctx.stroke();
    const mx = (l.a[0] + l.b[0]) / 2, my = (l.a[1] + l.b[1]) / 2;
    const len = 26, tx = mx + l.in[0] * len, ty = my + l.in[1] * len;
    ctx.beginPath();
    ctx.moveTo(mx, my);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    const ang = Math.atan2(ty - my, tx - mx);
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - 8 * Math.cos(ang - 0.5), ty - 8 * Math.sin(ang - 0.5));
    ctx.lineTo(tx - 8 * Math.cos(ang + 0.5), ty - 8 * Math.sin(ang + 0.5));
    ctx.closePath();
    ctx.fillStyle = "#00ffff";
    ctx.fill();
    ctx.fillText(`${l.name} IN`, tx + 4, ty - font / 2);
  }
}

function showBanner() {
  const banner = $("banner");
  const stale = lastSeen && Date.now() - lastSeen > STALE_MS;
  const text = paused ? "In pausa: l'immagine è ferma, i numeri continuano ad aggiornarsi."
    : stale ? "Nessun dato dalla visione: si sta riavviando o la camera non risponde." : "";
  banner.hidden = !text;
  banner.textContent = text;
}

// ---------- panels ----------
function showPanels(msg) {
  setPill("pill-vision", "ok", "Visione");
  setPill("pill-sketch", msg.failsafe ? "bad" : "ok", msg.failsafe ? "Sketch: fail-safe" : "Sketch");
  setPill("pill-fps", "neutral", `${msg.fps != null ? msg.fps.toFixed(1) : "—"} FPS`);
  if (msg.uptime_s != null) $("uptime").textContent = "attiva da " + duration(msg.uptime_s);

  // rule and traffic light
  const state = $("state");
  state.textContent = STATE_NAMES[msg.state] || msg.state;
  state.title = msg.state;
  state.style.background = STATE_COLORS[msg.state] || "#555";
  $("reason").textContent = msg.reason || "";
  $("led").textContent = "LED " + (msg.led || "—");
  const req = msg.req || {};
  const reqs = [
    [`verde pedonale +${req.ped_green_extend_s || 0} s`, (req.ped_green_extend_s || 0) > 0],
    ["rosso trattenuto", !!req.veh_red_hold],
    ["rosso subito", !!req.veh_red_now],
    ["lampeggiante", !!req.flash],
  ];
  $("reqs").innerHTML = reqs.map(([t, on]) => `<span class="req${on ? " on" : ""}">${t}</span>`).join("");
  $("lcd").textContent = fitLcd(msg.lcd || "");
  $("oled").textContent = msg.oled || "";
  const s = msg.sensors || {};
  const lantern = $("lantern");
  lantern.classList.toggle("unknown", !s.lamp);
  lantern.querySelectorAll(".lamp").forEach((l) => l.classList.toggle("on", l.classList.contains(s.lamp)));

  // performance
  $("fps").textContent = msg.fps != null ? msg.fps.toFixed(1) : "—";
  $("frames").textContent = `${(msg.frames || 0).toLocaleString("it-IT")} frame`;
  if (msg.lat_ms) {
    $("bars").innerHTML = Object.entries(msg.lat_ms).map(([k, v]) => {
      const pct = v == null ? 0 : Math.min(100, (v / PHASE_SCALE_MS) * 100);
      return `<div class="bar"><span>${PHASE_NAMES[k] || k}</span><div class="track"><div class="fill${v > 80 ? " slow" : ""}" style="width:${pct}%"></div></div><span>${v == null ? "—" : v.toFixed(1) + " ms"}</span></div>`;
    }).join("");
  }
  const link = msg.link || {};
  $("c1").textContent = link.c1 ?? "—";
  $("c2").textContent = link.c2 ?? "—";
  $("rej").textContent = link.rejected ?? "—";

  // boxes per group
  const counts = { person: 0, two_wheeler: 0, vehicle: 0, animal: 0, pending: 0 };
  for (const b of msg.boxes || []) counts[b.group] = (counts[b.group] || 0) + 1;
  document.querySelectorAll("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] || 0; });

  showCounts(msg);
  showSensors(msg);
  showLog(msg.log || []);
}

function showCounts(msg) {
  const lines = msg.lines || {};
  const names = Object.keys(lines);
  $("lines").innerHTML = names.length ? names.map((name) => {
    const l = lines[name];
    const roles = Object.entries(l.roles || {})
      .map(([r, c]) => `${ROLE_NAMES[r] || r} ${c.in}/${c.out}`).join(" · ");
    const label = name === "ped" ? "Strisce (pedoni)" : name === "veh" ? "Corsia (veicoli)" : name;
    return `<div class="line-row"><header><strong>${esc(label)}</strong><div class="io"><span>IN <b>${l.in}</b></span><span>OUT <b>${l.out}</b></span></div></header><div class="roles">${esc(roles || "nessun passaggio")}</div></div>`;
  }).join("") : `<p class="muted">Nessuna linea di conteggio: manca la calibrazione.</p>`;
  const st = msg.stats || {};
  $("yield").textContent = st.yield_rate == null ? "—" : `${Math.round(st.yield_rate * 100)}%`;
  $("yield").title = st.approaching ? `${st.yielded} su ${st.approaching} veicoli` : "";
  $("nearmiss").textContent = st.near_miss ?? 0;
  $("incidents").textContent = st.incidents ?? 0;
}

function showSensors(msg) {
  const s = msg.sensors || {};
  const mcu = msg.mcu || {};
  $("s-temp").textContent = s.temp_c != null ? `${s.temp_c.toFixed(1)} °C` : "—";
  $("s-rh").textContent = s.rh != null ? `${Math.round(s.rh)} %` : "—";
  $("s-eco2").textContent = s.eco2 != null ? `${s.eco2} ppm` : "—";
  $("s-tvoc").textContent = s.tvoc != null ? `${s.tvoc} ppb` : "—";
  $("s-light").textContent = s.light != null ? `${s.light} / 1023` : "—";
  $("s-light-bar").style.width = s.light != null ? `${(s.light / 1023) * 100}%` : "0";
  if (s.accel) {
    const g = Math.hypot(...s.accel);
    $("s-accel").textContent = `${g.toFixed(2)} g  (x ${s.accel[0]}  y ${s.accel[1]}  z ${s.accel[2]})`;
  } else {
    $("s-accel").textContent = "—";
  }
  $("s-rfid").textContent = s.rfid || "—";
  const shock = mcu.shock_s_ago;
  $("s-shock").textContent = shock == null ? "mai" : `${duration(shock)} fa`;
  $("t-shock").classList.toggle("alert", shock != null && shock < 60);
  const fs = mcu.firmware_failsafe;
  $("s-fs").textContent = fs ? `${fs.reason}, ${duration(fs.s_ago)} fa` : "mai";
  $("t-fs").classList.toggle("alert", !!fs && fs.s_ago < 60);
}

let logKey = "";
function showLog(entries) {
  const shown = entries.filter((e) => e.ts > clearedBefore).reverse();
  const key = `${shown.length}:${shown.length ? shown[0].ts + shown[0].text : ""}`;
  if (key === logKey) return;   // unchanged: keep the scroll position of the list
  logKey = key;
  $("log").innerHTML = shown.length ? shown.map((e) => {
    const t = new Date(e.ts * 1000).toLocaleTimeString("it-IT");
    return `<li><time>${t}</time><span class="tag ${esc(e.type)}">${esc(e.type.replace("_", " "))}</span><span>${esc(e.text)}</span></li>`;
  }).join("") : `<li class="empty">Nessun evento.</li>`;
}

// ---------- helpers ----------
function fitLcd(text) {
  // The LCD has 2 rows of 16 characters.
  const t = text.padEnd(32, " ").slice(0, 32);
  return t.slice(0, 16) + "\n" + t.slice(16);
}
function duration(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

setInterval(() => {
  if (lastSeen && Date.now() - lastSeen > STALE_MS) {
    setPill("pill-vision", "bad", "Visione");
    const state = $("state");
    state.textContent = "Nessun dato";
    state.style.background = STATE_COLORS.DEGRADED;
  }
  showBanner();
}, 1000);
