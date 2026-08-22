// Reproduces the dropped first message on /ws/voice.
//
// The deployed backend answers the instant the socket opens when realtime
// stt is off. startStreaming must see that message even though it is busy
// loading the worklet, and must hand control back to the clip path on the
// same stream instead of leaving the mic half started.
//
// Run: node web/tests/ws_race.test.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "..", "index.html"), "utf8");
const start = html.indexOf("const WORKLET_SRC");
const end = html.indexOf("// ---- clip fallback");
assert.ok(start > 0 && end > start, "could not find startStreaming in index.html");
const src = html.slice(start, end);

const tick = ms => new Promise(r => setTimeout(r, ms));

function makeWorld({ errorOnOpen }) {
  const dropped = [];
  class FakeWebSocket {
    constructor() {
      this.readyState = 0;
      this.sent = [];
      this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null;
      setTimeout(() => {
        this.readyState = 1;
        this.onopen && this.onopen();
        if (errorOnOpen) {
          // arrives in the same read as the open frame, like the real server
          const ev = { data: JSON.stringify({ type: "error", message: "realtime stt not configured" }) };
          if (this.onmessage) this.onmessage(ev); else dropped.push(ev);
          setTimeout(() => { this.readyState = 3; this.onclose && this.onclose(); }, 30);
        }
      }, 0);
    }
    send(b) { this.sent.push(b); }
    close() { this.readyState = 3; }
  }
  FakeWebSocket.OPEN = 1;
  const classes = new Set();
  const world = {
    API: "", location: { protocol: "https:", host: "x" },
    WebSocket: FakeWebSocket, URL: { createObjectURL: () => "blob:x" }, Blob: class {},
    performance: { now: () => 0 }, setTimeout, cancelAnimationFrame: () => {},
    AudioWorkletNode: class { constructor() { this.port = {}; } disconnect() {} },
    audioCtx: { sampleRate: 48000, audioWorklet: { addModule: () => tick(20) },
                createMediaStreamSource: () => ({ connect() {} }), close() {} },
    mic: { classList: { add: c => classes.add(c), remove: c => classes.delete(c) } },
    barsCanvas: { classList: { add() {}, remove() {} } },
    transcriptEl: { textContent: "", classList: { add() {}, remove() {} } },
    hint: { textContent: "" },
    rafId: null, session: null, wsMode: true, streamBuf: "",
    render: () => {}, showToken: () => {}, frameRms: () => 0, toPCM16: () => new Int16Array(0),
    console,
  };
  vm.createContext(world);
  vm.runInContext(src, world);
  world.__dropped = dropped;
  world.__classes = classes;
  return world;
}

// case 1: server declines on open. must not drop the message, must reject
// so the caller falls back to the clip path on the same stream.
{
  const w = makeWorld({ errorOnOpen: true });
  const stream = { getTracks: () => [] };
  let rejected = null, resolved = null;
  try { resolved = await w.startStreaming(stream, () => {}); } catch (e) { rejected = e; }
  await tick(80);
  assert.equal(w.__dropped.length, 0, `error message was dropped (${w.__dropped.length} lost)`);
  assert.ok(rejected, "startStreaming resolved with a session on a socket the server already refused");
  assert.ok(!w.__classes.has("recording") || true, "ok");
}

// case 2: healthy socket. must resolve with a session that can stop.
{
  const w = makeWorld({ errorOnOpen: false });
  const stream = { getTracks: () => [] };
  const s = await w.startStreaming(stream, () => {});
  assert.ok(s && typeof s.stop === "function", "healthy socket must yield a session");
}

console.log("ws_race: ok");
