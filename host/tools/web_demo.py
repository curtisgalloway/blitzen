# Copyright 2026 The Blitzen Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A browser playground for the procedural patterns.

A tiny stdlib HTTP server (no extra deps) renders frames with the *real*
:mod:`host.patterns` code — the same single source of truth the live path uses —
so the playground reflects exactly what hardware would show, and any newly
registered pattern shows up automatically. Each pattern's constructor is
introspected to expose live parameter sliders; the browser owns the display side
(grid size, LED look, rotation, serpentine wiring, multi-panel tiling)::

    python -m host.tools.web_demo            # opens http://127.0.0.1:8080

The browser polls ``/api/frame`` per tick; geometry, layout, and styling are all
client-side, so the host never needs to know about a "display" at all.
"""

from __future__ import annotations

import argparse
import inspect
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

from host.patterns import PATTERNS, get_pattern

#: Hard cap on either rendered dimension — keeps a stray query from allocating a
#: huge buffer. Comfortably above any real LED matrix.
MAX_DIM = 256


def _param_descriptor(name: str, default: Any) -> Dict[str, Any]:
    """Describe one constructor parameter for the UI (slider / color / toggle)."""
    if isinstance(default, (tuple, list)) and len(default) == 3:
        hexcolor = "%02x%02x%02x" % tuple(int(c) & 0xFF for c in default)
        return {"name": name, "kind": "color", "default": hexcolor}
    if isinstance(default, bool):
        return {"name": name, "kind": "bool", "default": default}
    if isinstance(default, int):
        return {"name": name, "kind": "int", "default": default,
                "min": 0, "max": max(8, default * 4), "step": 1}
    value = float(default)
    high = max(1.0, value * 4.0) if value > 0 else 1.0
    return {"name": name, "kind": "float", "default": value,
            "min": 0.0, "max": round(high, 3), "step": round(high / 100.0, 4) or 0.01}


def pattern_specs() -> List[Dict[str, Any]]:
    """Return ``[{name, params:[descriptor, ...]}]`` for every registered pattern.

    Parameters and their defaults come straight from each factory's signature, so
    the controls a pattern exposes are always in sync with its code.
    """
    specs: List[Dict[str, Any]] = []
    for name, factory in PATTERNS.items():
        params: List[Dict[str, Any]] = []
        try:
            sig = inspect.signature(factory)
        except (TypeError, ValueError):
            sig = None
        if sig is not None:
            for pname, p in sig.parameters.items():
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                if p.default is inspect.Parameter.empty:
                    continue
                try:
                    params.append(_param_descriptor(pname, p.default))
                except (TypeError, ValueError):
                    continue  # an unrepresentable param type just gets no UI control
        specs.append({"name": name, "params": params})
    return specs


def _coerce(name: str, default: Any, raw: str) -> Any:
    """Coerce a query string back to the type the constructor default implies."""
    if isinstance(default, (tuple, list)) and len(default) == 3:
        h = raw.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if isinstance(default, bool):
        return raw not in ("0", "false", "")
    if isinstance(default, int):
        return int(float(raw))
    return float(raw)


def render_frame(name: str, width: int, height: int, t: float,
                 raw_params: Dict[str, str]) -> bytes:
    """Render one frame to row-major RGB888 bytes using the live pattern code.

    ``raw_params`` are ``p_<name>`` query values; unknown or malformed ones are
    ignored so the pattern's own defaults apply.
    """
    width = max(1, min(MAX_DIM, width))
    height = max(1, min(MAX_DIM, height))
    factory = PATTERNS.get(name)
    if factory is None:
        raise KeyError(name)
    kwargs: Dict[str, Any] = {}
    try:
        sig = inspect.signature(factory)
        defaults = {n: p.default for n, p in sig.parameters.items()
                    if p.default is not inspect.Parameter.empty}
    except (TypeError, ValueError):
        defaults = {}
    for key, value in raw_params.items():
        pname = key[2:] if key.startswith("p_") else key
        if pname in defaults:
            try:
                kwargs[pname] = _coerce(pname, defaults[pname], value)
            except (ValueError, IndexError):
                pass  # leave the constructor default in place
    return get_pattern(name, **kwargs).render(width, height, t).to_bytes()


class _Handler(BaseHTTPRequestHandler):
    """Serves the single-page UI plus the ``/api/patterns`` and ``/api/frame`` endpoints."""

    server_version = "BlitzenWebDemo/0.1"

    def log_message(self, *_args) -> None:  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, content_type: str,
              extra: Dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, val in (extra or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib casing)
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/patterns":
            body = json.dumps(pattern_specs()).encode("utf-8")
            self._send(200, body, "application/json")
            return
        if path == "/api/frame":
            q = parse_qs(parsed.query)
            name = q.get("pattern", ["plasma"])[0]
            try:
                width = int(q.get("w", ["32"])[0])
                height = int(q.get("h", ["32"])[0])
                t = float(q.get("t", ["0"])[0])
            except ValueError:
                self._send(400, b"bad geometry", "text/plain")
                return
            params = {k: v[0] for k, v in q.items() if k.startswith("p_")}
            try:
                body = render_frame(name, width, height, t, params)
            except KeyError:
                self._send(404, b"unknown pattern", "text/plain")
                return
            width = max(1, min(MAX_DIM, width))
            height = max(1, min(MAX_DIM, height))
            self._send(200, body, "application/octet-stream",
                       {"X-Frame-Geometry": f"{width}x{height}",
                        "Cache-Control": "no-store"})
            return
        self._send(404, b"not found", "text/plain")


def serve(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True) -> None:
    """Run the playground server until interrupted."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{port}"
    print(f"Blitzen pattern playground on {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # headless / no browser — not fatal
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Browser playground for Blitzen patterns.")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="port (default 8080)")
    parser.add_argument("--no-open", dest="open_browser", action="store_false",
                        help="do not auto-open a browser")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, open_browser=args.open_browser)
    return 0


# --- The single-page UI. Plain string (not an f-string): the page fetches its own
#     pattern list from /api/patterns, so no server-side templating is needed and the
#     CSS/JS braces stay literal. -------------------------------------------------------
_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blitzen Pattern Playground</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         background: #0b0c10; color: #d7dbe0; }
  header { padding: 10px 16px; border-bottom: 1px solid #20232b;
           display: flex; align-items: baseline; gap: 12px; }
  header h1 { font-size: 15px; margin: 0; letter-spacing: .5px; }
  header .sub { color: #6b7280; font-size: 12px; }
  .wrap { display: flex; gap: 16px; align-items: flex-start; padding: 16px; flex-wrap: wrap; }
  .panel { background: #11131a; border: 1px solid #20232b; border-radius: 10px;
           padding: 14px; width: 300px; flex: 0 0 auto; }
  .panel h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
              color: #8b93a1; margin: 0 0 10px; }
  .ctl { display: grid; grid-template-columns: 92px 1fr 46px; align-items: center;
         gap: 8px; margin: 7px 0; }
  .ctl label { color: #9aa3b2; overflow: hidden; text-overflow: ellipsis; }
  .ctl .val { color: #cdd3db; text-align: right; font-variant-numeric: tabular-nums; }
  .ctl input[type=range] { width: 100%; }
  .ctl.full { grid-template-columns: 92px 1fr; }
  input, select, button { font: inherit; color: inherit; background: #0c0e14;
         border: 1px solid #2a2e38; border-radius: 6px; padding: 4px 6px; }
  input[type=number] { width: 100%; }
  input[type=color] { padding: 0; height: 26px; }
  select { width: 100%; }
  .stage { flex: 1 1 360px; min-width: 320px; }
  .canvas-box { background:
       repeating-conic-gradient(#15171d 0% 25%, #101218 0% 50%) 50% / 22px 22px;
       border: 1px solid #20232b; border-radius: 10px; padding: 16px;
       display: flex; justify-content: center; align-items: center; min-height: 300px; }
  canvas { image-rendering: pixelated; max-width: 100%; height: auto;
           border-radius: 4px; box-shadow: 0 0 0 1px #00000060, 0 10px 40px #0008; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .chip { cursor: pointer; padding: 4px 9px; font-size: 12px; }
  .chip:hover { border-color: #3b4150; }
  .toggle { display: flex; align-items: center; gap: 8px; margin: 7px 0; color: #9aa3b2; }
  .toggle input { width: auto; }
  .caption { margin-top: 10px; color: #8b93a1; display: flex; gap: 14px;
             justify-content: center; font-variant-numeric: tabular-nums; }
  .accent { color: #6ee7b7; }
  button.primary { background: #16321f; border-color: #2f6b45; color: #b9f3cf; }
  hr { border: none; border-top: 1px solid #20232b; margin: 12px 0; }
</style>
</head>
<body>
<header>
  <h1>⚡ Blitzen Pattern Playground</h1>
  <span class="sub">frames rendered by the real <code>host.patterns</code> code</span>
</header>
<div class="wrap">
  <div class="panel">
    <h2>Pattern</h2>
    <div class="ctl full"><label>name</label><select id="pattern"></select></div>
    <div id="params"></div>
    <hr>
    <h2>Playback</h2>
    <div class="ctl"><label>fps</label><input id="fps" type="range" min="1" max="60" step="1" value="30"><span class="val" id="fpsv">30</span></div>
    <div class="ctl"><label>time×</label><input id="speed" type="range" min="0" max="4" step="0.05" value="1"><span class="val" id="speedv">1.0</span></div>
    <div class="ctl"><label>scrub</label><input id="scrub" type="range" min="0" max="20" step="0.01" value="0"><span class="val" id="timev">0.0</span></div>
    <div class="row">
      <button class="chip primary" id="play">⏸ pause</button>
      <button class="chip" id="reset">↺ reset t</button>
    </div>
  </div>

  <div class="panel">
    <h2>Grid</h2>
    <div class="ctl"><label>panel w</label><input id="w" type="number" min="1" max="256" value="32"><span class="val"></span></div>
    <div class="ctl"><label>panel h</label><input id="h" type="number" min="1" max="256" value="32"><span class="val"></span></div>
    <div class="row">
      <button class="chip" data-w="32" data-h="32">32×32 panel</button>
      <button class="chip" data-w="8" data-h="32">8×32 array</button>
      <button class="chip" data-w="64" data-h="8">64×8 chain</button>
      <button class="chip" data-w="16" data-h="16">16×16</button>
      <button class="chip" data-w="64" data-h="64">64×64</button>
    </div>
    <hr>
    <h2>Layout</h2>
    <div class="ctl"><label>tiles →</label><input id="cols" type="range" min="1" max="6" step="1" value="1"><span class="val" id="colsv">1</span></div>
    <div class="ctl"><label>tiles ↓</label><input id="rows" type="range" min="1" max="6" step="1" value="1"><span class="val" id="rowsv">1</span></div>
    <div class="ctl full"><label>rotate</label><select id="rot">
      <option value="0">0°</option><option value="90">90°</option>
      <option value="180">180°</option><option value="270">270°</option></select></div>
    <label class="toggle"><input type="checkbox" id="serp"> serpentine wiring</label>
    <label class="toggle"><input type="checkbox" id="seams" checked> show panel seams</label>
    <hr>
    <h2>LED look</h2>
    <div class="ctl"><label>zoom</label><input id="scale" type="range" min="3" max="28" step="1" value="12"><span class="val" id="scalev">12</span></div>
    <div class="ctl"><label>gap</label><input id="gap" type="range" min="0" max="10" step="1" value="2"><span class="val" id="gapv">2</span></div>
    <label class="toggle"><input type="checkbox" id="round" checked> round pixels (LED)</label>
  </div>

  <div class="stage">
    <div class="canvas-box"><canvas id="screen" width="384" height="384"></canvas></div>
    <div class="caption">
      <span>res <span class="accent" id="resv">–</span></span>
      <span>pattern <span class="accent" id="patv">–</span></span>
      <span>fps <span class="accent" id="afps">–</span></span>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const canvas = $("screen"), ctx = canvas.getContext("2d");
let SPECS = {};

async function loadPatterns() {
  const list = await (await fetch("/api/patterns")).json();
  const sel = $("pattern");
  for (const spec of list) {
    SPECS[spec.name] = spec.params;
    const opt = document.createElement("option");
    opt.value = spec.name; opt.textContent = spec.name;
    sel.appendChild(opt);
  }
  sel.value = list.some(s => s.name === "plasma") ? "plasma" : list[0].name;
  buildParams();
}

function buildParams() {
  const params = SPECS[$("pattern").value] || [];
  const box = $("params");
  box.innerHTML = "";
  for (const p of params) {
    const row = document.createElement("div");
    const label = document.createElement("label");
    label.textContent = p.name; label.title = p.name;
    if (p.kind === "color") {
      row.className = "ctl full";
      const inp = document.createElement("input");
      inp.type = "color"; inp.value = "#" + p.default; inp.id = "p_" + p.name;
      row.append(label, inp);
    } else if (p.kind === "bool") {
      row.className = "ctl full";
      const wrap = document.createElement("label"); wrap.className = "toggle";
      const inp = document.createElement("input");
      inp.type = "checkbox"; inp.checked = p.default; inp.id = "p_" + p.name;
      wrap.append(inp, document.createTextNode(" " + p.name));
      box.appendChild(wrap); continue;
    } else {
      row.className = "ctl";
      const inp = document.createElement("input");
      inp.type = "range"; inp.min = p.min; inp.max = p.max;
      inp.step = p.step; inp.value = p.default; inp.id = "p_" + p.name;
      const val = document.createElement("span");
      val.className = "val"; val.textContent = fmt(p.default);
      inp.addEventListener("input", () => val.textContent = fmt(inp.value));
      row.append(label, inp, val);
    }
    box.appendChild(row);
  }
}
const fmt = (v) => { const n = +v; return Number.isInteger(n) ? String(n) : n.toFixed(2); };

function paramQuery() {
  let q = "";
  for (const p of SPECS[$("pattern").value] || []) {
    const el = $("p_" + p.name);
    if (!el) continue;
    let v = p.kind === "color" ? el.value.replace("#", "")
          : p.kind === "bool" ? (el.checked ? "1" : "0") : el.value;
    q += "&p_" + encodeURIComponent(p.name) + "=" + encodeURIComponent(v);
  }
  return q;
}

function src(rot, dx, dy, sw, sh) {
  if (rot === 0)   return [dx, dy];
  if (rot === 90)  return [dy, sh - 1 - dx];
  if (rot === 180) return [sw - 1 - dx, sh - 1 - dy];
  return [sw - 1 - dy, dx];                       // 270
}

function draw(buf, sw, sh) {
  const rot = +$("rot").value, serp = $("serp").checked, seams = $("seams").checked;
  const cell = +$("scale").value, gap = +$("gap").value, round = $("round").checked;
  const pw = +$("w").value, ph = +$("h").value;
  const cols = +$("cols").value, rows = +$("rows").value;
  const swap = rot === 90 || rot === 270;
  const dispW = swap ? sh : sw, dispH = swap ? sw : sh;
  canvas.width = dispW * cell; canvas.height = dispH * cell;
  ctx.fillStyle = "#08090d"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const inset = Math.min(gap, cell - 1);
  const seglist = [];
  for (let dy = 0; dy < dispH; dy++) {
    for (let dx = 0; dx < dispW; dx++) {
      const [sx, sy] = src(rot, dx, dy, sw, sh);
      let lx = sx;
      if (serp && (sy & 1)) lx = sw - 1 - sx;          // zigzag wiring on odd rows
      const i = (sy * sw + lx) * 3;
      ctx.fillStyle = "rgb(" + buf[i] + "," + buf[i + 1] + "," + buf[i + 2] + ")";
      const px = dx * cell, py = dy * cell;
      if (round) {
        const r = Math.max(0.5, (cell - inset) / 2);
        ctx.beginPath(); ctx.arc(px + cell / 2, py + cell / 2, r, 0, 6.2832); ctx.fill();
      } else {
        ctx.fillRect(px + inset / 2, py + inset / 2,
                     Math.max(1, cell - inset), Math.max(1, cell - inset));
      }
      if (seams && (cols > 1 || rows > 1)) {           // mark physical panel joins
        const pc = Math.floor(sx / pw), pr = Math.floor(sy / ph);
        if (dx > 0) { const [ax, ay] = src(rot, dx - 1, dy, sw, sh);
          if (Math.floor(ax / pw) !== pc || Math.floor(ay / ph) !== pr)
            seglist.push([px, py, px, py + cell]); }
        if (dy > 0) { const [ax, ay] = src(rot, dx, dy - 1, sw, sh);
          if (Math.floor(ax / pw) !== pc || Math.floor(ay / ph) !== pr)
            seglist.push([px, py, px + cell, py]); }
      }
    }
  }
  if (seglist.length) {
    ctx.strokeStyle = "#5eead4cc"; ctx.lineWidth = Math.max(1, cell / 8);
    ctx.beginPath();
    for (const s of seglist) { ctx.moveTo(s[0], s[1]); ctx.lineTo(s[2], s[3]); }
    ctx.stroke();
  }
  $("resv").textContent = dispW + "×" + dispH;
}

let t = 0, playing = true, lastWall = null, inFlight = false, scrubbing = false;
let frames = 0, fpsClock = null, shownFps = 0;

async function renderOnce() {
  const pw = +$("w").value, ph = +$("h").value;
  const cols = +$("cols").value, rows = +$("rows").value;
  const effW = Math.min(256, Math.max(1, pw * cols));
  const effH = Math.min(256, Math.max(1, ph * rows));
  const name = $("pattern").value;
  const url = "/api/frame?pattern=" + encodeURIComponent(name) +
              "&w=" + effW + "&h=" + effH + "&t=" + t.toFixed(4) + paramQuery();
  const resp = await fetch(url);
  if (!resp.ok) return;
  const geo = (resp.headers.get("X-Frame-Geometry") || (effW + "x" + effH)).split("x");
  const buf = new Uint8Array(await resp.arrayBuffer());
  draw(buf, +geo[0], +geo[1]);
  $("patv").textContent = name;
  frames++;
}

function loop() {
  const fps = +$("fps").value;
  setTimeout(loop, 1000 / Math.max(1, fps));
  const now = performance.now() / 1000;
  if (lastWall === null) lastWall = now;
  const dt = now - lastWall; lastWall = now;
  if (playing && !scrubbing) {
    t += dt * (+$("speed").value);
    $("scrub").value = (t % 20).toFixed(2);
    $("timev").textContent = t.toFixed(1);
  }
  if (fpsClock === null) fpsClock = now;
  if (now - fpsClock >= 1) { shownFps = frames; frames = 0; fpsClock = now;
                             $("afps").textContent = shownFps; }
  if (!inFlight) { inFlight = true; renderOnce().catch(() => {}).finally(() => inFlight = false); }
}

// --- wiring -------------------------------------------------------------------------
$("pattern").addEventListener("change", buildParams);
$("play").addEventListener("click", (e) => {
  playing = !playing; e.target.textContent = playing ? "⏸ pause" : "▶ play"; lastWall = null;
});
$("reset").addEventListener("click", () => { t = 0; $("scrub").value = 0; $("timev").textContent = "0.0"; });
const scrub = $("scrub");
scrub.addEventListener("mousedown", () => scrubbing = true);
scrub.addEventListener("touchstart", () => scrubbing = true);
window.addEventListener("mouseup", () => scrubbing = false);
window.addEventListener("touchend", () => scrubbing = false);
scrub.addEventListener("input", () => { t = +scrub.value; $("timev").textContent = t.toFixed(1); });
for (const [id, out] of [["fps","fpsv"],["speed","speedv"],["cols","colsv"],
                         ["rows","rowsv"],["scale","scalev"],["gap","gapv"]]) {
  $(id).addEventListener("input", () => $(out).textContent = fmt($(id).value));
}
document.querySelectorAll(".chip[data-w]").forEach((b) =>
  b.addEventListener("click", () => { $("w").value = b.dataset.w; $("h").value = b.dataset.h; }));

loadPatterns().then(loop);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
