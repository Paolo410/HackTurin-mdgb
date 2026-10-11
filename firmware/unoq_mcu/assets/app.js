// MDGB technician's panel. Two messages arrive from the Python side of the app:
//   "health" once a second: the check of every part of the node (python/health.py), the log, the uptime;
//   "vision" a few times a second (once a second in the panel version): rule, counts, timings and, with the
//            vision inside the app, the frame (JPEG, base64) with the boxes of the tracks.
// Everything is drawn here and nothing is stored, apart from the view options in this browser.

const GROUP_COLORS = {
  person: "#2f9e44", two_wheeler: "#e8a400", vehicle: "#1f78c8", animal: "#a33ea1", pending: "#8a9399",
};
const STATE_NAMES = {
  IDLE: "Strada libera", PRESENCE: "Pedone presente", WARN_DRIVER: "Avviso ai conducenti",
  WARN_PEDESTRIAN: "Avviso ai pedoni", ANIMAL_WARN: "Animale vicino", ANIMAL_ALERT: "Animale in strada",
  DEGRADED: "Visione non affidabile", UNKNOWN: "Visione non disponibile",
};
const ROLE_MANY = {
  pedestrian: "Pedoni", cyclist: "Ciclisti", motorcyclist: "Motociclisti", car: "Auto", bus: "Autobus",
  truck: "Camion", bicycle: "Bici", motorcycle: "Moto", animal: "Animali", bird: "Uccelli",
};
const ROLE_ONE = {
  pedestrian: "Pedone", cyclist: "Ciclista", motorcyclist: "Motociclista", car: "Auto", bus: "Autobus",
  truck: "Camion", bicycle: "Bici", motorcycle: "Moto", animal: "Animale", bird: "Uccello", ridden: "Bici",
};
const PHASE_NAMES = { detect: "Rilevamento", track: "Tracciamento", rules: "Regola", act: "Invio" };
const STATUS_WORDS = { ok: "Funziona", warn: "Da controllare", fault: "Non funziona", waiting: "In attesa", untested: "Da provare" };
const KIND_NAMES = {
  diag: "Sensori", crossing: "Passaggio", state: "Stato", alarm: "Allarme", rfid: "Badge", link: "Visione",
  near_miss: "Quasi incidente", incident: "Incidente",
};
const INCIDENT_NAMES = {
  person_down: "persona a terra", collision: "collisione", hard_braking: "frenata brusca",
  stopped_on_crosswalk: "veicolo fermo sulle strisce",
};
const LOG_FILTERS = {
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
const pageStart = Date.now();
let mode = "app";
let connected = false;
let connectedAt = 0;
let lastHealth = null;
let healthSeen = 0;
let visionSeen = 0;
let lastFrame = null;
let paused = false;
let clearedBefore = 0;
let logFilter = "all";
let logKey = "";

// ---------- connection ----------
const ui = new WebUI();
ui.on_connect(() => { connected = true; connectedAt = Date.now(); showConn(); showStatus(); });
ui.on_disconnect(() => { connected = false; showConn(); showStatus(); });
ui.on_message("config", (cfg) => {
  // "panel": app without the vision inside; the live view is on the page of the vision service.
  mode = cfg.mode === "panel" ? "panel" : "app";
  document.body.classList.toggle("mode-panel", mode === "panel");
  if (cfg.vision_port) $("vision-link").href = `http://${window.location.hostname}:${cfg.vision_port}/`;
  if (cfg.live === false && mode === "app") {
    $("privacy").textContent = "Vista dal vivo disattivata sulla scheda: si vedono solo i riquadri.";
  }
});
ui.on_message("health", onHealth);
ui.on_message("vision", onVision);

function showConn() {
  $("conn").className = "conn " + (connected ? "on" : "off");
  $("conn").textContent = connected ? "Collegato" : "Non collegato";
  $("conn").title = connected ? "Questa pagina riceve i dati dalla scheda" : "Questa pagina non riceve dati dalla scheda";
}

// ---------- tabs (in the address, so a link opens the right one) ----------
function showView() {
  const name = (window.location.hash || "#stato").slice(1);
  const view = ["stato", "traffico", "registro"].includes(name) ? name : "stato";
  for (const v of ["stato", "traffico", "registro"]) $("view-" + v).hidden = v !== view;
  document.querySelectorAll(".tabs a").forEach((a) => a.setAttribute("aria-selected", String(a.dataset.view === view)));
}
window.addEventListener("hashchange", showView);
showView();

// ---------- "health": status, parts, log ----------
function onHealth(msg) {
  healthSeen = Date.now();
  lastHealth = msg;
  showStatus();
  showParts(msg.checks || []);
  const lamp = (msg.checks || []).find((c) => c.key === "lamp");
  showLantern(lamp && lamp.status !== "fault" ? lamp.value : null);
  $("uptime").textContent = msg.uptime_s != null ? duration(msg.uptime_s) : "–";
  showLog();
}

function showStatus() {
  const now = Date.now();
  const h = lastHealth;
  const notConnected = !connected && (healthSeen || now - pageStart > NO_DATA_MS);
  const pythonMute = connected && !healthSeen && now - connectedAt > NO_DATA_MS;
  const stopped = connected && healthSeen && now - healthSeen > STALE_MS;
  let level, title, text;
  if (notConnected) {
    level = "fault"; title = "La scheda non risponde";
    text = "Questa pagina non è collegata alla scheda. Controlla che l'app sia avviata in App Lab e di essere sulla stessa rete.";
  } else if (pythonMute) {
    level = "fault"; title = "L'app non manda dati";
    text = "La pagina è collegata, ma il Python dell'app non risponde. Apri la console dell'app in App Lab e cerca un errore (la parola Traceback).";
  } else if (stopped) {
    level = "fault"; title = "La scheda non risponde";
    text = `Da ${Math.round((now - healthSeen) / 1000)} secondi non arrivano dati: l'app si sta riavviando o si è fermata.`;
  } else if (!h) {
    level = "waiting"; title = connected ? "Avvio in corso" : "Collegamento alla scheda";
    text = connected ? "Aspetto i primi dati dalla scheda." : "Apro la connessione con l'app.";
  } else {
    const s = h.summary;
    const problems = s.fault + s.warn;
    level = s.overall;
    if (level === "ok") {
      title = "Tutto funziona";
      text = `${s.ok} parti su ${s.total} rispondono.` + (s.untested ? " Il lettore badge si prova passando un badge." : "");
    } else if (level === "waiting") {
      title = "Avvio in corso";
      text = "Sensori e camera hanno 15 secondi per mandare il primo dato.";
    } else if (level === "warn") {
      title = problems === 1 ? "Una cosa da controllare" : `${problems} cose da controllare`;
      text = "Il semaforo funziona. Trovi cosa fare qui sotto.";
    } else {
      title = problems === 1 ? "Una cosa da sistemare" : `${problems} cose da sistemare`;
      text = "Il semaforo continua comunque il suo ciclo. Trovi cosa fare qui sotto.";
    }
  }
  $("status").className = "status " + level;
  $("status-title").textContent = title;
  $("status-text").textContent = text;
  const count = $("count-stato");
  const n = h && level !== "waiting" && !notConnected && !pythonMute && !stopped ? h.summary.fault + h.summary.warn : 0;
  count.hidden = !n;
  count.textContent = n;
  count.className = "badge-count" + (h && !h.summary.fault ? " warn" : "");
}

function showParts(checks) {
  const problems = checks.filter((c) => c.status === "fault").concat(checks.filter((c) => c.status === "warn"));
  const oks = checks.filter((c) => c.status === "ok");
  const others = checks.filter((c) => c.status === "waiting" || c.status === "untested");

  $("group-problems").hidden = !problems.length;
  $("problems").innerHTML = problems.map((c) => `
    <li class="part ${c.status}">
      <span class="dot"></span><span class="part-name">${esc(c.name)}</span><span class="part-word">${STATUS_WORDS[c.status]}</span>
      <p class="part-more">${esc(sentence(c.detail))} Collegato a: ${esc(c.where)}.</p>
      ${c.hint ? `<p class="part-fix"><b>Cosa fare</b>${esc(c.hint)}</p>` : ""}
    </li>`).join("");

  $("group-ok").hidden = !oks.length;
  $("ok-title").textContent = oks.length === checks.length ? "Tutte le parti funzionano" : `Funzionano (${oks.length})`;
  $("oks").innerHTML = oks.map((c) => `
    <li class="part ok" title="${esc(sentence(c.detail))} Collegato a: ${esc(c.where)}.">
      <span class="dot"></span><span class="part-name">${esc(c.name)}</span><span class="part-value">${esc(c.shown || "")}</span>
    </li>`).join("");

  $("group-other").hidden = !others.length;
  $("others").innerHTML = others.map((c) => `
    <li class="part ${c.status}">
      <span class="dot"></span><span class="part-name">${esc(c.name)}</span><span class="part-word">${STATUS_WORDS[c.status]}</span>
      <p class="part-more">${esc(sentence(c.detail))}</p>
    </li>`).join("");
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
  document.querySelectorAll("[data-logcount]").forEach((el) => {
    el.textContent = entries.filter(LOG_FILTERS[el.dataset.logcount]).length;
  });
  const shown = entries.filter(LOG_FILTERS[logFilter]).reverse();
  const key = `${logFilter}:${shown.length}:${shown.length ? shown[0].ts + shown[0].text : ""}`;
  if (key === logKey) return;   // unchanged: keep the scroll position
  logKey = key;
  $("log").innerHTML = shown.length ? shown.map((e) => `
    <li><time>${clock(e.ts)}</time><span class="kind ${esc(e.type)}${isGood(e) ? " good" : ""}">${esc(KIND_NAMES[e.type] || e.type)}</span><span>${esc(logText(e))}</span></li>`
  ).join("") : `<li class="empty">${entries.length ? "Nessun evento di questo tipo." : "Ancora nessun evento."}</li>`;
}

function isGood(e) {
  return e.type === "diag" && (/di nuovo a posto|provato: funziona/.test(e.text)
    || (e.text.startsWith("controllo iniziale") && !e.text.includes("da guardare")));
}

function fields(text) {
  // "a=12 b=31 ttc_s=0.8" -> {a: "12", b: "31", ttc_s: "0.8"}
  return Object.fromEntries(text.split(" ").map((p) => p.split("=")).filter((p) => p.length === 2));
}

function logText(e) {
  if (e.type === "crossing") {
    const m = /^(\S+) #(\d+) (IN|OUT) linea (\S+)$/.exec(e.text);
    if (m) {
      const where = { ped: "sulle strisce", veh: "in corsia" }[m[4]] || `sulla linea ${m[4]}`;
      return `${ROLE_ONE[m[1]] || m[1]} #${m[2]} passato ${where}, verso ${m[3]}.`;
    }
  }
  if (e.type === "state") {
    const [code, ...rest] = e.text.split(": ");
    return `${STATE_NAMES[code] || code}: ${rest.join(": ")}.`;
  }
  if (e.type === "near_miss") {
    const f = fields(e.text);
    const ttc = f.ttc_s && f.ttc_s !== "None" ? `, ${num(f.ttc_s)} s alla collisione` : "";
    return `Tra #${f.a} e #${f.b}${ttc}.`;
  }
  if (e.type === "incident") {
    const f = fields(e.text);
    return sentence(`${INCIDENT_NAMES[f.kind] || f.kind || "evento"}` + (f.track_id ? `, traccia #${f.track_id}` : ""));
  }
  return sentence(e.text);
}

document.querySelectorAll("[data-log]").forEach((chip) => {
  chip.addEventListener("click", () => {
    logFilter = chip.dataset.log;
    document.querySelectorAll("[data-log]").forEach((c) => c.classList.toggle("active", c === chip));
    logKey = "";
    showLog();
  });
});
$("btn-clear").addEventListener("click", () => { clearedBefore = Date.now() / 1000; logKey = ""; showLog(); });
$("btn-download").addEventListener("click", () => {
  const now = new Date();
  const lines = [`MDGB, registro del nodo scaricato il ${now.toLocaleString("it-IT")}`, ""];
  if (lastHealth) {
    lines.push($("status-title").textContent + ". " + $("status-text").textContent, "", "PARTI DEL NODO");
    for (const c of lastHealth.checks) {
      lines.push(`  ${STATUS_WORDS[c.status].padEnd(15)} ${c.name}${c.shown ? ": " + c.shown : ""}. ${sentence(c.detail)}`);
      if (c.hint) lines.push(`  ${"".padEnd(15)} Cosa fare: ${c.hint}`);
    }
    lines.push("");
  }
  lines.push("EVENTI");
  for (const e of logEntries()) {
    lines.push(`  ${new Date(e.ts * 1000).toLocaleString("it-IT")}  ${(KIND_NAMES[e.type] || e.type).padEnd(16)} ${logText(e)}`);
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" }));
  a.download = `mdgb-registro-${now.toISOString().slice(0, 16).replace(/[-:T]/g, "")}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// ---------- "vision": rule, counts, timings, live view ----------
function onVision(msg) {
  visionSeen = Date.now();
  showSignal(msg);
  showCounts(msg);
  showTech(msg);
  const counts = { person: 0, two_wheeler: 0, vehicle: 0, animal: 0, pending: 0 };
  for (const b of msg.boxes || []) counts[b.group] = (counts[b.group] || 0) + 1;
  document.querySelectorAll("[data-count]").forEach((el) => { el.textContent = counts[el.dataset.count] || 0; });
  if (paused || !msg.w) return;        // frozen by the technician, or no frame
  lastFrame = msg;
  if (msg.jpg) {
    image.onload = () => { if (lastFrame === msg) render(msg, image); };
    image.src = "data:image/jpeg;base64," + msg.jpg;
  } else {
    render(msg, null);
  }
}

function showSignal(msg) {
  $("state").textContent = STATE_NAMES[msg.state] || msg.state;
  $("reason").textContent = sentence(msg.reason || "") + (msg.failsafe ? " Lo sketch è in fail-safe: ciclo normale." : "");
  const req = msg.req || {};
  const extend = req.ped_green_extend_s || 0;
  $("reqs").innerHTML = [
    [extend ? `Verde pedonale allungato di ${extend} s` : "Verde pedonale normale", extend > 0],
    ["Rosso ai veicoli trattenuto", !!req.veh_red_hold],
    ["Rosso ai veicoli subito", !!req.veh_red_now],
    ["Lampeggiante acceso", !!req.flash],
  ].map(([t, on]) => `<li class="${on ? "on" : ""}">${t}</li>`).join("");
  $("lcd").textContent = fitLcd(msg.lcd || "");
  $("oled").textContent = msg.oled || "";
}

function showCounts(msg) {
  const roles = {};
  for (const line of Object.values(msg.lines || {})) {
    for (const [role, c] of Object.entries(line.roles || {})) {
      roles[role] = roles[role] || { in: 0, out: 0 };
      roles[role].in += c.in;
      roles[role].out += c.out;
    }
  }
  const rows = Object.entries(roles).filter(([, c]) => c.in || c.out);
  const empty = !Object.keys(msg.lines || {}).length && mode === "app"
    ? "Nessuna linea di conteggio: manca la calibrazione della camera."
    : "Nessun passaggio finora.";
  $("counts").innerHTML = rows.length
    ? rows.map(([r, c]) => `<tr><td>${esc(ROLE_MANY[r] || r)}</td><td>${c.in}</td><td>${c.out}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">${empty}</td></tr>`;
  const st = msg.stats || {};
  $("yield").textContent = st.yield_rate == null ? "nessun caso" : `${Math.round(st.yield_rate * 100)}%`;
  $("nearmiss").textContent = st.near_miss ?? 0;
  $("incidents").textContent = st.incidents ?? 0;
}

function showTech(msg) {
  $("fps").textContent = msg.fps != null ? num(msg.fps.toFixed(1)) : "–";
  if (msg.lat_ms) {
    $("bars").innerHTML = Object.entries(msg.lat_ms).map(([k, v]) => {
      const pct = v == null ? 0 : Math.min(100, (v / PHASE_SCALE_MS) * 100);
      return `<div class="bar"><span>${PHASE_NAMES[k] || k}</span><div class="track"><div class="fill${v > 80 ? " slow" : ""}" style="width:${pct}%"></div></div><span>${v == null ? "–" : num(v) + " ms"}</span></div>`;
    }).join("");
  }
  const link = msg.link || {};
  $("frames").textContent = msg.frames != null ? msg.frames.toLocaleString("it-IT") : "–";
  $("c1").textContent = link.c1 ?? "–";
  $("c2").textContent = link.c2 ?? "–";
  $("rej").textContent = link.rejected ?? "–";
  $("profile").textContent = msg.profile ? `${msg.profile}, ingresso ${msg.input_px} px` : "–";
}

// ---------- live view ----------
function loadOpts() {
  const base = { labels: true, scene: true, groups: { person: true, two_wheeler: true, vehicle: true, animal: true, pending: true } };
  try {
    const saved = JSON.parse(localStorage.getItem("mdgb-opts") || "null");
    if (saved) return { ...base, ...saved, groups: { ...base.groups, ...(saved.groups || {}) } };
  } catch (e) { /* storage not available: defaults */ }
  return base;
}
document.querySelectorAll("#filters input").forEach((input) => {
  if (input.dataset.opt) input.checked = opts[input.dataset.opt];
  if (input.dataset.group) input.checked = opts.groups[input.dataset.group];
  input.addEventListener("change", () => {
    if (input.dataset.opt) opts[input.dataset.opt] = input.checked;
    if (input.dataset.group) opts.groups[input.dataset.group] = input.checked;
    try { localStorage.setItem("mdgb-opts", JSON.stringify(opts)); } catch (e) { /* ignore */ }
    if (lastFrame) render(lastFrame, lastFrame.jpg ? image : null);
  });
});
$("btn-pause").addEventListener("click", () => {
  paused = !paused;
  $("btn-pause").setAttribute("aria-pressed", String(paused));
  $("btn-pause").textContent = paused ? "Riprendi" : "Pausa";
  showBanner();
});
$("btn-full").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else if ($("stage").requestFullscreen) $("stage").requestFullscreen();
});

function boxLabel(b) {
  // The Python label is "#id role score [N km/h] [child+slow]": keep speed and flags, in Italian.
  const speed = /(\d+) km\/h/.exec(b.label);
  const flags = /km\/h (\S+)$/.exec(b.label);
  const words = { child: "bambino", slow: "lento", wheelchair: "carrozzina", walking_aid: "deambulatore", stroller: "passeggino" };
  return [`${ROLE_ONE[b.role] || b.role} #${b.id}`, speed ? `${speed[1]} km/h` : "",
          flags ? flags[1].split("+").map((f) => words[f] || f).join(", ") : ""].filter(Boolean).join(", ");
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
    const label = boxLabel(b);
    const tw = ctx.measureText(label).width + 8;
    const top = b.y1 - font - 6 >= 0 ? b.y1 - font - 6 : b.y1;
    ctx.fillStyle = color;
    ctx.fillRect(b.x1, top, tw, font + 6);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, b.x1 + 4, top + 3);
  }
}

function drawScene(scene, font) {
  for (const z of scene.zones || []) {
    if (z.points.length < 3) continue;
    ctx.beginPath();
    z.points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = z.name === "crosswalk" ? "rgba(255, 255, 255, 0.12)" : "rgba(31, 95, 174, 0.15)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  for (const l of scene.lines || []) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.setLineDash([10, 6]);
    ctx.beginPath();
    ctx.moveTo(l.a[0], l.a[1]);
    ctx.lineTo(l.b[0], l.b[1]);
    ctx.stroke();
    ctx.setLineDash([]);
    const mx = (l.a[0] + l.b[0]) / 2, my = (l.a[1] + l.b[1]) / 2;
    const tx = mx + l.in[0] * 26, ty = my + l.in[1] * 26;
    ctx.beginPath();
    ctx.moveTo(mx, my);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.fillText(`IN ${l.name === "ped" ? "pedoni" : l.name === "veh" ? "veicoli" : l.name}`, tx + 4, ty - font / 2);
  }
}

function showBanner() {
  const stale = visionSeen && Date.now() - visionSeen > STALE_MS;
  const text = paused ? "In pausa: l'immagine è ferma, i numeri continuano ad aggiornarsi."
    : stale ? "Nessuna immagine dalla visione: si sta riavviando o la camera non risponde. Guarda la scheda Stato." : "";
  $("banner").hidden = !text;
  $("banner").textContent = text;
}

// ---------- helpers ----------
function sentence(text) {
  // Python details are lower-case fragments: start with a capital and end with a full stop.
  const t = String(text || "").trim();
  if (!t) return "";
  return t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".");
}
function num(v) { return String(v).replace(".", ","); }
function fitLcd(text) {
  const t = text.padEnd(32, " ").slice(0, 32);   // the LCD has 2 rows of 16 characters
  return t.slice(0, 16) + "\n" + t.slice(16);
}
function duration(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
function clock(ts) { return new Date(ts * 1000).toLocaleTimeString("it-IT"); }
function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

setInterval(() => { showStatus(); showBanner(); }, 1000);
