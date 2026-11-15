// The STB simulator's user interface (index.html). Everything is reached with
// remote control keys: the arrow keys move the selection, OK opens what is
// selected, BACK returns to where the user was before, EXIT goes home.
//
// The stb-simulator workload serves this page. It tells the page what the
// device has (GET /api/config), is told what the user interface does (POST
// /api/event, printed as EMU-STB lines), and starts what a page cannot: a
// performance workload (POST /api/run) and switching off (POST /api/off).
"use strict";

const $ = (id) => document.getElementById(id);
const video = $("video");
let config = null;
let screen = null;                // the screen that is shown
const trail = [];                 // the screens the user came through, for BACK
const focusOf = {};               // the selection each screen was left with

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value; else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) node.append(child);
  }
  return node;
}

function tell(data) {
  return fetch("/api/event", { method: "POST", body: JSON.stringify(data) }).catch(() => {});
}
async function call(path, data) {
  const reply = await fetch(path, { method: "POST", body: JSON.stringify(data || {}) });
  return reply.json();
}
async function readConfig() {
  config = await (await fetch("/api/config", { cache: "no-store" })).json();
  return config;
}
window.addEventListener("error", (event) => tell({ event: "script-error", text: String(event.message) }));
window.addEventListener("unhandledrejection", (event) => tell({ event: "script-error", text: String(event.reason) }));

// ---------------------------------------------------------------- screens ---

// A screen: its title, what it lists (items with a label, and what OK does),
// what else it shows, and the keys it takes besides the common ones.
const SCREENS = {
  home: {
    title: "Emu TV",
    items: () => [
      { id: "channels", name: "TV channels", about: config.channels.length + " channels", open: () => go("channels") },
      { id: "apps", name: "Apps", about: "Video on demand", open: () => go("apps") },
      { id: "performance", name: "Performance tests", about: config.workloads.length + " workloads of the evaluation",
        open: () => go("performance") },
      { id: "off", name: "Switch off", about: "Ends the simulator", open: switchOff },
    ],
    side: () => el("dl", {},
      el("dt", {}, "Display"), el("dd", {}, config.display.width + " x " + config.display.height),
      el("dt", {}, "Graphics"), el("dd", {}, config.graphics === "host" ? "host GPU" : "emulated"),
      el("dt", {}, "Sound"), el("dd", {}, config.sound ? "on the target's audio device" : "no audio device"),
      el("dt", {}, "Remote control"), el("dd", {}, config.remote ? "on" : "off: no keys reach this screen"),
      el("dt", {}, "Simulator"), el("dd", {}, "version " + config.version)),
    hints: [["OK", "open"], ["EXIT", "home"]],
  },
  channels: {
    title: "TV channels",
    items: () => config.channels.map((channel) => ({
      id: String(channel.number), number: channel.number, name: channel.name, about: channel.about,
      open: () => { go("tv"); tune(channel.number); } })),
    side: () => el("p", {}, "OK plays the selected channel. While a channel plays, Up and Down change the channel, "
      + "a digit selects one by its number, and BACK returns to this list."),
    hints: [["OK", "play"], ["0-9", "channel"], ["BACK", "home"]],
  },
  tv: { title: "", playing: true, hints: [] },
  apps: {
    title: "Apps",
    grid: true,
    items: () => [
      { id: "vod", name: "Video on demand", about: "Open films as MPEG-DASH streams, played with dash.js",
        open: () => { tell({ event: "app", app: "vod", state: "starting" }).then(() => { location.href = "/stb/vod/index.html"; }); } },
    ],
    hints: [["OK", "start"], ["BACK", "home"]],
  },
  performance: {
    title: "Performance tests",
    items: () => config.workloads.map((workload) => ({
      id: workload.id, name: workload.name, about: workload.about,
      tag: workload.display ? "takes over the display" : "",
      open: () => startWorkload(workload) })),
    side: () => el("p", {}, "OK starts a workload of the performance evaluation. It runs as it does when the "
      + "launcher starts it and reports its results to the launcher; they are shown here when it is done. "
      + (config.quick ? "This simulator was started for a short run of each (--quick)." : "")),
    hints: [["OK", "run"], ["BACK", "home"]],
  },
  running: { title: "Performance tests", hints: [] },
  results: { title: "Results", hints: [["BACK", "performance tests"]] },
};

function go(name, options) {
  if (screen && !(options && options.replace)) trail.push(screen);
  show(name);
}

function back() {
  if (screen === "tv") stopChannel();
  const previous = trail.pop();
  if (previous) show(previous);
  else if (screen !== "home") show("home");
}

function home() {
  if (screen === "tv") stopChannel();
  trail.length = 0;
  show("home");
}

function show(name) {
  screen = name;
  const spec = SCREENS[name];
  $("screen").hidden = Boolean(spec.playing);
  video.hidden = !spec.playing;
  if (!spec.playing) $("banner").hidden = true;
  $("message").hidden = true;
  $("title").textContent = spec.title;
  $("where").textContent = name === "home" ? clock() : "Emu TV";
  $("hints").replaceChildren(...spec.hints.map(([key, what]) => el("span", {}, el("b", {}, key), " " + what)));
  const main = $("main");
  main.replaceChildren();
  let items = [];
  if (spec.items) {
    items = spec.items();
    const wanted = Math.max(0, items.findIndex((item) => item.id === focusOf[name]));
    main.append(el("div", { class: spec.grid ? "grid" : "list" }, items.map((item, index) => el("div",
      { class: "item" + (index === wanted ? " focus" : ""), "data-id": item.id },
      item.number !== undefined && el("div", { class: "number" }, String(item.number)),
      el("div", {}, el("div", { class: "name" }, item.name), item.about && el("div", { class: "about" }, item.about)),
      item.tag && el("div", { class: "tag" }, item.tag)))));
    focusOf[name] = items.length ? items[wanted].id : null;
  }
  if (spec.side) main.append(el("div", { class: "side" }, spec.side()));
  if (name === "running") main.append(runningNotice());
  if (name === "results") main.append(resultsTable());
  tell({ event: "screen", screen: name, focus: focusOf[name] || null, items: items.map((item) => item.id) });
}

function clock() {
  const now = new Date();
  return String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
}

function move(step) {
  const spec = SCREENS[screen];
  if (!spec.items) return;
  const items = spec.items();
  const index = items.findIndex((item) => item.id === focusOf[screen]);
  const next = Math.min(items.length - 1, Math.max(0, index + step));
  if (next === index) return;
  focusOf[screen] = items[next].id;
  for (const node of document.querySelectorAll("#main .item")) {
    node.classList.toggle("focus", node.getAttribute("data-id") === focusOf[screen]);
  }
  tell({ event: "focus", screen, focus: focusOf[screen] });
}

function open() {
  const spec = SCREENS[screen];
  if (!spec.items) return;
  const item = spec.items().find((found) => found.id === focusOf[screen]);
  if (item) item.open();
}

// --------------------------------------------------------------- channels ---

// A channel is a reference stream played in a loop through Media Source
// Extensions: its initialisation segment and media fragments are appended to
// a source buffer, and when the stream ends it starts again.
let tuned = null;         // the channel that plays, or is being started
let tuning = 0;           // counts the changes, so that a slow start gives way to a newer one
let digits = "";
let digitTimer = null, bannerTimer = null;

function appended(buffer, data) {
  return new Promise((resolve, reject) => {
    buffer.addEventListener("updateend", resolve, { once: true });
    buffer.addEventListener("error", () => reject(new Error("the source buffer refused a fragment")), { once: true });
    buffer.appendBuffer(data);
  });
}

async function tune(number) {
  const channel = config.channels.find((found) => found.number === number);
  if (!channel) { banner(null, "No channel " + number); return; }
  const mine = ++tuning;
  tuned = channel;
  focusOf.channels = String(channel.number);
  banner(channel);
  tell({ event: "channel", state: "tuning", number: channel.number, stream: channel.stream });
  try {
    if (!("MediaSource" in window) || !MediaSource.isTypeSupported(channel.type)) {
      throw new Error("the browser does not play " + channel.type);
    }
    video.muted = !config.sound;
    const source = new MediaSource();
    video.src = URL.createObjectURL(source);
    await new Promise((resolve) => source.addEventListener("sourceopen", resolve, { once: true }));
    const buffer = source.addSourceBuffer(channel.type);
    for (const name of [channel.init, ...channel.media]) {
      const reply = await fetch(channel.base + name);
      if (!reply.ok) throw new Error("no " + name);
      const data = await reply.arrayBuffer();
      if (mine !== tuning) return;          // another channel was chosen meanwhile
      await appended(buffer, data);
      if (name === channel.init) {
        video.play().catch(() => { video.muted = true; video.play().catch(() => {}); });
      }
    }
    if (mine === tuning && source.readyState === "open") source.endOfStream();
  } catch (error) {
    if (mine !== tuning) return;
    tell({ event: "channel", state: "error", number: channel.number, reason: String(error.message || error) });
    banner(channel, "This channel cannot be played: " + (error.message || error));
  }
}

video.addEventListener("playing", () => {
  if (screen !== "tv" || !tuned) return;
  tell({ event: "channel", state: "playing", number: tuned.number, stream: tuned.stream,
         video: video.videoWidth + "x" + video.videoHeight, sound: !video.muted });
});
// A channel has no end: the stream starts again.
video.addEventListener("ended", () => {
  if (screen !== "tv") return;
  video.currentTime = 0;
  video.play().catch(() => {});
});
video.addEventListener("error", () => {
  if (screen !== "tv" || !tuned) return;
  const reason = video.error ? video.error.code + " " + (video.error.message || "") : "an error";
  tell({ event: "channel", state: "error", number: tuned.number, reason });
  banner(tuned, "This channel cannot be played (" + reason.trim() + ")");
});

function stopChannel() {
  tuning++;
  if (tuned) tell({ event: "channel", state: "stopped", number: tuned.number });
  tuned = null;
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("banner").hidden = true;
}

function banner(channel, text) {
  const node = $("banner");
  node.replaceChildren(
    channel && el("div", { class: "number" }, String(channel.number)),
    el("div", {}, el("div", { class: "name" }, channel ? channel.name : text),
       el("div", { class: "about" }, channel ? (text || channel.about) : "")),
    el("div", { class: "right" }, clock()));
  node.hidden = false;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => { node.hidden = true; }, text ? 8000 : 4000);
}

function step(direction) {
  const numbers = config.channels.map((channel) => channel.number);
  const index = numbers.indexOf(tuned ? tuned.number : numbers[0]);
  tune(numbers[(index + direction + numbers.length) % numbers.length]);
}

function digit(key) {
  digits = (digits + key).slice(-3);
  banner(null, "Channel " + digits);
  clearTimeout(digitTimer);
  digitTimer = setTimeout(() => {
    const number = Number(digits);
    digits = "";
    if (screen !== "tv") { go("tv"); }
    tune(number);
  }, 1200);
}

// ------------------------------------------------------------ performance ---

let pollTimer = null;

async function startWorkload(workload) {
  const reply = await call("/api/run", { id: workload.id });
  await readConfig();
  if (!reply.started) {
    $("message").replaceChildren(el("div", { class: "big" }, "Not started"), el("div", {}, reply.reason || ""));
    $("message").hidden = false;
    setTimeout(() => { $("message").hidden = true; }, 4000);
    return;
  }
  go("running");
  poll();
}

// A workload that takes over the display ends this page; the simulator
// starts it again at the results. One that does not is waited for here.
function poll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try { await readConfig(); } catch (error) { return poll(); }
    if (screen !== "running") return;
    if (config.running) { $("main").replaceChildren(runningNotice()); return poll(); }
    go("results", { replace: true });            // the running notice is not a place to return to
  }, 1000);
}

function runningNotice() {
  const running = config.running || {};
  const seconds = running.started ? Math.max(0, Math.round(Date.now() / 1000 - running.started)) : 0;
  return el("div", { class: "notice" },
    el("div", { class: "big" }, "Running: " + (running.name || "a performance test")),
    el("div", { class: "muted" }, running.display
      ? "It takes over the display now. This screen returns with its results."
      : "Its results are shown here when it is done. " + seconds + " s so far."));
}

function resultsTable() {
  const last = config.last;
  if (!last) return el("div", { class: "notice" }, el("div", { class: "big" }, "No performance test has run yet"));
  const value = (result) => result.value === null || result.value === undefined ? "unavailable"
    : (Math.abs(result.value) >= 100 ? Math.round(result.value) : Number(result.value).toFixed(2)) + " " + (result.unit || "");
  const rows = last.results.slice(0, 14);
  return el("div", { class: "results" },
    el("h2", {}, last.name + (last.quick ? " (short run)" : "")),
    el("p", { class: "muted" }, last.results.length + " results in " + last.seconds + " s"
      + (last.status === 0 ? "" : ", ended with status " + last.status)
      + (last.results.length > rows.length ? "; the first " + rows.length + " are shown, the launcher has them all" : "")),
    el("table", {},
      el("thead", {}, el("tr", {}, ["Area", "Test", "Case", "Result"].map((name) => el("th", {}, name)))),
      el("tbody", {}, rows.map((result) => el("tr", {},
        el("td", {}, result.area || ""), el("td", {}, result.test || ""),
        el("td", {}, [result.case, result.resolution].filter(Boolean).join(" · ")),
        el("td", { class: "num" }, value(result)))))));
}

async function switchOff() {
  $("message").replaceChildren(el("div", { class: "big" }, "Switching off"));
  $("message").hidden = false;
  await tell({ event: "screen", screen: "off" });
  call("/api/off").catch(() => {});
}

// ------------------------------------------------------------------- keys ---

// The remote control's keys as the browser names them. BACK is the browser's
// "BrowserBack" key and EXIT its "Close" key; the page handles both itself.
addEventListener("keydown", (event) => {
  const key = event.key;
  if (!screen || !config) return;
  let handled = true;
  if (key === "Close") home();
  else if (key === "BrowserBack" || key === "Backspace") { if (screen !== "running") back(); }
  else if (screen === "tv") {
    if (key === "ArrowUp") step(1);
    else if (key === "ArrowDown") step(-1);
    else if (key === "Enter") banner(tuned);
    else if (/^[0-9]$/.test(key)) digit(key);
    else if (key === "MediaStop") back();
    else handled = false;
  } else if (key === "ArrowUp" || key === "ArrowLeft") move(-1);
  else if (key === "ArrowDown" || key === "ArrowRight") move(1);
  else if (key === "Enter") open();
  else if (/^[0-9]$/.test(key) && screen === "channels") digit(key);
  else handled = false;
  if (handled) event.preventDefault();
  // A key without a function here is reported, so that whoever watches the
  // run sees that keys arrive.
  else tell({ event: "key", screen, key, code: event.keyCode });
});

// ------------------------------------------------------------------ start ---

async function start() {
  await readConfig();
  tell({ event: "ready", page: "stb", user_agent: navigator.userAgent, viewport: innerWidth + "x" + innerHeight });
  // Where to begin: the simulator names the results after a workload that
  // took over the display, and the video on demand application returns to
  // the app launcher.
  const wanted = location.hash.replace("#", "");
  // The home screen's selection is where the user left it.
  if (wanted === "results") { focusOf.home = "performance"; trail.push("home", "performance"); show("results"); }
  else if (wanted === "apps") { focusOf.home = "apps"; trail.push("home"); show("apps"); }
  else if (config.running) { focusOf.home = "performance"; trail.push("home", "performance"); show("running"); poll(); }
  else show("home");
}

start();
