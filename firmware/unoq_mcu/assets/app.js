// MDGB live view: the Python side (python/vision.py) sends a "vision" message a few times a second with the
// frame as JPEG (field jpg, base64) and the boxes of the tracks in frame pixels. Boxes are drawn here.

const GROUP_COLORS = {
  person: "#50c850",      // pedestrians
  two_wheeler: "#ffc800", // cyclists, motorcyclists
  vehicle: "#00a0ff",     // cars, buses, trucks
  animal: "#c850c8",
  pending: "#969696",     // track not yet valid (younger than min_track_age)
};
const STATE_COLORS = {
  IDLE: "#5a5a5a", PRESENCE: "#c8c8c8", WARN_DRIVER: "#ffaa00", WARN_PEDESTRIAN: "#ff3030",
  ANIMAL_WARN: "#ffaa00", ANIMAL_ALERT: "#ff6400", DEGRADED: "#ffff00",
};

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const $ = (id) => document.getElementById(id);
const image = new Image();
let pending = null;      // last message whose image is being decoded
let lastSeen = 0;

const ui = new WebUI();
ui.on_connect(() => setLink(true));
ui.on_disconnect(() => setLink(false));
ui.on_message("config", (cfg) => { $("noimage").hidden = cfg.live; });
ui.on_message("vision", onVision);

function setLink(on) {
  $("link").textContent = on ? "collegato" : "non collegato";
  $("link").className = "pill " + (on ? "on" : "off");
}

function onVision(msg) {
  lastSeen = Date.now();
  showStatus(msg);
  if (!msg.w) return;                 // no frame (camera missing): status only
  if (msg.jpg) {
    pending = msg;
    image.onload = () => { if (pending === msg) draw(msg, image); };
    image.src = "data:image/jpeg;base64," + msg.jpg;
  } else {
    draw(msg, null);
  }
}

function draw(msg, img) {
  if (canvas.width !== msg.w || canvas.height !== msg.h) {
    canvas.width = msg.w;
    canvas.height = msg.h;
  }
  if (img) {
    ctx.drawImage(img, 0, 0, msg.w, msg.h);
  } else {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, msg.w, msg.h);
  }
  const font = Math.max(12, Math.round(msg.w / 50));
  ctx.font = `${font}px system-ui, sans-serif`;
  ctx.textBaseline = "top";
  for (const b of msg.boxes) {
    const color = GROUP_COLORS[b.group] || GROUP_COLORS.animal;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(2, msg.w / 320);
    ctx.strokeRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1);
    const tw = ctx.measureText(b.label).width + 8;
    const top = Math.max(0, b.y1 - font - 6);
    ctx.fillStyle = color;
    ctx.fillRect(b.x1, top, tw, font + 6);
    ctx.fillStyle = "#000";
    ctx.fillText(b.label, b.x1 + 4, top + 3);
  }
}

function showStatus(msg) {
  const state = $("state");
  state.textContent = msg.state + (msg.failsafe ? "  (fail-safe)" : "");
  state.style.background = STATE_COLORS[msg.state] || "#333";
  $("reason").textContent = msg.reason || "";
  $("led").textContent = msg.led || "—";
  const req = msg.req || {};
  $("green").textContent = msg.green_s != null ? `${msg.green_s} s (+${req.ped_green_extend_s || 0} s)` : "—";
  $("req").textContent = `rosso trattenuto ${req.veh_red_hold ? "sì" : "no"}, rosso subito ${req.veh_red_now ? "sì" : "no"}`;
  $("texts").textContent = `[${msg.lcd || ""}] / [${msg.oled || ""}]`;
  $("fps").textContent = msg.fps != null ? msg.fps.toFixed(1) : "—";
  $("lat").textContent = msg.lat_ms
    ? Object.entries(msg.lat_ms).map(([k, v]) => `${k} ${v == null ? "-" : v}`).join("  ")
    : "—";
  const people = msg.boxes.filter((b) => b.group === "person").length;
  $("tracks").textContent = `${msg.boxes.length} (persone ${people})`;
  $("counts").textContent = msg.counts || "—";
  $("events").textContent = msg.events || "—";
}

// No message for 3 s while connected: the vision is restarting or the camera is missing.
setInterval(() => {
  if (lastSeen && Date.now() - lastSeen > 3000) {
    $("state").textContent = "nessun dato dalla visione";
    $("state").style.background = STATE_COLORS.DEGRADED;
  }
}, 1000);
