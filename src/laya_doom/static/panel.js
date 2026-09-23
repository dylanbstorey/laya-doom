// Decision panel. Frame and decision arrive in the same message, so the picture
// and the reasoning beside it can never drift out of step.

const $ = (id) => document.getElementById(id);
const canvas = $("screen");
const ctx = canvas.getContext("2d");

const LOW_CONFIDENCE = 0.15;   // below this the model is effectively guessing
const SPARK_SAMPLES = 60;
const LOG_LIMIT = 300;         // enough to scroll a whole episode, bounded so the DOM stays cheap
const latencies = [];
let budgetMs = 114;            // replaced by /api/status
let logged = 0;

const fmt = (value, digits = 0) =>
  value === null || value === undefined ? "—" : Number(value).toFixed(digits);

function drawFrame(base64) {
  if (!base64) return;
  const image = new Image();
  image.onload = () => ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  image.src = `data:image/jpeg;base64,${base64}`;
}

// Every decision, newest first. The answers panel above shows only the current
// one; this is the record of what the model has actually been doing.
function logDecision(message) {
  const fire = message.answers.find((a) => a.name === "fire");
  const turn = message.answers.find((a) => a.name === "turn");
  if (!fire && !turn) return;

  const row = document.createElement("div");
  row.className = message.sweeping ? "log-row fresh-sweep" : "log-row";

  const tick = document.createElement("span");
  tick.className = "log-tick";
  tick.textContent = `#${message.tick}`;

  const fireCell = document.createElement("span");
  const firing = fire ? fire.value >= 0.5 : false;
  fireCell.className = `log-fire ${firing ? "yes" : "no"}`;
  fireCell.textContent = firing ? "FIRE" : "hold";

  const turnCell = document.createElement("span");
  const move = turn ? String(turn.value) : "—";
  turnCell.className = `log-turn ${move}`;
  turnCell.textContent = move;

  const worst = Math.min(...message.answers.map((a) => a.confidence));
  const conf = document.createElement("span");
  conf.className = worst < LOW_CONFIDENCE ? "log-conf unsure" : "log-conf";
  conf.textContent = message.answers
    .map((a) => `${a.name[0]}=${a.confidence.toFixed(2)}`)
    .join(" ");

  const lat = document.createElement("span");
  const ms = message.latency_ms;
  lat.className = ms > budgetMs ? "log-lat over" : "log-lat";
  lat.textContent = ms === null || ms === undefined ? "—" : `${ms.toFixed(0)}ms`;

  row.append(tick, fireCell, turnCell, conf, lat);

  const log = $("log");
  log.prepend(row);
  while (log.childElementCount > LOG_LIMIT) log.lastElementChild.remove();
  $("log-count").textContent = ++logged;
}

function renderKeys(buttons, pressed) {
  $("keys").replaceChildren(
    ...buttons.map((name) => {
      const el = document.createElement("span");
      el.className = pressed.includes(name) ? "key on" : "key";
      el.textContent = name.replace("_", " ").toLowerCase();
      return el;
    }),
  );
}

function bars(answer) {
  const entries = Object.entries(answer.distribution ?? {});
  if (!entries.length) return null;
  const top = Math.max(...entries.map(([, p]) => p));
  const wrap = document.createElement("div");
  wrap.className = "bars";
  for (const [label, probability] of entries) {
    const row = document.createElement("div");
    row.className = probability === top ? "bar-row top" : "bar-row";

    const name = document.createElement("span");
    name.className = "bar-label";
    name.textContent = label;
    name.title = label;

    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${(probability * 100).toFixed(1)}%`;
    track.append(fill);

    const pct = document.createElement("span");
    pct.className = "bar-pct";
    pct.textContent = `${(probability * 100).toFixed(0)}%`;

    row.append(name, track, pct);
    wrap.append(row);
  }
  return wrap;
}

function renderAnswer(answer) {
  const card = document.createElement("div");
  const unsure = answer.confidence < LOW_CONFIDENCE;
  card.className = unsure ? "answer unsure" : "answer";

  const head = document.createElement("div");
  head.className = "answer-head";

  const name = document.createElement("span");
  name.className = "answer-name";
  name.textContent = `${answer.name} · ${answer.type}`;

  const value = document.createElement("span");
  value.className = "answer-value";
  if (answer.type === "noul") {
    value.classList.add(answer.value >= 0.5 ? "yes" : "no");
  }
  value.textContent = answer.label;

  head.append(name, value);
  card.append(head);

  const chart = bars(answer);
  if (chart) card.append(chart);

  if (unsure) {
    const flag = document.createElement("p");
    flag.className = "unsure-flag";
    flag.textContent =
      `near-uniform (confidence ${answer.confidence.toFixed(3)}) — the model is telling you it does not know`;
    card.append(flag);
  }
  return card;
}

function renderLatency(ms) {
  if (ms === null || ms === undefined) return;
  latencies.push(ms);
  if (latencies.length > 400) latencies.shift();
  const ordered = [...latencies].sort((a, b) => a - b);
  const p = (q) => ordered[Math.max(0, Math.ceil(q * ordered.length) - 1)];

  $("lat-last").textContent = `${fmt(ms, 1)} ms`;
  $("lat-p50").textContent = `${fmt(p(0.5), 1)} ms`;
  $("lat-p95").textContent = `${fmt(p(0.95), 1)} ms`;
  $("lat-budget").textContent = `${fmt((p(0.5) / budgetMs) * 100)}%`;

  const recent = latencies.slice(-SPARK_SAMPLES);
  const peak = Math.max(budgetMs, ...recent);
  $("spark").replaceChildren(
    ...recent.map((value) => {
      const bar = document.createElement("i");
      bar.style.height = `${Math.max(2, (value / peak) * 100)}%`;
      if (value > budgetMs) bar.classList.add("over");
      bar.title = `${value.toFixed(1)} ms`;
      return bar;
    }),
  );
}

function onTick(message) {
  drawFrame(message.frame);
  $("health").textContent = fmt(message.health);
  $("ammo").textContent = fmt(message.ammo);
  $("kills").textContent = fmt(message.kills);
  $("tick").textContent = message.tick;
  renderKeys(message.buttons ?? ["TURN_LEFT", "TURN_RIGHT", "ATTACK"], message.pressed);
  $("sweep").hidden = !message.sweeping;

  if (message.observation) $("observation").textContent = message.observation;

  // Only redraw answers when a reply actually landed; between replies the latch
  // is coasting and the previous answers are still what is steering the game.
  if (message.fresh && message.answers.length) {
    $("answers").replaceChildren(...message.answers.map(renderAnswer));
    renderLatency(message.latency_ms);
    logDecision(message);
  }
}

function onEpisode(message) {
  $("ep-count").textContent = message.episodes_played;
  $("ep-score").textContent = fmt(message.mean_score, 2);
  $("ep-skipped").textContent = message.skipped;
  $("ep-stale").textContent = message.stale;
  $("ep-sweeps").textContent =
    message.sweeps_interrupted ? `${message.sweeps} (${message.sweeps_interrupted} cut short)` : message.sweeps;
  $("rate").textContent = fmt(message.decisions_per_second, 1);

  // A new episode starts a fresh log; the old one stays scrolled above.
  logged = 0;
  $("log-count").textContent = 0;

  const item = document.createElement("li");
  item.textContent = `${message.policy} · ${message.summary}`;
  $("episodes").prepend(item);
}

function setStatus(text, bad = false) {
  const el = $("status");
  el.textContent = text;
  el.className = bad ? "note bad" : "note";
}

function connect() {
  const socket = new WebSocket(`ws://${location.host}/ws`);
  socket.onopen = () => {
    setStatus("Connected. Press Start.");
    setInterval(() => socket.readyState === 1 && socket.send("ping"), 15000);
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "tick") onTick(message);
    else if (message.type === "episode") onEpisode(message);
    else if (message.type === "error") setStatus(message.message, true);
  };
  socket.onclose = () => {
    setStatus("Disconnected. Reconnecting…", true);
    setTimeout(connect, 1200);
  };
}

const post = (path) => fetch(path, { method: "POST" }).then((r) => r.json());

$("start").onclick = async () => {
  setStatus("Loading the model and warming up…");
  await post("/api/start");
  setStatus("Running.");
};
$("stop").onclick = async () => {
  await post("/api/stop");
  setStatus("Paused.");
};
$("restart").onclick = () => post("/api/restart");
$("policy").onchange = async (event) => {
  latencies.length = 0;
  logged = 0;
  $("log").replaceChildren();
  $("log-count").textContent = 0;
  $("episodes").replaceChildren();
  await post(`/api/policy/${event.target.value}`);
  setStatus(`Policy: ${event.target.value}.`);
};

fetch("/api/status")
  .then((r) => r.json())
  .then((status) => {
    budgetMs = status.interval_ms ?? budgetMs;
    $("policy").value = status.policy;
    if (status.error) setStatus(status.error, true);
  });

connect();
