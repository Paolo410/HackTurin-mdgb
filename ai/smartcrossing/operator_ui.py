"""The technician's page served by status_page.py: one HTML file with its style, script and logo inside.

Everything is in this string so the board needs no other file (push_to_arduino.sh copies the package as it is) and
the page works without Internet. The logo is the MDGB placeholder of docs/brand/ (genera_logo.py): same drawing.
Three moments: locked (pass the badge), login (user and password within operator.login_s), open (Stato, Vista,
Registro). The data comes from status.json every second; images only from stream.mjpg, only while the Vista tab is
open, so the vision draws frames only while someone is really looking.
"""

# Same drawing as docs/brand/mdgb-simbolo.svg: the M made of crossing stripes, the amber beacon in its notch.
LOGO = (
    '<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><clipPath id="lg-b">'
    '<rect y="13" width="64" height="6"/><rect y="21.25" width="64" height="6"/><rect y="29.5" width="64" height="6"/>'
    '<rect y="37.75" width="64" height="6"/><rect y="46" width="64" height="6"/></clipPath>'
    '<radialGradient id="lg-g" cx="32" cy="20.5" r="15" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#f2a900" stop-opacity=".55"/><stop offset="1" stop-color="#f2a900" stop-opacity="0"/>'
    '</radialGradient></defs><rect width="64" height="64" rx="15" fill="#1d2226"/>'
    '<circle cx="32" cy="20.5" r="15" fill="url(#lg-g)"/>'
    '<polygon points="10,52 10,13 19.5,13 32,31 44.5,13 54,13 54,52 45,52 45,29 32,47.5 19,29 19,52" fill="#f3f4f1" '
    'clip-path="url(#lg-b)"/><circle cx="32" cy="20.5" r="4.4" fill="#f2a900"/></svg>')

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' "
           "height='64' rx='15' fill='%231d2226'/%3E%3Cpolygon points='10,52 10,13 19.5,13 32,31 44.5,13 54,13 54,52 45,52 "
           "45,29 32,47.5 19,29 19,52' fill='%23f3f4f1'/%3E%3Ccircle cx='32' cy='20.5' r='4.4' fill='%23f2a900'/%3E%3C/svg%3E")

_PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MDGB, pagina del tecnico</title><link rel="icon" href="__FAVICON__">
<style>
/* Colours of the road, light by default (read outdoors), dark when the device asks for it; system fonts. */
:root{--paper:#f3f4f1;--surface:#fff;--ink:#1d2226;--muted:#59636b;--line:#d6dad5;--green:#17803f;--amber:#b36b00;
--red:#c4302b;--blue:#1f5fae;--lamp:#f2a900;--tint-red:#fbeceb;--wait:#8a9399;--bar:#1d2226;--radius:8px}
@media (prefers-color-scheme:dark){:root{--paper:#1a1e22;--surface:#23282d;--ink:#eceeea;--muted:#a2abb2;--line:#353c42;
--green:#4cc27a;--amber:#f2b33d;--red:#ff6b61;--blue:#6aa5ef;--tint-red:#3a2524;--bar:#101316}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--paper);color:var(--ink);font:400 .95rem/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
-webkit-text-size-adjust:100%}
h1,h2,h3,p{margin:0}h2{font-size:1.1rem;font-weight:650;margin-bottom:.6rem}.muted{color:var(--muted)}.small{font-size:.85rem}
:focus-visible{outline:3px solid var(--blue);outline-offset:2px}[hidden]{display:none!important}
.logo{display:block;width:100%;height:100%}
.button{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;padding:.55rem .95rem;min-height:2.6rem;
border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);color:var(--ink);font:inherit;font-weight:600;
cursor:pointer;text-decoration:none}.button:hover{border-color:var(--ink)}
.button.primary{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.button.ghost{background:transparent;border-color:rgba(243,244,241,.35);color:#f3f4f1}

/* ---------- locked and login ---------- */
.gate{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:2rem 1rem 3rem;
background:radial-gradient(60rem 30rem at 50% -10%,rgba(242,169,0,.16),transparent 60%),var(--paper)}
.brandmark{display:flex;align-items:center;gap:.9rem;margin-bottom:1.6rem}.brandmark .mk{width:3.6rem;height:3.6rem}
.brandmark strong{display:block;font-size:1.7rem;font-weight:800;letter-spacing:.14em;line-height:1}
.brandmark span{display:block;color:var(--muted);font-size:.85rem;margin-top:.3rem}
.gatecard{width:100%;max-width:25rem;background:var(--surface);border-radius:14px;padding:1.6rem;
box-shadow:0 1px 2px rgba(0,0,0,.06),0 12px 32px -16px rgba(0,0,0,.25)}
.gatecard h1{font-size:1.45rem;line-height:1.25;margin-bottom:.35rem}.gatecard>p{color:var(--muted)}
.steps{list-style:none;margin:1.3rem 0 0;padding:0;display:grid;gap:.6rem}
.steps li{display:grid;grid-template-columns:2rem 1fr;gap:.7rem;align-items:center;color:var(--muted)}
.steps i{width:2rem;height:2rem;border-radius:50%;display:grid;place-items:center;font-style:normal;font-weight:700;
border:2px solid var(--line);font-size:.9rem}
.steps li.now{color:var(--ink);font-weight:600}.steps li.now i{border-color:var(--lamp);background:var(--lamp);color:#1d2226}
.steps li.done i{border-color:var(--green);background:var(--green);color:#fff}
.reader{display:flex;justify-content:center;margin:1.4rem 0 .3rem}.reader svg{width:7.5rem;height:auto}
.wave{fill:none;stroke:var(--lamp);stroke-width:3;stroke-linecap:round}
@media (prefers-reduced-motion:no-preference){.wave{animation:pulse 1.8s ease-in-out infinite}.wave.w2{animation-delay:.3s}
.wave.w3{animation-delay:.6s}@keyframes pulse{0%,100%{opacity:.15}50%{opacity:1}}}
.timer{display:flex;align-items:center;gap:.8rem;margin:1.2rem 0 1rem;padding:.7rem .9rem;border-radius:var(--radius);background:var(--paper)}
.timer svg{width:3rem;height:3rem;flex:none;transform:rotate(-90deg)}
.timer .track{fill:none;stroke:var(--line);stroke-width:6}.timer .left{fill:none;stroke:var(--lamp);stroke-width:6;stroke-linecap:round}
.timer b{display:block;font-size:1.25rem;font-variant-numeric:tabular-nums}
form label{display:block;font-weight:600;font-size:.9rem;margin:.8rem 0 .3rem}
form input{display:block;width:100%;font:inherit;padding:.7rem .85rem;border:1px solid var(--line);border-radius:var(--radius);
background:var(--surface);color:var(--ink)}
.pw{position:relative}.pw input{padding-right:5.2rem}
.pw button{position:absolute;right:.35rem;top:50%;transform:translateY(-50%);min-height:2.1rem;padding:.3rem .7rem;font-size:.85rem}
form .button.primary{width:100%;margin-top:1.2rem;min-height:3rem;font-size:1rem}
.error{color:var(--red);font-weight:600;min-height:1.4rem;margin-top:.7rem}
.gatefoot{margin-top:1.4rem;max-width:25rem;text-align:center;color:var(--muted);font-size:.8rem}

/* ---------- open ---------- */
.bar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem 1rem;background:var(--bar);color:#f3f4f1;
padding:.7rem max(1rem,calc((100% - 1120px)/2 + 1rem))}
.brand{display:flex;align-items:center;gap:.7rem;white-space:nowrap}.brand .mk{width:2.2rem;height:2.2rem}
.brand strong{display:block;letter-spacing:.1em}.brand span{font-size:.82rem;opacity:.8}
.right{display:flex;align-items:center;gap:.9rem}
.conn{font-size:.85rem;white-space:nowrap}.conn::before{content:"";display:inline-block;width:.6em;height:.6em;border-radius:50%;
margin-right:.45em;background:var(--wait)}.conn.on::before{background:#3fbf6a}.conn.off::before{background:#e5483f}
.tabs{position:sticky;top:0;z-index:5;display:flex;gap:.25rem;background:var(--surface);border-bottom:1px solid var(--line);
overflow-x:auto;padding:0 max(1rem,calc((100% - 1120px)/2 + 1rem))}
.tabs a{padding:.85rem .9rem .7rem;color:var(--muted);text-decoration:none;font-weight:600;border-bottom:3px solid transparent;white-space:nowrap}
.tabs a[aria-selected=true]{color:var(--ink);border-bottom-color:var(--ink)}
.count{display:inline-block;min-width:1.4em;padding:0 .4em;margin-left:.3em;border-radius:999px;background:var(--red);color:#fff;
font-size:.75rem;text-align:center}.count.warn{background:var(--amber)}
main{max-width:1120px;margin:0 auto;padding:1.25rem 1rem 3rem}
.status{padding:1.1rem 1.25rem;border-left:8px solid var(--wait);background:var(--surface);border-radius:var(--radius);margin-bottom:1.5rem}
.status h1{font-size:1.9rem;line-height:1.15;font-weight:700}.status p{margin-top:.35rem;color:var(--muted);max-width:62ch}
.status.ok{border-left-color:var(--green)}.status.ok h1{color:var(--green)}
.status.warn{border-left-color:var(--lamp)}.status.warn h1{color:var(--amber)}
.status.fault{border-left-color:var(--red);background:var(--tint-red)}.status.fault h1{color:var(--red)}
.split{display:grid;gap:1.5rem;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);align-items:start}
@media (max-width:820px){.split{grid-template-columns:minmax(0,1fr)}}
.group{margin-bottom:1.75rem}
.parts{list-style:none;margin:0;padding:0}
.part{display:grid;grid-template-columns:auto 1fr auto;gap:.15rem .6rem;align-items:baseline}
.parts.big .part{padding:.85rem 1rem;margin-bottom:.6rem;background:var(--surface);border-radius:var(--radius);border-left:5px solid var(--red)}
.parts.big .part.warn{border-left-color:var(--lamp)}
.parts.list{background:var(--surface);border-radius:var(--radius)}
.parts.list .part{padding:.6rem 1rem;border-top:1px solid var(--line)}.parts.list .part:first-child{border-top:0}
.dot{width:.7rem;height:.7rem;border-radius:50%;background:var(--wait);align-self:center}
.part.ok .dot{background:var(--green)}.part.warn .dot{background:var(--lamp)}.part.fault .dot{background:var(--red)}
.part.untested .dot{background:transparent;border:2px solid var(--blue)}
.pname{font-weight:600}.pval{color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.pword{font-weight:650;font-size:.9rem}.part.fault .pword{color:var(--red)}.part.warn .pword{color:var(--amber)}
.part.untested .pword,.part.waiting .pword{color:var(--muted);font-weight:500}
.pmore{grid-column:2/-1;color:var(--muted)}.pfix{grid-column:2/-1;margin-top:.35rem}.pfix b{display:block;font-size:.85rem}
@media (max-width:560px){.parts.list .part{grid-template-columns:auto 1fr}.parts.list .pval{grid-column:2;text-align:left}}
.rule{padding:1rem 1.1rem;background:var(--surface);border-radius:var(--radius);border-left:6px solid var(--wait)}
.rule.ok{border-left-color:var(--green)}.rule.warn{border-left-color:var(--lamp)}.rule.fault{border-left-color:var(--red)}
.rule h3{font-size:1.35rem;line-height:1.2}.rule .code{margin-left:.4rem;font-size:.75rem;color:var(--muted);font-weight:600;letter-spacing:.04em}
.rule p{color:var(--muted);margin-top:.3rem}
.facts{display:grid;grid-template-columns:1fr auto;gap:.35rem 1rem;margin:.8rem 0 0}
.facts dt{color:var(--muted)}.facts dd{margin:0;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
details.box{background:var(--surface);border-radius:var(--radius);padding:.8rem 1rem}details.box summary{cursor:pointer;font-weight:650}
.note{margin-top:1rem;padding:.8rem 1rem;border-radius:var(--radius);background:var(--surface);color:var(--muted);font-size:.88rem}
.stage{background:#000;border-radius:var(--radius);overflow:hidden;min-height:4rem;display:grid;place-items:center;color:#a2abb2}
.stage img{display:block;width:100%;height:auto}.stage p{padding:2rem 1rem;text-align:center}
.vbtns{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.5rem;margin:.7rem 0 .4rem}
@media (max-width:560px){.vbtns{grid-template-columns:repeat(2,minmax(0,1fr))}}
table.counts{width:100%;border-collapse:collapse;background:var(--surface);border-radius:var(--radius);overflow:hidden;margin-bottom:1rem}
.counts th,.counts td{padding:.55rem 1rem;text-align:right;border-top:1px solid var(--line);font-variant-numeric:tabular-nums}
.counts thead th{border-top:0;color:var(--muted);font-weight:600;font-size:.85rem}.counts th:first-child,.counts td:first-child{text-align:left}
.counts td:not(:first-child){font-size:1.1rem;font-weight:650}
.warnline{color:var(--amber);font-weight:600;margin-bottom:.8rem}
.filter{display:flex;gap:.4rem;flex-wrap:wrap}.chip{padding:.4rem .8rem;min-height:2.3rem;border:1px solid var(--line);border-radius:999px;
background:var(--surface);color:var(--ink);font:inherit;cursor:pointer}.chip b{font-weight:600;color:var(--muted);margin-left:.2em}
.chip.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}.chip.on b{color:inherit}
.head{display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem}
.log{list-style:none;margin:0 0 .8rem;padding:0;background:var(--surface);border-radius:var(--radius)}
.log li{display:grid;grid-template-columns:4.6rem 7rem 1fr;gap:.75rem;padding:.6rem 1rem;border-top:1px solid var(--line)}
.log li:first-child{border-top:0}.log li.empty{display:block;color:var(--muted)}.log time{color:var(--muted);font-variant-numeric:tabular-nums}
.kind{font-weight:650;font-size:.9rem}.kind.diag{color:var(--amber)}.kind.good,.kind.crossing{color:var(--green)}
.kind.alarm,.kind.near_miss,.kind.incident{color:var(--red)}.kind.state,.kind.link{color:var(--blue)}.kind.rfid{color:#7a4cc2}
@media (max-width:560px){.log li{grid-template-columns:4.2rem 1fr}.log li>span:last-child{grid-column:1/-1}}
</style></head><body>

<!-- 1. Locked: nothing is shown until the badge -->
<section class="gate" id="locked" hidden>
  <div class="brandmark"><span class="mk">__LOGO__</span><div><strong>MDGB</strong><span>Mobility Data &amp; Guardian Beacon</span></div></div>
  <div class="gatecard">
    <h1>Pagina del tecnico</h1>
    <p>Per entrare servono il badge e le credenziali del tecnico.</p>
    <div class="reader" aria-hidden="true"><svg viewBox="0 0 120 90">
      <rect x="8" y="22" width="56" height="38" rx="6" fill="var(--ink)"/><rect x="15" y="30" width="16" height="12" rx="2" fill="var(--lamp)"/>
      <rect x="15" y="48" width="36" height="4" rx="2" fill="var(--paper)" opacity=".6"/>
      <path class="wave w1" d="M76 33a14 14 0 0 1 0 22"/><path class="wave w2" d="M86 26a24 24 0 0 1 0 36"/>
      <path class="wave w3" d="M96 19a34 34 0 0 1 0 50"/></svg></div>
    <ol class="steps">
      <li class="now"><i>1</i>Avvicina il badge al lettore sul palo</li>
      <li><i>2</i>Entra con utente e password</li>
    </ol>
  </div>
  <p class="gatefoot">La pagina si aggiorna da sola quando il lettore riconosce il badge.</p>
</section>

<!-- 2. Badge read: log in within operator.login_s -->
<section class="gate" id="login" hidden>
  <div class="brandmark"><span class="mk">__LOGO__</span><div><strong>MDGB</strong><span>Mobility Data &amp; Guardian Beacon</span></div></div>
  <div class="gatecard">
    <h1>Badge riconosciuto</h1>
    <ol class="steps">
      <li class="done"><i>&#10003;</i>Badge letto</li>
      <li class="now"><i>2</i>Entra con utente e password</li>
    </ol>
    <div class="timer"><svg viewBox="0 0 60 60"><circle class="track" cx="30" cy="30" r="26"/>
      <circle class="left" id="ring" cx="30" cy="30" r="26" stroke-dasharray="163.4" stroke-dashoffset="0"/></svg>
      <div><b id="login_left">2:00</b><span class="muted small">per entrare, poi serve di nuovo il badge</span></div></div>
    <form id="form">
      <label for="user">Utente</label><input id="user" autocomplete="username" autocapitalize="none" spellcheck="false" required>
      <label for="password">Password</label>
      <div class="pw"><input id="password" type="password" autocomplete="current-password" required>
        <button type="button" class="button" id="showpw" aria-pressed="false">Mostra</button></div>
      <button class="button primary" type="submit">Entra</button>
      <p class="error" id="error" role="alert"></p>
    </form>
  </div>
  <p class="gatefoot">Collegamento non cifrato sulla rete locale: usa una password solo per questa scheda.</p>
</section>

<!-- 3. Open -->
<div id="open" hidden>
<header class="bar"><div class="brand"><span class="mk">__LOGO__</span><div><strong>MDGB</strong><span>Pagina del tecnico</span></div></div>
  <div class="right"><span id="conn" class="conn" role="status">Collegamento&hellip;</span>
  <button class="button ghost" id="logout" type="button">Esci</button></div></header>
<nav class="tabs" role="tablist" aria-label="Sezioni">
  <a href="#stato" role="tab" data-view="stato">Stato <span class="count" id="count" hidden></span></a>
  <a href="#vista" role="tab" data-view="vista">Vista dal vivo</a>
  <a href="#registro" role="tab" data-view="registro">Registro</a>
</nav>
<main>
  <section id="view-stato">
    <div class="status" id="status"><h1 id="status-title">Controllo in corso</h1><p id="status-text"></p></div>
    <div class="split"><div>
      <section class="group" id="g-problems" hidden><h2>Da sistemare</h2><ul class="parts big" id="problems"></ul></section>
      <section class="group" id="g-ok" hidden><h2 id="ok-title">Funzionano</h2><ul class="parts list" id="oks"></ul></section>
      <section class="group" id="g-other" hidden><h2>In attesa o da provare</h2><ul class="parts list" id="others"></ul></section>
    </div><aside>
      <section class="group"><h2>Semaforo</h2>
        <div class="rule" id="rule"><h3><span id="state">&ndash;</span><span class="code" id="code"></span></h3><p id="reason"></p>
        <dl class="facts"><dt>Lampada richiesta</dt><dd id="led">&ndash;</dd><dt>Verde pedonale</dt><dd id="green">&ndash;</dd>
        <dt>Sketch</dt><dd id="sketch">&ndash;</dd></dl></div></section>
      <details class="box"><summary>Dettagli della visione</summary><dl class="facts">
        <dt>Fotogrammi al secondo</dt><dd id="fps">&ndash;</dd><dt>Tempi per fase</dt><dd id="lat">&ndash;</dd>
        <dt>Tracce valide</dt><dd id="tracks">&ndash;</dd><dt>Sorgente</dt><dd id="source">&ndash;</dd>
        <dt>Calibrazione</dt><dd id="calib">&ndash;</dd><dt>Acceso da</dt><dd id="uptime">&ndash;</dd></dl></details>
      <p class="note" id="session"></p>
    </aside></div>
  </section>

  <section id="view-vista" hidden>
    <div class="split"><div>
      <section class="group"><h2>Vista dal vivo</h2><div class="stage" id="live"></div>
        <div id="video" hidden><div class="vbtns">
          <button class="button" data-a="prev">Video prima</button><button class="button" data-a="back">Indietro</button>
          <button class="button" data-a="fwd">Avanti</button><button class="button" data-a="next">Video dopo</button></div>
          <p class="muted small" id="vname"></p></div>
        <p class="muted small" id="images"></p></section>
    </div><aside>
      <section class="group"><h2>Passaggi contati</h2><p class="warnline" id="notsent" hidden>Non inviati alla centrale:
        manca la calibrazione di questa inquadratura.</p>
        <table class="counts"><thead><tr><th scope="col">Chi</th><th scope="col">IN</th><th scope="col">OUT</th></tr></thead>
        <tbody id="counts"></tbody></table>
        <dl class="facts"><dt>Veicoli che rallentano per i pedoni</dt><dd id="yield">&ndash;</dd><dt>Quasi incidenti</dt><dd id="near">0</dd>
        <dt>Incidenti</dt><dd id="incidents">0</dd></dl>
        <p class="muted small" style="margin-top:.8rem">Da quando è partita la visione o il video.</p></section>
    </aside></div>
  </section>

  <section id="view-registro" hidden>
    <div class="head"><div class="filter" role="group" aria-label="Mostra">
      <button type="button" class="chip on" data-log="all">Tutto <b data-n="all">0</b></button>
      <button type="button" class="chip" data-log="diag">Parti del nodo <b data-n="diag">0</b></button>
      <button type="button" class="chip" data-log="traffic">Traffico <b data-n="traffic">0</b></button>
      <button type="button" class="chip" data-log="security">Sicurezza <b data-n="security">0</b></button></div>
      <div class="filter"><button class="button" id="download" type="button">Scarica</button>
      <button class="button" id="clear" type="button">Svuota</button></div></div>
    <ol class="log" id="log"><li class="empty">Ancora nessun evento.</li></ol>
    <p class="muted small">Ultimi 100 eventi, solo in memoria sulla scheda. "Scarica" salva un file di testo sul tuo telefono.</p>
  </section>
</main>
</div>

<script>
const $ = id => document.getElementById(id);
const STATES = {IDLE: ["Strada libera", "ok"], PRESENCE: ["Pedone presente", "ok"], WARN_DRIVER: ["Avviso ai conducenti", "warn"],
  WARN_PEDESTRIAN: ["Avviso ai pedoni", "warn"], ANIMAL_WARN: ["Animale vicino", "warn"], ANIMAL_ALERT: ["Animale in strada", "warn"],
  DEGRADED: ["Visione non affidabile", "fault"]};
const WORDS = {ok: "Funziona", warn: "Da controllare", fault: "Non funziona", waiting: "In attesa", untested: "Da provare"};
const KINDS = {diag: "Parti", crossing: "Passaggio", state: "Semaforo", alarm: "Allarme", rfid: "Accesso", link: "Sketch",
  near_miss: "Quasi incidente", incident: "Incidente"};
const ROLES = {pedestrian: ["Pedone", "Pedoni"], cyclist: ["Ciclista", "Ciclisti"], motorcyclist: ["Motociclista", "Motociclisti"],
  car: ["Auto", "Auto"], bus: ["Autobus", "Autobus"], truck: ["Camion", "Camion"], animal: ["Animale", "Animali"], bird: ["Uccello", "Uccelli"]};
const FILTERS = {all: () => true, diag: e => e.type === "diag", security: e => ["alarm", "rfid", "link"].includes(e.type),
  traffic: e => !["diag", "alarm", "rfid", "link"].includes(e.type)};
let view = "", last = null, logFilter = "all", logKey = "", clearedBefore = 0;

const esc = t => String(t ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const sentence = t => { t = String(t || "").trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") : ""; };
const mmss = x => { x = Math.max(0, Math.round(x || 0)); return Math.floor(x / 60) + ":" + String(x % 60).padStart(2, "0"); };
const dur = s => { s = Math.round(s || 0); return s < 60 ? s + " s" : s < 3600 ? Math.floor(s / 60) + " min" : Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min"; };
const num = v => String(v).replace(".", ",");

function show(which) {
  for (const id of ["locked", "login", "open"]) $(id).hidden = id !== which;
  if (which !== "open") setLive(false);
  if (which === "login" && view !== "login") setTimeout(() => $("user").focus(), 50);
  view = which;
}

// ---------- tabs of the open page (in the address: a reload stays on the same tab) ----------
function tab() { const t = location.hash.slice(1); return ["stato", "vista", "registro"].includes(t) ? t : "stato"; }
function showTab() {
  const t = tab();
  for (const v of ["stato", "vista", "registro"]) $("view-" + v).hidden = v !== t;
  document.querySelectorAll(".tabs a").forEach(a => a.setAttribute("aria-selected", String(a.dataset.view === t)));
  setLive(t === "vista" && last && last.images);
}
addEventListener("hashchange", showTab);

// The stream is open only while the Vista tab is visible: the vision draws frames only for someone watching.
function setLive(on) {
  const has = !!$("view-img");
  if (on && !has) $("live").innerHTML = "<img id='view-img' src='stream.mjpg' alt='Vista dal vivo con i riquadri'>";
  if (!on && has) $("live").innerHTML = last && !last.images ? "<p>Immagini disattivate sulla scheda: solo i numeri.</p>" : "";
}

// ---------- every second ----------
async function tick() {
  let r;
  try { r = await fetch("status.json", {cache: "no-store"}); }
  catch (err) { $("conn").textContent = "Scheda non raggiungibile"; $("conn").className = "conn off"; return; }
  if (r.status === 401) {
    const b = await r.json(), left = b.login_s_left || 0, total = b.login_s || 120;
    $("login_left").textContent = mmss(left);
    $("ring").style.strokeDashoffset = String(163.4 * (1 - Math.min(1, left / total)));
    return show("login");
  }
  if (r.status !== 200) return show("locked");
  last = await r.json();
  if (view !== "open") { show("open"); showTab(); }
  $("conn").textContent = "Collegato"; $("conn").className = "conn on";
  render(last);
}

function render(s) {
  renderHealth(s.health || {});
  const st = STATES[s.state] || [s.state || "–", "warn"];
  $("state").textContent = st[0]; $("code").textContent = s.state || ""; $("rule").className = "rule " + st[1];
  $("reason").textContent = sentence(s.reason);
  $("led").textContent = s.led || "–"; $("green").textContent = s.green_s != null ? s.green_s + " s" : "–";
  $("sketch").textContent = s.link_failsafe ? "ciclo normale (fail-safe)" : "comandato dalla visione";
  const l = s.lat_ms || {};
  $("fps").textContent = s.fps != null ? num(s.fps) : "–";
  $("lat").textContent = ["detect", "track", "rules"].map(k => (l[k] ?? "–")).join(" / ") + " ms";
  $("tracks").textContent = s.tracks ?? "–"; $("source").textContent = s.source || "–"; $("calib").textContent = s.calib || "–";
  $("uptime").textContent = dur(s.uptime_s);
  $("session").textContent = (s.session_s_left == null ? "Sessione aperta finché non premi Esci." :
    "La sessione si chiude fra " + Math.ceil(s.session_s_left / 60) + " min.") + " Il cicalino resta muto finché non esci.";
  // Vista
  const v = s.video;
  $("video").hidden = !v;
  if (v) $("vname").textContent = `Video ${v.index} di ${v.total}: ${v.name}, ${mmss(v.pos_s)} su ${mmss(v.dur_s)}, ` +
    (v.calib ? "calibrazione " + v.calib : "senza calibrazione") + `, salto di ${v.seek_s} s.`;
  $("images").textContent = s.images ? "Vista dal vivo, mai registrata." : "Immagini disattivate sulla scheda (operator.share_images).";
  if (tab() === "vista") setLive(s.images);
  renderCounts(s);
  renderLog(s.log || []);
}

function renderHealth(h) {
  const checks = h.checks || [], sum = h.summary;
  const problems = checks.filter(c => c.status === "fault").concat(checks.filter(c => c.status === "warn"));
  let level = "waiting", title = "Controllo in corso", text = "Le parti del nodo hanno qualche secondo per mandare il primo dato.";
  if (sum && sum.overall !== "waiting") {
    level = sum.overall; const n = problems.length;
    if (level === "ok") { title = "Tutto funziona"; text = `${sum.ok} parti su ${sum.total} a posto.` + (sum.untested ? " Badge e antifurto si provano dal vivo." : ""); }
    else if (level === "warn") { title = n === 1 ? "Una cosa da controllare" : `${n} cose da controllare`; text = "Il semaforo funziona. Trovi cosa fare qui sotto."; }
    else { title = n === 1 ? "Una cosa da sistemare" : `${n} cose da sistemare`; text = "Il semaforo continua comunque il suo ciclo. Trovi cosa fare qui sotto."; }
  }
  $("status").className = "status " + level; $("status-title").textContent = title; $("status-text").textContent = text;
  const c = $("count"); c.hidden = !problems.length; c.textContent = problems.length;
  c.className = "count" + (sum && !sum.fault ? " warn" : "");
  const oks = checks.filter(x => x.status === "ok"), others = checks.filter(x => x.status === "waiting" || x.status === "untested");
  $("g-problems").hidden = !problems.length;
  $("problems").innerHTML = problems.map(x => `<li class="part ${x.status}"><span class="dot"></span><span class="pname">${esc(x.name)}</span>
    <span class="pword">${WORDS[x.status]}</span><p class="pmore">${esc(sentence(x.detail))} ${esc(sentence(x.where))}</p>
    ${x.hint ? `<p class="pfix"><b>Cosa fare</b>${esc(x.hint)}</p>` : ""}</li>`).join("");
  $("g-ok").hidden = !oks.length;
  $("ok-title").textContent = oks.length === checks.length ? "Tutte le parti funzionano" : `Funzionano (${oks.length})`;
  $("oks").innerHTML = oks.map(x => `<li class="part ok" title="${esc(sentence(x.detail))}"><span class="dot"></span>
    <span class="pname">${esc(x.name)}</span><span class="pval">${esc(x.shown)}</span></li>`).join("");
  $("g-other").hidden = !others.length;
  $("others").innerHTML = others.map(x => `<li class="part ${x.status}"><span class="dot"></span><span class="pname">${esc(x.name)}</span>
    <span class="pword">${WORDS[x.status]}</span><p class="pmore">${esc(sentence(x.detail))}</p></li>`).join("");
}

function renderCounts(s) {
  const roles = {};
  for (const line of Object.values(s.lines || {})) for (const [r, c] of Object.entries(line.roles || {})) {
    roles[r] = roles[r] || {in: 0, out: 0}; roles[r].in += c.in; roles[r].out += c.out;
  }
  const rows = Object.entries(roles).filter(([, c]) => c.in || c.out);
  $("counts").innerHTML = rows.length ? rows.map(([r, c]) => `<tr><td>${esc((ROLES[r] || [r, r])[1])}</td><td>${c.in}</td><td>${c.out}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">${s.lines && Object.keys(s.lines).length ? "Nessun passaggio finora." : "Nessuna linea di conteggio."}</td></tr>`;
  $("notsent").hidden = s.counts_sent !== false;
  const st = s.stats || {};
  $("yield").textContent = st.yield_rate == null ? "nessun caso" : Math.round(st.yield_rate * 100) + "%";
  $("near").textContent = st.near_miss ?? 0; $("incidents").textContent = st.incidents ?? 0;
}

// ---------- Registro ----------
function entries() { return ((last && last.log) || []).filter(e => e.ts > clearedBefore); }
function good(e) { return e.type === "diag" && (/di nuovo a posto|provato: funziona/.test(e.text) || (e.text.startsWith("controllo iniziale") && !e.text.includes("da guardare"))); }
function fields(t) { return Object.fromEntries(t.split(" ").map(p => p.split("=")).filter(p => p.length === 2)); }
function text(e) {
  if (e.type === "crossing") {
    const m = /^(\\S+) #(\\d+) (IN|OUT) linea ([^\\s,]+)(.*)$/.exec(e.text);
    if (m) return `${(ROLES[m[1]] || [m[1]])[0]} #${m[2]} passato ${({ped: "sulle strisce", veh: "in corsia"})[m[4]] || "sulla linea " + m[4]}, verso ${m[3]}${m[5]}.`;
  }
  if (e.type === "state") { const [code, ...rest] = e.text.split(": "); return `${(STATES[code] || [code])[0]}: ${sentence(rest.join(": "))}`; }
  if (e.type === "near_miss") { const f = fields(e.text); return `Tra #${f.a} e #${f.b}` + (f.ttc_s && f.ttc_s !== "None" ? `, ${num(f.ttc_s)} s alla collisione.` : "."); }
  return sentence(e.text);
}
function renderLog(all) {
  const list = entries();
  document.querySelectorAll("[data-n]").forEach(b => b.textContent = list.filter(FILTERS[b.dataset.n]).length);
  const shown = list.filter(FILTERS[logFilter]).reverse();
  const key = logFilter + shown.length + (shown[0] ? shown[0].ts + shown[0].text : "");
  if (key === logKey) return; logKey = key;
  $("log").innerHTML = shown.length ? shown.map(e => `<li><time>${new Date(e.ts * 1000).toLocaleTimeString("it-IT")}</time>
    <span class="kind ${esc(e.type)}${good(e) ? " good" : ""}">${esc(KINDS[e.type] || e.type)}</span><span>${esc(text(e))}</span></li>`).join("")
    : `<li class="empty">${list.length ? "Nessun evento di questo tipo." : "Ancora nessun evento."}</li>`;
}
document.querySelectorAll("[data-log]").forEach(b => b.addEventListener("click", () => {
  logFilter = b.dataset.log; document.querySelectorAll("[data-log]").forEach(x => x.classList.toggle("on", x === b)); logKey = ""; renderLog();
}));
$("clear").addEventListener("click", () => { clearedBefore = Date.now() / 1000; logKey = ""; renderLog(); });
$("download").addEventListener("click", () => {
  const now = new Date(), h = (last && last.health) || {};
  const lines = [`MDGB, registro del nodo scaricato il ${now.toLocaleString("it-IT")}`, "", $("status-title").textContent + ". " + $("status-text").textContent, "", "PARTI DEL NODO"];
  for (const c of h.checks || []) { lines.push(`  ${WORDS[c.status].padEnd(15)} ${c.name}${c.shown ? ": " + c.shown : ""}. ${sentence(c.detail)}`); if (c.hint) lines.push(`  ${"".padEnd(15)} Cosa fare: ${c.hint}`); }
  lines.push("", "EVENTI");
  for (const e of entries()) lines.push(`  ${new Date(e.ts * 1000).toLocaleString("it-IT")}  ${(KINDS[e.type] || e.type).padEnd(16)} ${text(e)}`);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], {type: "text/plain;charset=utf-8"}));
  a.download = `mdgb-registro-${now.toISOString().slice(0, 16).replace(/[-:T]/g, "")}.txt`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// ---------- actions ----------
$("form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const body = new URLSearchParams({user: $("user").value, password: $("password").value});
  const r = await fetch("login", {method: "POST", body});
  $("password").value = "";
  $("error").textContent = r.status === 200 ? "" : r.status === 503 ? "Credenziali non configurate sulla scheda (scripts/operator_login.py)."
    : r.status === 403 ? "Troppi tentativi o tempo scaduto: ripassa il badge." : "Utente o password sbagliati.";
  tick();
});
$("showpw").addEventListener("click", () => {
  const on = $("password").type === "password";
  $("password").type = on ? "text" : "password"; $("showpw").textContent = on ? "Nascondi" : "Mostra";
  $("showpw").setAttribute("aria-pressed", String(on));
});
document.querySelectorAll(".vbtns button").forEach(b => b.addEventListener("click", async () => {
  await fetch("video", {method: "POST", body: new URLSearchParams({action: b.dataset.a})}); tick();
}));
$("logout").addEventListener("click", async () => { await fetch("logout", {method: "POST"}); setLive(false); tick(); });
tick(); setInterval(tick, 1000);
</script></body></html>
"""

def _with_logos(page: str) -> str:
    """Each copy of the logo gets its own ids: the copies in the hidden screens must not lend their clip and glow."""
    parts = page.split("__LOGO__")
    out = parts[0]
    for i, rest in enumerate(parts[1:], 1):
        out += LOGO.replace("lg-", f"lg{i}-") + rest
    return out


PAGE = _with_logos(_PAGE).replace("__FAVICON__", FAVICON)
