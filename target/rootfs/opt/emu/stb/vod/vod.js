// The STB simulator's video on demand application (index.html). Its titles
// are MPEG-DASH streams, played with dash.js, which chooses among a stream's
// representations as it plays: by the speed of the connection, and no larger
// than the display.
//
// Keys: the arrow keys and OK choose a title; BACK or EXIT at the titles
// leaves the application, back to the simulator's app launcher. While a
// title plays: OK or play/pause pauses and resumes, Left and Right (and
// rewind and fast forward) move through the title, BACK or stop returns to
// the titles.
"use strict";

const $ = (id) => document.getElementById(id);
const video = $("video");
const STB = "/stb/index.html#apps";
let config = null;
let titles = [];
let focus = 0;
let playing = null;           // the title that plays
let player = null;
let shown = null;             // the video representation that is on the display
let bannerTimer = null, progressTimer = null;

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
  return fetch("/api/event", { method: "POST", body: JSON.stringify(Object.assign({ event: "vod" }, data)) })
    .catch(() => {});
}
window.addEventListener("error", (event) => tell({ state: "script-error", text: String(event.message) }));
window.addEventListener("unhandledrejection", (event) => tell({ state: "script-error", text: String(event.reason) }));

function clockTime(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  const whole = Math.max(0, Math.floor(seconds));
  return Math.floor(whole / 60) + ":" + String(whole % 60).padStart(2, "0");
}
const megabits = (bits) => (bits / 1e6).toFixed(bits < 1e6 ? 2 : 1) + " Mbit/s";

// ----------------------------------------------------------------- titles ---

function showTitles() {
  $("screen").hidden = false;
  video.hidden = true;
  $("banner").hidden = true;
  $("message").hidden = true;
  $("hints").replaceChildren(...[["OK", "play"], ["BACK", "leave"]].map(([key, what]) =>
    el("span", {}, el("b", {}, key), " " + what)));
  const title = titles[focus];
  $("main").replaceChildren(
    el("div", { class: "list" }, titles.map((entry, index) => el("div",
      { class: "item" + (index === focus ? " focus" : "") },
      el("div", {}, el("div", { class: "name" }, entry.name + (entry.year ? " (" + entry.year + ")" : "")),
         el("div", { class: "about" }, entry.where === "device" ? "On this device" : "On the internet")),
      el("div", { class: "tag" }, entry.minutes >= 1 ? Math.round(entry.minutes) + " min" : "20 s")))),
    el("div", { class: "side" },
      el("p", {}, title.about),
      el("dl", { style: "margin-top:1rem" },
        el("dt", {}, "Stream"), el("dd", {}, "MPEG-DASH, adaptive"),
        el("dt", {}, "From"), el("dd", {}, title.served_by || ""),
        el("dt", {}, "Licence"), el("dd", {}, title.licence || ""))));
  tell({ state: "titles", focus: title.id, titles: titles.map((entry) => entry.id) });
}

function move(step) {
  const next = Math.min(titles.length - 1, Math.max(0, focus + step));
  if (next === focus) return;
  focus = next;
  showTitles();
}

// ----------------------------------------------------------------- player ---

function play(title) {
  playing = title;
  shown = null;
  $("screen").hidden = true;
  video.hidden = false;
  video.muted = !config.sound;
  banner("Starting…");
  tell({ state: "starting", title: title.id, url: title.url });
  player = dashjs.MediaPlayer().create();
  // Start small and grow with the connection; no larger than the display.
  player.updateSettings({ streaming: { abr: { limitBitrateByPortal: true, usePixelRatioInLimitBitrateByPortal: false,
                                              initialBitrate: { video: 300 } } } });
  const events = dashjs.MediaPlayer.events;
  player.on(events.ERROR, (event) => {
    const error = event.error || {};
    failed(error.message || (error.code !== undefined ? "error " + error.code : "an error"));
  });
  player.on(events.STREAM_INITIALIZED, () => {
    const all = player.getRepresentationsByType("video") || [];
    tell({ state: "stream", title: title.id, dash_js: player.getVersion(), duration: Math.round(player.duration()),
           representations: all.map((r) => ({ id: r.id, width: r.width, height: r.height, bandwidth: r.bandwidth,
                                               codecs: r.codecs })) });
  });
  player.on(events.QUALITY_CHANGE_RENDERED, (event) => {
    if (event.mediaType !== "video" || !event.newRepresentation) return;
    const r = event.newRepresentation;
    shown = { id: r.id, width: r.width, height: r.height, bandwidth: r.bandwidth };
    tell({ state: "representation", title: title.id, representation: shown, time: Math.round(video.currentTime * 10) / 10 });
    banner();
  });
  player.on(events.PLAYBACK_ENDED, () => { tell({ state: "ended", title: title.id }); stop(); });
  player.initialize(video, title.url, true);
  clearInterval(progressTimer);
  progressTimer = setInterval(progress, 5000);
}

video.addEventListener("playing", () => {
  if (!playing) return;
  tell({ state: "playing", title: playing.id, time: Math.round(video.currentTime * 10) / 10,
         video: video.videoWidth + "x" + video.videoHeight, sound: !video.muted, representation: shown });
  banner();
});
video.addEventListener("pause", () => { if (playing && !video.ended) { tell({ state: "paused", title: playing.id }); banner("Paused", true); } });

function progress() {
  if (!playing || video.paused) return;
  const quality = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : {};
  tell({ state: "progress", title: playing.id, time: Math.round(video.currentTime * 10) / 10,
         video: video.videoWidth + "x" + video.videoHeight, representation: shown,
         frames: quality.totalVideoFrames, dropped: quality.droppedVideoFrames });
}

function banner(text, keep) {
  if (!playing) return;
  const node = $("banner");
  node.replaceChildren(
    el("div", {}, el("div", { class: "name" }, playing.name),
       el("div", { class: "about" }, text || (clockTime(video.currentTime) + " / " + clockTime(video.duration)))),
    el("div", { class: "right" }, shown ? shown.width + " x " + shown.height + " · " + megabits(shown.bandwidth) : ""));
  node.hidden = false;
  clearTimeout(bannerTimer);
  if (!keep) bannerTimer = setTimeout(() => { node.hidden = true; }, 4000);
}

function teardown() {
  clearInterval(progressTimer);
  clearTimeout(bannerTimer);
  if (player) { try { player.destroy(); } catch (error) { /* it is going away */ } }
  player = null;
  playing = null;
  video.removeAttribute("src");
  video.load();
}

function stop() {
  if (playing) tell({ state: "stopped", title: playing.id });
  teardown();
  showTitles();
}

// A title that cannot be played: say so, and stay usable.
function failed(reason) {
  if (!playing) return;
  const title = playing;
  const unreachable = /not available|NetworkError|network|load/i.test(reason);
  tell({ state: "error", title: title.id, reason, unreachable });
  teardown();
  showTitles();
  $("message").replaceChildren(
    el("div", { class: "big" }, title.name + " cannot be played"),
    el("div", { class: "muted" }, unreachable && title.where !== "device"
      ? "Its stream is on the internet, which this device cannot reach now."
      : reason),
    el("div", { class: "muted", style: "margin-top:0.6rem" }, "OK or BACK returns to the titles."));
  $("message").hidden = false;
}

function seek(seconds) {
  if (!player) return;
  const target = Math.min(Math.max(0, video.currentTime + seconds), Math.max(0, (video.duration || 0) - 1));
  player.seek(target);
  banner();
}

function toggle() {
  if (video.paused) video.play().catch(() => {}); else video.pause();
}

// ------------------------------------------------------------------- keys ---

addEventListener("keydown", (event) => {
  const key = event.key;
  if (!config) return;
  let handled = true;
  if (!$("message").hidden) {
    if (key === "Enter" || key === "BrowserBack" || key === "Backspace") $("message").hidden = true;
    else if (key === "Close") leave();
    else handled = false;
  } else if (playing) {
    if (key === "BrowserBack" || key === "Backspace" || key === "MediaStop") stop();
    else if (key === "Close") { teardown(); leave(); }
    else if (key === "Enter" || event.code === "MediaPlayPause") toggle();
    else if (key === "MediaPlay") video.play().catch(() => {});
    else if (key === "MediaPause") video.pause();
    else if (key === "ArrowLeft") seek(-10);
    else if (key === "ArrowRight") seek(10);
    else if (key === "MediaRewind") seek(-30);
    else if (key === "MediaFastForward") seek(30);
    else if (key === "ArrowUp" || key === "ArrowDown") banner();
    else handled = false;
  } else if (key === "ArrowUp" || key === "ArrowLeft") move(-1);
  else if (key === "ArrowDown" || key === "ArrowRight") move(1);
  else if (key === "Enter") { if (titles[focus]) play(titles[focus]); }
  else if (key === "BrowserBack" || key === "Backspace" || key === "Close") leave();
  else handled = false;
  if (handled) event.preventDefault();
  else fetch("/api/event", { method: "POST", body: JSON.stringify({ event: "key", screen: "vod", key, code: event.keyCode }) })
    .catch(() => {});
});

// Leaving the application: the simulator's user interface is shown again.
function leave() {
  tell({ state: "leaving" }).then(() => { location.href = STB; });
}

async function start() {
  config = await (await fetch("/api/config", { cache: "no-store" })).json();
  titles = config.titles || [];
  await tell({ state: "ready", page: "vod", dash_js: typeof dashjs === "undefined" ? null : dashjs.Version || true });
  if (typeof dashjs === "undefined" || !titles.length) {
    $("main").replaceChildren(el("div", { class: "notice" }, el("div", { class: "big" },
      typeof dashjs === "undefined" ? "The player (dash.js) is not on this device" : "No titles")));
    titles = [];
    return;
  }
  showTitles();
}

start();
