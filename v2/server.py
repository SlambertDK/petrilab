"""
PetriLab v2 — server
====================
Runs the dish in a background thread, measures MODES every few gens, lets the
gardener tune ratios, and serves /api/state to the dashboard.
"""
import json
import os
import signal
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import sys
sys.path.insert(0, os.path.dirname(__file__))
from petrilab import Petri
from modes import Modes
from gardener import Gardener

HERE = os.path.dirname(__file__)
STATE_PATH = os.path.join(HERE, "data", "state.json")            # Petri sim state
BRAIN_PATH = os.path.join(HERE, "data", "gardener_brain.json")   # Gardener memory
FINDINGS_PATH = os.path.join(HERE, "data", "findings.md")        # durable conclusions
LOG_PATH = os.path.join(HERE, "data", "gardener_log.md")

SAVE_EVERY = 2000     # gens between persistence snapshots

# Control key: write endpoints (toggle/speed/param) require this secret in the
# X-Control-Key header. Read endpoints (/api/state, dashboard) stay public.
# Set via env PETRILAB_CONTROL_KEY; if unset, write endpoints are disabled
# entirely (fail closed) so a public URL can never touch server resources.
CONTROL_KEY = os.environ.get("PETRILAB_CONTROL_KEY", "").strip()


def _require_control(x_control_key: str | None):
    if not CONTROL_KEY or x_control_key != CONTROL_KEY:
        raise HTTPException(status_code=403, detail="control disabled")

sim = Petri()
modes = Modes()
gardener = Gardener(findings_path=FINDINGS_PATH)

_running = True
_speed = 200          # gens per loop batch
_viewers = {}         # anonymous viewer-id -> last-seen epoch (live-viewer count)
_last_modes = {}
_last_falsi = {}
_lock = threading.Lock()

MEASURE_EVERY = 10    # gens between MODES samples
GARDEN_EVERY = 50     # gens between gardener ticks


def _atomic_write(path, text):
    """Write to a tmp file then os.replace -> the target is never half-written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_state():
    """Persist the Petri sim AND the Gardener brain atomically. Caller holds
    _lock (or is in a context where the sim is not mutating)."""
    try:
        _atomic_write(STATE_PATH, json.dumps(sim.to_dict()))
    except Exception as e:
        print(f"[persist] sim save failed: {e}", flush=True)
    try:
        _atomic_write(BRAIN_PATH, json.dumps(gardener.to_dict()))
    except Exception as e:
        print(f"[persist] brain save failed: {e}", flush=True)


def _load_state():
    """Restore sim generation/cells/genomes and the gardener brain on startup so
    learning and progress survive restarts."""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                sim.load_dict(json.load(f))
            print(f"[persist] restored sim @ gen {sim.generation}, "
                  f"{len(sim.cells)} cells", flush=True)
        except Exception as e:
            print(f"[persist] sim load failed (fresh start): {e}", flush=True)
    if os.path.exists(BRAIN_PATH):
        try:
            with open(BRAIN_PATH) as f:
                gardener.load_dict(json.load(f))
            print(f"[persist] restored gardener brain: "
                  f"{gardener.experiments_run} experiments", flush=True)
        except Exception as e:
            print(f"[persist] brain load failed (fresh start): {e}", flush=True)


def _loop():
    global _last_modes, _last_falsi
    while True:
        if _running:
            with _lock:
                for _ in range(_speed):
                    sim.step()
                    if sim.generation % MEASURE_EVERY == 0:
                        rec, _census = modes.update(sim)
                        _last_modes = rec
                    if sim.generation % GARDEN_EVERY == 0:
                        _last_falsi = modes.falsification(sim)
                        gardener.observe(sim, _last_modes or {}, _last_falsi)
                    if sim.generation % SAVE_EVERY == 0:
                        _save_state()
        time.sleep(0.02)


app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)


def _build_state():
    with _lock:
        census = sim.lineage_census()
        nodes = [{"id": c.id, "x": round(c.x, 3), "y": round(c.y, 3),
                  "e": round(c.energy, 1), "a": round(c.activation, 2),
                  "lin": c.lineage_id, "g": len(c.genome)}
                 for c in sim.cells.values()]
        # Only send the strongest edges (by |weight|). At 1000+ edges the
        # extra lines are invisible clutter but dominate payload size; the
        # dashboard just draws faint links, so the top 250 is plenty.
        _edges = sorted(sim.edges, key=lambda e: -abs(e.weight))[:250]
        edges = [{"s": e.src, "d": e.dst, "w": round(e.weight, 2)} for e in _edges]
        return {
            "generation": sim.generation,
            "cell_count": len(sim.cells),
            "lineage_count": len(census),
            "nodes": nodes,
            "edges": edges,
            "params": sim.params_dict(),
            "modes": _last_modes,
            "modes_history": list(modes.history)[-300:],
            "falsification": _last_falsi,
            "gardener_log": gardener.log[-40:],
            "gardener": gardener.state(sim),
            "analysis": {
                "knobs": gardener.significance_report(),
                "complexity_trend": gardener.complexity_trend(),
            },
            "running": _running,
            "speed": _speed,
            "viewers": len(_viewers),
        }


@app.get("/api/state")
def api_state(v: str | None = None):
    # Live-viewer tracking: each client sends a stable anonymous id (?v=...).
    # We remember last-seen time per id; "viewers" = ids seen in the last 15s.
    now = time.time()
    if v:
        _viewers[v] = now
    cutoff = now - 15
    for vid in [k for k, t in _viewers.items() if t < cutoff]:
        del _viewers[vid]
    return JSONResponse(_build_state())


@app.post("/api/toggle")
def api_toggle(x_control_key: str | None = Header(default=None)):
    _require_control(x_control_key)
    global _running
    _running = not _running
    return {"ok": True, "running": _running}


@app.post("/api/speed/{value}")
def api_speed(value: int, x_control_key: str | None = Header(default=None)):
    _require_control(x_control_key)
    global _speed
    _speed = max(1, min(2000, int(value)))
    return {"ok": True, "speed": _speed}


@app.post("/api/param/{key}/{value}")
def api_param(key: str, value: float, x_control_key: str | None = Header(default=None)):
    _require_control(x_control_key)
    with _lock:
        ok = sim.set_param(key, value)
    return {"ok": ok, "key": key, "value": value}


@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(HERE, "dashboard.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "<h1>PetriLab v2</h1><p>dashboard.html not built yet</p>"


@app.get("/og-image.png")
def og_image():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(HERE, "og-image.png"), media_type="image/png")


@app.get("/deck", response_class=HTMLResponse)
def deck():
    path = os.path.join(HERE, "deck.html")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "<h1>PetriLab</h1><p>deck.html not found</p>"


@app.get("/paper", response_class=HTMLResponse)
def paper():
    path = os.path.join(HERE, "paper.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return "<h1>PetriLab</h1><p>paper.html not found</p>"


@app.get("/report", response_class=HTMLResponse)
def report():
    """Serve the most recent precomputed data-science report. A background thread
    rebuilds it periodically (see _report_loop) so the heavy permutation tests
    never run inside a request and never starve the sim's tick loop."""
    html = _REPORT.get("html")
    if html:
        return html
    # first-run fallback before the background build has finished
    return ("<h1>PetriLab report</h1><p>The statistical report is being computed "
            "for the first time — refresh in a few seconds.</p>")


@app.get("/api/report")
def api_report():
    models = _REPORT.get("models")
    if models:
        return JSONResponse(models)
    return JSONResponse({"status": "warming up"}, status_code=503)


_REPORT = {"html": None, "models": None, "built_at": 0}


def _report_loop(interval=120):
    """Rebuild the statistics report off the request path. Runs the expensive
    interaction permutation tests in a daemon thread; the GIL is released enough
    between numpy-free pure-Python loops that the sim keeps ticking, and requests
    only ever read the cached string."""
    import time
    import analytics
    while True:
        try:
            models = analytics.build_models()
            html = analytics.render_report(models)
            _REPORT["models"] = models
            _REPORT["html"] = html
            _REPORT["built_at"] = time.time()
        except Exception as e:
            if _REPORT["html"] is None:
                _REPORT["html"] = f"<h1>PetriLab report</h1><pre>report error: {e}</pre>"
        time.sleep(interval)


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    _load_state()   # restore sim + gardener brain BEFORE the loop starts

    def _on_signal(signum, frame):
        # clean shutdown (systemctl stop/restart sends SIGTERM) -> flush to disk
        with _lock:
            _save_state()
        print(f"[persist] saved on signal {signum}", flush=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    rt = threading.Thread(target=_report_loop, daemon=True)
    rt.start()
    port = int(os.environ.get("PETRILAB_PORT", "8770"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
