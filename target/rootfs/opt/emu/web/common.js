// Shared by the pages of the web-bench workload
// (target/rootfs/opt/emu/workloads/web-bench). A page reports to the workload,
// which serves it, with POST requests: /result when its test is done, /screen
// when a frame is on the display for the launcher to capture (the answer comes
// when the capture has been made), /failure when the test cannot be done.
"use strict";

const PARAMETERS = new URLSearchParams(location.search);

function parameter(name, fallback) {
  return PARAMETERS.has(name) ? PARAMETERS.get(name) : fallback;
}

async function post(path, data) {
  const reply = await fetch(path, { method: "POST", body: JSON.stringify(data) });
  return reply.ok;
}

function report(data) { return post("/result", data); }
function capture(data) { return post("/screen", data); }
function failure(reason) { return post("/failure", { reason: String(reason) }); }

window.addEventListener("error", (event) => { failure("script error: " + event.message); });
window.addEventListener("unhandledrejection", (event) => { failure("script error: " + event.reason); });

// What draws for the page, as far as the browser tells.
function renderer() {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    if (!gl) return { webgl: false };
    const names = gl.getExtension("WEBGL_debug_renderer_info");
    return { webgl: true, version: gl.getParameter(gl.VERSION),
             renderer: names ? gl.getParameter(names.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) };
  } catch (error) {
    return { webgl: false, error: String(error) };
  }
}

function browser() {
  return { user_agent: navigator.userAgent, viewport: innerWidth + "x" + innerHeight,
           device_pixel_ratio: devicePixelRatio, media_source: "MediaSource" in window, graphics: renderer() };
}

function percentile(sorted, fraction) {
  if (!sorted.length) return null;
  return sorted[Math.min(sorted.length - 1, Math.floor(fraction * sorted.length))];
}

// The marker blocks the launcher looks for in a capture of the display, as in
// target/src/emugfx.c: the four corners, and one at the top centre whose colour
// names what drew the frame. Each is a twelfth of the display's height square.
function markers(colour) {
  const size = Math.floor(innerHeight / 12);
  const blocks = [["left:0;top:0", "rgb(255,0,0)"], ["right:0;top:0", "rgb(0,255,0)"],
                  ["left:0;bottom:0", "rgb(0,0,255)"], ["right:0;bottom:0", "rgb(255,255,255)"],
                  ["left:" + Math.floor((innerWidth - size) / 2) + "px;top:0", "rgb(" + colour.join(",") + ")"]];
  for (const [place, fill] of blocks) {
    const block = document.createElement("div");
    block.style.cssText = "position:fixed;z-index:10;width:" + size + "px;height:" + size + "px;background:" + fill
                          + ";" + place;
    document.body.appendChild(block);
  }
}
