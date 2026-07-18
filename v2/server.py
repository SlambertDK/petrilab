"""
PetriLab v2 — server
====================
Runs the dish in a background thread, measures MODES every few gens, lets the
gardener tune ratios, and serves /api/state to the dashboard.
"""
import json
import os
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import sys
sys.path.insert(0, os.path.dirname(__file__))
from petrilab import Petri
from modes import Modes
from gardener import Gardener

HERE = os.path.dirname(__file__)
STATE_PATH = os.path.join(HERE, "data", "state.json")
LOG_PATH = os.path.join(HERE, "data", "gardener_log.md")

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
gardener = Gardener()

_running = True
_speed = 200          # gens per loop batch
_last_modes = {}
_last_falsi = {}
_lock = threading.Lock()

MEASURE_EVERY = 10    # gens between MODES samples
GARDEN_EVERY = 50     # gens between gardener ticks


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
        time.sleep(0.02)


app = FastAPI()


def _build_state():
    with _lock:
        census = sim.lineage_census()
        nodes = [{"id": c.id, "x": round(c.x, 3), "y": round(c.y, 3),
                  "e": round(c.energy, 1), "a": round(c.activation, 2),
                  "lin": c.lineage_id, "g": len(c.genome)}
                 for c in sim.cells.values()]
        edges = [{"s": e.src, "d": e.dst, "w": round(e.weight, 2)} for e in sim.edges]
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
            "running": _running,
            "speed": _speed,
        }


@app.get("/api/state")
def api_state():
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


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PETRILAB_PORT", "8770"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
