// MDGB technician's panel. Two messages arrive from python/vision.py:
//   "health" once a second: the check of every part of the node (python/health.py), the log, the uptime;
//   "vision" a few times a second: frame (JPEG, base64), boxes, counting lines and zones, the rule, counts.
// Everything is drawn here and nothing is stored, apart from the view options in this browser.

const GROUP_COLORS = {
  person: "#50c850",      // pedestrians
  two_wheeler: "#ffc800", // cyclists, motorcyclists
  vehicle: "#00a0ff",     // cars, buses, trucks
  animal: "#c850c8",
  pending: "#969696",     // track not yet valid (younger than min_track_age), or a ridden two-wheeler
};
const STATE_COLORS = {
  IDLE: "#7a828c", PRESENCE: "#d0d4d9", WARN_DRIVER: "#ffaa00", WARN_PEDESTRIAN: "#ff4d4f",
  ANIMAL_WARN: "#ffaa00", ANIMAL_ALERT: "#ff7a1a", DEGRADED: "#ffe14d", UNKNOWN: "#7a828c",
};
const STATE_NAMES = {
  IDLE: "Strada libera", PRESENCE: "Pedone presente", WARN_DRIVER: "Avviso ai conducenti",
  WARN_PEDESTRIAN: "Avviso ai pedoni", ANIMAL_WARN: "Animale vicino", ANIMAL_ALERT: "Animale in strada",
  DEGRADED: "Visione non affidabile", UNKNOWN: "Visione non disponibile",
};
const ROLE_NAMES = {
  pedestrian: "pedoni", cyclist: "ciclisti", motorcyclist: "motociclisti", car: "auto", bus: "bus",
  truck: "camion", bicycle: "bici", motorcycle: "moto", animal: "animali", bird: "uccelli",
};
const PHASE_NAMES = { detect: "rilevamento", track: "tracciamento", rules: "regola", act: "invio" };
const CHECK_ICONS = {
  camera: "📷", ai: "🧠", link: "🔗", lamp: "🚦", accel: "📳", env: "🌡", air: "💨", light: "💡",
  rfid: "🔑", storage: "💾",
};
const STATUS_LABELS = {
  ok: "✔ Funziona", warn: "⚠ Da controllare", fault: "✖ Non funziona", waiting: "⏳ In attesa", untested: "☐ Da provare",
};
const TAG_LABELS = {
  diag: "sensori", crossing: "passaggio", state: "stato", alarm: "allarme", rfid: "badge", link: "sketch",
  near_miss: "quasi incid.", incident: "incidente",
};
const LOG_TABS = {
  all: () => true,
  diag: (e) => e.type === "diag",
  security: (e) => ["alarm", "rfid", "link"].includes(e.type),
  traffic: (e) => !["diag", "alarm", "rfid", "link"].includes(e.type),
};
const PHASE_SCALE_MS = 120;   // full bar
const STALE_MS = 3000;        // no message for longer: something is not running
const NO_DATA_MS = 6000;      // connected, or trying to, for this long without any data: say why

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
const image = new Image();

const opts = loadOpts();
let paused = false;
let connected = false;
let lastMsg = null;       // last "vision" message drawn
let lastHealth = null;    // last "health" message
let visionSeen = 0;
let healthSeen = 0;
const pageStart = Date.now();
let connectedAt = 0;
let clearedBefore = 0;    // log lines older than this are hidden ("Pulisci")
let logTab = "all";
let logKey = "";

// ---------- connection ----------
const ui = new WebUI();
ui.on_connect(() => { connected = true; connectedAt = Date.now(); showConn(); showHero(); });
ui.on_disconnect(() => { connected = false; showConn(); showHero(); });
ui.on_message("config", (cfg) => {
  // "panel": app without the vision inside; the live view is on the page of the vision service.
  const panel = cfg.mode === "panel";
  document.body.classList.toggle("mode-panel", panel);
  $("nav-live").href = panel ? "#sec-vision-page" : "#sec-live";
  if (cfg.vision_port) $("vision-link").href = `http://${window.location.hostname}:${cfg.vision_port}/`;
  $("privacy").textContent = cfg.live
    ? "Le immagini non vengono mai salvate: si producono solo mentre questa pagina è aperta."
    : "Vista dal vivo disattivata (MDGB_LIVE_VIEW=0): solo riquadri e numeri.";
});
ui.on_message("vision", onVision);
ui.on_message("health", onHealth);

function showConn() {
  $("conn").className = "conn " + (connected ? "on" : "off");
  $("conn").textContent = connected ? "Collegato" : "Non collegato";
}

// ---------- view options (remembered in this browser only) ----------
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

// ---------- buttons ----------
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
  logKey = "";
  showLog();
});
$("btn-download").addEventListener("click", downloadLog);
document.querySelectorAll("#tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    logTab = tab.dataset.tab;
    document.querySelectorAll("#tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
    logKey = "";
    showLog();
  });
});

// ---------- "health": overall status, sensor check, log ----------
function onHealth(msg) {
  healthSeen = Date.now();
  lastHealth = msg;
  showHero();
  showChecks(msg.checks || [], msg.summary || {});
  const lamp = (msg.checks || []).find((c) => c.key === "lamp");
  showLantern(lamp && lamp.status !== "fault" ? lamp.value : null);
  $("uptime").textContent = msg.uptime_s != null ? duration(msg.uptime_s) : "—";
  showLog();
}

function showHero() {
  const hero = $("hero");
  const overall = $("overall");
  const h = lastHealth;
  const now = Date.now();
  // Why the page may have nothing to show: not connected, connected but the Python sends nothing, data stopped.
  const notConnected = !connected && (healthSeen || now - pageStart > NO_DATA_MS);
  const pythonMute = connected && !healthSeen && now - connectedAt > NO_DATA_MS;
  const stopped = connected && healthSeen && now - healthSeen > STALE_MS;
  const silent = notConnected || pythonMute || stopped;
  let level, icon, title, text, items = [];
  if (silent) {
    level = "fault"; icon = "📡"; title = "La scheda non risponde";
    text = notConnected
      ? "Questa pagina non è collegata alla scheda: controlla che l'app sia avviata in App Lab e di essere sulla stessa rete."
      : pythonMute
        ? "La pagina è collegata, ma il Python dell'app non manda dati. Apri la console dell'app in App Lab e cerca un errore (la parola Traceback)."
        : `Da ${Math.round((now - healthSeen) / 1000)} s non arrivano dati: l'app si sta riavviando o si è fermata. Guarda la console in App Lab.`;
  } else if (!h) {
    level = "waiting"; icon = "⏳"; title = connected ? "Avvio in corso" : "Collegamento alla scheda…";
    text = connected ? "Aspetto i primi dati dalla scheda." : "Apro la connessione con l'app.";
  } else {
    const s = h.summary;
    const problems = h.checks.filter((c) => c.status === "fault").concat(h.checks.filter((c) => c.status === "warn"));
    items = problems;
    level = s.overall;
    if (level === "ok") {
      icon = "✅"; title = "Tutto funziona"; text = `${s.ok} controlli su ${s.total} superati.`;
    } else if (level === "waiting") {
      icon = "⏳"; title = "Avvio in corso"; text = "Aspetto i primi dati da sensori e camera (al massimo 15 s).";
    } else if (level === "warn") {
      icon = "⚠️"; title = "Da controllare";
      text = `${problems.length} ${problems.length === 1 ? "cosa da guardare" : "cose da guardare"}. Il semaforo funziona.`;
    } else {
      icon = "❌"; title = "Qualcosa non funziona";
      text = `${s.fault} ${s.fault === 1 ? "guasto" : "guasti"}${s.warn ? ` e ${s.warn} da controllare` : ""}. ` +
             "Il semaforo continua comunque il suo ciclo.";
    }
  }
  hero.className = "card hero " + level;
  $("hero-icon").textContent = icon;
  $("hero-title").textContent = title;
  $("hero-text").textContent = text;
  $("hero-list").innerHTML = items.map((c) =>
    `<li><b>${CHECK_ICONS[c.key] || ""} ${esc(c.name)}</b><span>${esc(c.detail)}</span> <a href="#check-${c.key}">cosa fare →</a></li>`
  ).join("");
  const untested = h ? h.checks.filter((c) => c.status === "untested") : [];
  $("hero-foot").textContent = [
    untested.length ? `Da provare: ${untested.map((c) => `${c.name} (${c.detail})`).join(", ")}.` : "",
    h && !silent ? "Controllo aggiornato adesso." : "",
  ].filter(Boolean).join(" ");

  const labels = { ok: "✅ Tutto OK", warn: "⚠️ Da controllare", fault: "❌ Problemi", waiting: "⏳ Avvio…" };
  const n = h && !silent ? h.summary.fault + h.summary.warn : 0;
  overall.className = "overall " + level;
  overall.textContent = silent ? "📡 Scheda muta"
    : labels[level] + (n && level !== "ok" ? ` (${n})` : "");
}

function showChecks(checks, s) {
  $("tally").innerHTML = [
    s.ok ? `<span class="t-ok">✔ ${s.ok} ok</span>` : "",
    s.warn ? `<span class="t-warn">⚠ ${s.warn} da controllare</span>` : "",
    s.fault ? `<span class="t-fault">✖ ${s.fault} ${s.fault === 1 ? "guasto" : "guasti"}</span>` : "",
    s.waiting ? `<span class="t-wait">⏳ ${s.waiting} in attesa</span>` : "",
    s.untested ? `<span class="t-wait">☐ ${s.untested} da provare</span>` : "",
  ].join("");
  $("checks").innerHTML = checks.map((c) => `
    <div class="check ${c.status}" id="check-${c.key}">
      <div class="check-head">
        <span class="check-icon" aria-hidden="true">${CHECK_ICONS[c.key] || "•"}</span>
        <div class="check-name"><b>${esc(c.name)}</b><small>${esc(c.where)}</small></div>
      </div>
      <div class="check-status">
        <span class="badge ${c.status}">${STATUS_LABELS[c.status] || c.status}</span>
        ${c.age_s != null ? `<small>${ago(c.age_s)}</small>` : ""}
      </div>
      <div class="check-value">${esc(c.shown || "—")}</div>
      <div class="check-detail">${esc(c.detail)}</div>
      ${c.hint ? `<div class="check-hint">${esc(c.hint)}</div>` : ""}
    </div>`).join("");
}

function showLantern(lamp) {
  const lantern = $("lantern");
  lantern.classList.toggle("unknown", !lamp);
  lantern.querySelectorAll(".lamp").forEach((l) => l.classList.toggle("on", !!lamp && l.classList.contains(lamp)));
}

// ---------- log ----------
function logEntries() {
  return ((lastHealth && lastHealth.log) || []).filter((e) => e.ts > clearedBefore);
}

function showLog() {
  const entries = logEntries();
  document.querySelectorAll("[data-tabcount]").forEach((el) => {
    el.textContent = entries.filter(LOG_TABS[el.dataset.tabcount]).length;
  });
  const shown = entries.filter(LOG_TABS[logTab]).reverse();
  const key = `${logTab}:${shown.length}:${shown.length ? shown[0].ts + shown[0].text : ""}`;
  if (key === logKey) return;   // unchanged: keep the scroll position of the list
  logKey = key;
  $("log").innerHTML = shown.length ? shown.map((e) => {
    // Green tag for good news from the check: back to normal, tested, start-up check with nothing to look at.
    const good = e.type === "diag" && (/di nuovo a posto|provato, funziona/.test(e.text)
      || (e.text.startsWith("controllo iniziale") && !e.text.includes("da guardare")));
    return `<li><time>${clock(e.ts)}</time><span class="tag ${esc(e.type)}${good ? " good" : ""}">${esc(TAG_LABELS[e.type] || e.type)}</span><span>${esc(logText(e))}</span></li>`;
  }).join("") : `<li class="empty">Nessun evento in questa scheda.</li>`;
}

const ROLE_ONE = {
  pedestrian: "Pedone", cyclist: "Ciclista", motorcyclist: "Motociclista", car: "Auto", bus: "Bus",
  truck: "Camion", bicycle: "Bici", motorcycle: "Moto", animal: "Animale", bird: "Uccello",
};
const LINE_WHERE = { ped: "sulle strisce", veh: "in corsia" };

function logText(e) {
  const crossing = e.type === "crossing" && /^(\S+) #(\d+) (IN|OUT) linea (\S+)$/.exec(e.text);
  if (crossing) {
    const [, role, id, dir, line] = crossing;
    return `${ROLE_ONE[role] || role} #${id} · ${dir} ${LINE_WHERE[line] || "linea " + line}`;
  }
  if (e.type === "state") {
    const [code, ...rest] = e.text.split(": ");
    return `${STATE_NAMES[code] || code}: ${rest.join(": ")}`;
  }
  return e.text;
}

function downloadLog() {
  const now = new Date();
  const lines = [`MDGB - registro del nodo, scaricato il ${now.toLocaleString("it-IT")}`, ""];
  if (lastHealth) {
    lines.push("CONTROLLO SENSORI");
    for (const c of lastHealth.checks) {
      lines.push(`  ${(STATUS_LABELS[c.status] || c.status).padEnd(18)} ${c.name}: ${c.shown || "-"} (${c.detail})`);
    }
    lines.push("");
  }
  lines.push("EVENTI");
  for (const e of logEntries()) {
    lines.push(`  ${new Date(e.ts * 1000).toLocaleString("it-IT")}  [${TAG_LABELS[e.type] || e.type}]  ${logText(e)}`);
  }
  const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  const stamp = now.toISOString().slice(0, 16).replace(/[-:T]/g, "");
  a.href = URL.createObjectURL(blob);
  a.download = `mdgb-registro-${stamp}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------- "vision": live view, rule, traffic ----------
function onVision(msg) {
  visionSeen = Date.now();
  showRule(msg);
  showTraffic(msg);
  showTech(msg);
  const counts = { person: 0, two_wheeler: 0, vehicle: 0, animal: 0, pending: 0 };
  for (const b of msg.boxes || []) counts[b.group] = (counts[b.group] || 0) + 1;
  document.querySelectorAll("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] || 0; });
  if (paused || !msg.w) return;        // frozen by the technician, or no frame (camera missing)
  lastMsg = msg;
  if (msg.jpg) {
    image.onload = () => { if (lastMsg === msg) render(msg, image); };
    image.src = "data:image/jpeg;base64," + msg.jpg;
  } else {
    render(msg, null);
  }
}

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
    ctx.fillText(`${l.name === "ped" ? "pedoni" : l.name === "veh" ? "veicoli" : l.name} IN`, tx + 4, ty - font / 2);
  }
}

function showBanner() {
  const banner = $("banner");
  const stale = visionSeen && Date.now() - visionSeen > STALE_MS;
  const text = paused ? "In pausa: l'immagine è ferma, i numeri continuano ad aggiornarsi."
    : stale ? "Nessuna immagine dalla visione: si sta riavviando o la camera non risponde (vedi Controllo sensori)." : "";
  banner.hidden = !text;
  banner.textContent = text;
}

function showRule(msg) {
  const state = $("state");
  state.textContent = (STATE_NAMES[msg.state] || msg.state) + (msg.failsafe ? " · fail-safe" : "");
  state.title = msg.state;
  state.style.background = STATE_COLORS[msg.state] || "#555";
  $("reason").textContent = msg.reason || "";
  $("led").textContent = msg.led ? "LED " + msg.led : "—";
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
}

function showTraffic(msg) {
  const lines = msg.lines || {};
  const names = Object.keys(lines);
  $("lines").innerHTML = names.length ? names.map((name) => {
    const l = lines[name];
    const roles = Object.entries(l.roles || {})
      .map(([r, c]) => `${ROLE_NAMES[r] || r} ${c.in} IN / ${c.out} OUT`).join(" · ");
    const label = name === "ped" ? "Attraversamenti sulle strisce" : name === "veh" ? "Passaggi in corsia" : name;
    return `<div class="line-row"><header><strong>${esc(label)}</strong><div class="io"><span>IN <b>${l.in}</b></span><span>OUT <b>${l.out}</b></span></div></header><div class="roles">${esc(roles || "nessun passaggio finora")}</div></div>`;
  }).join("") : `<p class="muted">Nessuna linea di conteggio: manca la calibrazione della camera.</p>`;
  const st = msg.stats || {};
  $("yield").textContent = st.yield_rate == null ? "—" : `${Math.round(st.yield_rate * 100)}%`;
  $("yield").title = st.approaching ? `${st.yielded} su ${st.approaching} veicoli` : "ancora nessun caso";
  $("nearmiss").textContent = st.near_miss ?? 0;
  $("incidents").textContent = st.incidents ?? 0;
}

function showTech(msg) {
  $("fps").textContent = msg.fps != null ? msg.fps.toFixed(1) : "—";
  if (msg.lat_ms) {
    $("bars").innerHTML = Object.entries(msg.lat_ms).map(([k, v]) => {
      const pct = v == null ? 0 : Math.min(100, (v / PHASE_SCALE_MS) * 100);
      return `<div class="bar"><span>${PHASE_NAMES[k] || k}</span><div class="track"><div class="fill${v > 80 ? " slow" : ""}" style="width:${pct}%"></div></div><span>${v == null ? "—" : v.toFixed(1) + " ms"}</span></div>`;
    }).join("");
  }
  const link = msg.link || {};
  $("frames").textContent = msg.frames != null ? msg.frames.toLocaleString("it-IT") : "—";
  $("c1").textContent = link.c1 ?? "—";
  $("c2").textContent = link.c2 ?? "—";
  $("rej").textContent = link.rejected ?? "—";
  $("profile").textContent = msg.profile ? `${msg.profile} / ${msg.input_px} px` : "—";
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
function ago(s) {
  return s < 2 ? "aggiornato ora" : `aggiornato ${duration(s)} fa`;
}
function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString("it-IT");
}
function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

setInterval(() => {
  showHero();
  showBanner();
}, 1000);
