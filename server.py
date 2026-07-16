"""
PetriLab web server.
Runs the simulation in a background thread, serves a live dashboard + JSON API.
Speed is controlled via a slider. Everything is persisted to disk every N generations.
"""

import asyncio
import os
import threading
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from engine import Petri

DATA = os.path.join(os.path.dirname(__file__), "data")
SAVE_PATH = os.path.join(DATA, "state.json")
os.makedirs(DATA, exist_ok=True)

# --- Global simulation ---
sim = Petri()
if os.path.exists(SAVE_PATH):
    try:
        sim.load(SAVE_PATH)
        print(f"[petri] reloaded gen {sim.generation}, seed {sim.seed}")
    except Exception as e:
        print(f"[petri] could not load: {e} — starting fresh")

# Shared state between thread and API
control = {"speed": 5.0, "running": True}  # generations per second
lock = threading.Lock()


def sim_loop():
    """Background thread. Runs the simulation at the speed the slider says."""
    last_save = time.time()
    while True:
        if control["running"]:
            with lock:
                sim.step()
            # periodic save
            if time.time() - last_save > 15:
                with lock:
                    sim.save(SAVE_PATH)
                last_save = time.time()
        spd = max(0.1, control["speed"])
        time.sleep(1.0 / spd)


threading.Thread(target=sim_loop, daemon=True).start()

app = FastAPI(title="PetriLab")


@app.get("/api/state")
def api_state():
    with lock:
        return JSONResponse(sim.snapshot())


@app.get("/api/control")
def api_control():
    return control


@app.post("/api/speed/{value}")
def api_speed(value: float):
    control["speed"] = max(0.1, min(200.0, value))
    return control


@app.post("/api/toggle")
def api_toggle():
    control["running"] = not control["running"]
    return control


@app.post("/api/param/{key}/{value}")
def api_param(key: str, value: float):
    with lock:
        ok = sim.set_param(key, value)
    return {"ok": ok, "key": key, "value": value}


@app.post("/api/reset")
def api_reset():
    global sim
    with lock:
        sim = Petri()
    return {"ok": True, "seed": sim.seed}


@app.post("/api/cpucap/{percent}")
def api_cpucap(percent: int):
    """Set the CPU cap for the service (observer's frame, not the engine's rule)."""
    import subprocess
    pct = max(5, min(100, percent))
    try:
        subprocess.run(
            ["systemctl", "--user", "set-property", "petriskal.service",
             f"CPUQuota={pct}%"],
            check=True, capture_output=True, timeout=10,
        )
        return {"ok": True, "cpu_cap": pct}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/logbog")
def api_logbog():
    path = os.path.join(DATA, "logbog.md")
    if not os.path.exists(path):
        return JSONResponse({"lines": []})
    with open(path) as f:
        lines = f.readlines()
    return JSONResponse({"lines": [l.rstrip() for l in lines[-100:]]})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PetriLab</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;background:#0a0e14;color:#c9d1d9;
       font:14px/1.5 system-ui,-apple-system,sans-serif}
  /* ---------- TOPBAR ---------- */
  #top{display:flex;gap:10px 18px;align-items:center;padding:10px 16px;
       background:#0d1117;border-bottom:1px solid #21262d;flex-wrap:wrap}
  #top b{color:#58a6ff;font-size:16px;letter-spacing:.3px}
  #topstats{display:flex;gap:10px 16px;flex-wrap:wrap;align-items:center;flex:1;min-width:0}
  .stat{color:#8b949e;white-space:nowrap}.stat span{color:#c9d1d9;font-weight:600}
  #topbtns{display:flex;gap:8px;align-items:center;margin-left:auto}
  .iconbtn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;
           padding:6px 12px;cursor:pointer;font-size:13px;font-weight:600;line-height:1}
  .iconbtn:hover{background:#30363d}
  #helpbtn{background:#1f6feb;border-color:#1f6feb;color:#fff}
  #helpbtn:hover{background:#388bfd}
  /* ---------- EMERGENS-GRID ---------- */
  #emergewrap{padding:10px 16px;background:#0d1117;border-bottom:1px solid #21262d}
  #emergehead{color:#58a6ff;font-weight:600;font-size:12px;letter-spacing:.5px;
              margin-bottom:8px}
  #emerge{display:grid;gap:8px;
          grid-template-columns:repeat(auto-fit,minmax(104px,1fr))}
  .metric{background:#161b22;border:1px solid #21262d;border-radius:8px;
          padding:8px 10px;min-width:0}
  .metric .k{color:#8b949e;font-size:10px;text-transform:uppercase;letter-spacing:.4px;
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .metric .v{color:#58a6ff;font-size:20px;font-weight:700;line-height:1.2}
  /* ---------- STAGE (graf + net) ---------- */
  #stage{display:flex;gap:0;height:calc(100vh - 340px);min-height:300px}
  #trend{flex:1;background:#080b10;display:block;min-width:0}
  #netwrap{width:320px;border-left:1px solid #21262d;position:relative;background:#0a0e14}
  #netlabel{position:absolute;top:6px;left:8px;font-size:11px;color:#6e7681;z-index:2}
  #c{display:block;width:100%;height:100%}
  #legend{display:flex;gap:16px;padding:6px 16px;background:#0d1117;font-size:11px;
          border-top:1px solid #21262d;border-bottom:1px solid #21262d;flex-wrap:wrap}
  /* ---------- KONTROLPANEL (bag tandhjul) ---------- */
  #ctrl{padding:12px 16px;background:#0d1117;
        display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}
  #ctrl.hidden{display:none}
  label{color:#8b949e;font-size:12px}
  input[type=range]{vertical-align:middle;width:180px;max-width:60vw}
  button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;
         border-radius:6px;padding:6px 14px;cursor:pointer}
  button:hover{background:#30363d}
  /* ---------- MOBIL ---------- */
  @media (max-width:720px){
    #top{gap:8px 12px;padding:10px 12px}
    #top b{font-size:15px}
    #topstats{font-size:12px;gap:6px 12px;order:3;flex-basis:100%}
    #topbtns{order:2}
    #emergewrap{padding:8px 12px}
    #emerge{grid-template-columns:repeat(3,1fr);gap:6px}
    .metric{padding:6px 8px}
    .metric .v{font-size:16px}
    .metric .k{font-size:9px}
    #stage{flex-direction:column;height:auto;min-height:0}
    #trend{width:100%;height:44vh;min-height:230px}
    #netwrap{width:100%;height:24vh;min-height:150px;
             border-left:none;border-top:1px solid #21262d}
    #ctrl{gap:16px;padding:12px}
    input[type=range]{width:100%;max-width:none}
    #ctrl label{flex-basis:100%}
  }
  @media (max-width:400px){ #emerge{grid-template-columns:repeat(2,1fr)} }
  #logwrap{max-height:88px;overflow-y:auto;padding:6px 16px;background:#080b10;
           border-top:1px solid #21262d;font-size:12px;color:#8b949e}
  #logwrap div{padding:1px 0}
  .phase{color:#d29922;font-weight:600}
  /* --- Help overlay --- */
  #helpbtn{margin-left:auto;background:#1f6feb;border-color:#1f6feb;color:#fff;
           font-weight:600;padding:5px 12px}
  #helpbtn:hover{background:#388bfd}
  .stat[data-tip],.metric[data-tip]{cursor:help;position:relative}
  .stat[data-tip]:hover::after,.metric[data-tip]:hover::after{
    content:attr(data-tip);position:absolute;left:0;top:100%;margin-top:6px;z-index:50;
    width:230px;background:#161b22;border:1px solid #30363d;border-radius:6px;
    padding:8px 10px;font-size:12px;font-weight:400;line-height:1.4;color:#c9d1d9;
    box-shadow:0 6px 20px rgba(0,0,0,.5);white-space:normal;text-transform:none}
  #overlay{display:none;position:fixed;inset:0;background:rgba(3,6,10,.82);z-index:100;
           overflow-y:auto;padding:40px 16px}
  #overlay.show{display:block}
  #helpcard{max-width:760px;margin:0 auto;background:#0d1117;border:1px solid #30363d;
            border-radius:12px;padding:28px 32px;box-shadow:0 12px 48px rgba(0,0,0,.6)}
  #helpcard h1{color:#58a6ff;font-size:22px;margin:0 0 4px}
  #helpcard .sub{color:#8b949e;margin:0 0 20px;font-size:13px}
  #helpcard h2{color:#3fb950;font-size:15px;margin:22px 0 8px;
               border-bottom:1px solid #21262d;padding-bottom:4px}
  #helpcard dl{margin:0}
  #helpcard dt{color:#c9d1d9;font-weight:600;margin-top:12px}
  #helpcard dd{color:#8b949e;margin:2px 0 0;font-size:13px;line-height:1.5}
  #helpcard .tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;
                 background:#161b22;border:1px solid #30363d;color:#8b949e;margin-left:6px}
  #helpclose{position:sticky;top:0;float:right;background:#21262d;border:1px solid #30363d;
             color:#c9d1d9;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:18px}
  #helpcard a{color:#58a6ff}
</style></head><body>
<div id="top">
  <b>PetriLab</b>
  <div id="topstats">
    <span class="stat" data-tip="Random starting seed. Same seed = same run (reproducible for research).">seed <span id="seed">–</span></span>
    <span class="stat" data-tip="Generation = one time step of the simulation. The system's 'age'.">gen <span id="gen">0</span></span>
    <span class="stat" data-tip="Number of living cells right now. Grows and shrinks with energy and pressure.">nodes <span id="nodes">0</span></span>
    <span class="stat" data-tip="Number of connections between cells. This is where structure and complexity live.">edges <span id="edges">0</span></span>
    <span class="stat" data-tip="Total energy in the system. Falls in winter, rises in summer.">energy <span id="energy">0</span></span>
    <span class="stat" id="season" data-tip="The season. Seasons make the light (energy) oscillate cyclically — winter squeezes, summer gives abundance. It forces the system to keep adapting.">🌍 <span id="season_txt">–</span></span>
    <span class="stat" id="status" style="color:#3fb950">● running</span>
  </div>
  <div id="topbtns">
    <button id="settingsbtn" class="iconbtn" title="Settings (your frame)">⚙︎</button>
    <button id="helpbtn" class="iconbtn">❔ About</button>
  </div>
</div>
<div id="emergewrap">
  <div id="emergehead">EMERGENCE</div>
  <div id="emerge">
  <div class="metric" style="border-color:#3fb950" data-tip="KEY METRIC. Phase transitions per 1000 generations = how much the system KEEPS evolving. Near 0 = dead equilibrium (homeostasis). High (>5) = open-ended, the system still invents new things.">
    <div class="k">innovation</div><div class="v" id="m_innovation" style="color:#3fb950">–</div></div>
  <div class="metric" data-tip="How rich the system's structure is (information content in the connections). High = advanced, non-trivial patterns. Driven mostly by cheap connections + high mutation.">
    <div class="k">complexity</div><div class="v" id="m_complexity">–</div></div>
  <div class="metric" data-tip="How much the system clusters into separate modules/groups — the earliest form of 'organs'. High = specialized clusters rather than one big soup.">
    <div class="k">modularity</div><div class="v" id="m_modularity">–</div></div>
  <div class="metric" data-tip="Number of closed loops (feedback cycles) in the network. Cycles = the system can keep information circulating, a prerequisite for memory and computation.">
    <div class="k">cycles</div><div class="v" id="m_cycles">–</div></div>
  <div class="metric" data-tip="How deep signals can travel through the network (longest chain). Depth = computational power — how many steps the system can 'think' in.">
    <div class="k">depth</div><div class="v" id="m_depth">–</div></div>
  <div class="metric" data-tip="How stable the structures are over time — do the same patterns survive, or dissolve? High = durable, robust structures.">
    <div class="k">persistence</div><div class="v" id="m_persistence">–</div></div>
  <div class="metric" style="border-color:#a371f7" data-tip="Spatial coherence: do connected cells cluster physically together (organized tissue), or lie scattered? 0 = random spread. High = self-organization. Driven by receptors + chemotaxis.">
    <div class="k">spatial</div><div class="v" id="m_spatial" style="color:#a371f7">–</div></div>
  <div class="metric" style="border-color:#3fb950" data-tip="Communication (phase 3): how strongly do cells use the wireless signaling layer? 0 = no signaling. High = cells 'talk' chemically without wires.">
    <div class="k">communication</div><div class="v" id="m_comm" style="color:#3fb950">–</div></div>
  <div class="metric" style="border-color:#d29922" data-tip="Total number of times a metric made a sudden jump (qualitative change). Each transition = a possible 'evolutionary moment'. Shown as yellow lines in the graph.">
    <div class="k">phase transitions</div><div class="v" id="m_phases" style="color:#d29922">0</div></div>
  </div>
</div>
<div id="stage">
  <canvas id="trend"></canvas>
  <div id="netwrap"><span id="netlabel">living network</span><canvas id="c"></canvas></div>
</div>
<div id="legend">
  <span style="color:#58a6ff">■ complexity</span>
  <span style="color:#3fb950">■ persistence</span>
  <span style="color:#8b949e">■ nodes</span>
  <span style="color:#d29922">▏phase transition</span>
</div>
<div id="logwrap"><div style="color:#58a6ff">Gardener interventions (full logbook in repo)</div></div>
<div id="ctrl" class="hidden">
  <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
    <span style="color:#58a6ff;font-weight:600;font-size:12px">YOUR FRAME</span>
    <span><button id="toggle">Pause</button>
          <button id="reset">Reset</button></span>
    <label>Speed (gen/sec): <span id="spd">5</span><br>
      <input id="speed" type="range" min="0.5" max="60" step="0.5" value="5" style="width:180px"></label>
    <label>CPU cap (%): <span id="cpuv">40</span><br>
      <input id="cpu" type="range" min="5" max="100" step="5" value="40" style="width:180px"></label>
  </div>
  <div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin-top:10px;
              padding-top:10px;border-top:1px solid #21262d">
    <span style="color:#8b949e;font-weight:600;font-size:12px" data-tip="These conditions are driven by the gardener robot as part of its experiments. They are shown here so you can follow along — but locked, so your data and the gardener's don't mix.">🌱 GARDENER'S CONDITIONS <span style="font-weight:400">(locked)</span></span>
    <span class="stat" data-tip="How much light/energy drips in.">energy: <span id="g_influx" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Connection cost. The most important complexity knob.">cost: <span id="g_cost" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Mutation rate. Strongest driver of complexity.">mutation: <span id="g_mut" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Season amplitude (0 = none, higher = stronger seasons).">season: <span id="g_season" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Chemotaxis (phase 1): 0 = cells scattered randomly. >0 = receptors + attraction, cells organize into tissue.">chemotaxis: <span id="g_chemo" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Heredity (phase 2 v2): 0 = random. >0 = daughter inherits mother's connection pattern + genes = structural heredity that carries selection.">heredity: <span id="g_hered" style="color:#c9d1d9;font-weight:600">–</span></span>
    <span class="stat" data-tip="Signaling (phase 3): 0 = none. >0 = cells emit signaling molecules and affect receptor-bearing neighbors wirelessly. Keeps the system in perpetual change.">signaling: <span id="g_sig" style="color:#c9d1d9;font-weight:600">–</span></span>
  </div>
</div>
<div id="overlay">
  <div id="helpcard">
    <button id="helpclose">✕</button>
    <h1>PetriLab — what are you looking at?</h1>
    <p class="sub">A digital petri dish: cells grow, connect and die under fixed natural laws. The goal is to see whether <b>real complexity arises on its own</b> — and to capture it with numbers, not gut feeling.</p>

    <h2>The big idea</h2>
    <p style="color:#8b949e;font-size:13px;line-height:1.6">The rules (the system's "physics") are <b>fixed and untouchable</b> — that's the proof. Only the <b>conditions</b> (energy, costs, seasons) may change. The question we chase: can a system under the right conditions keep evolving instead of settling into a dead equilibrium (homeostasis)?</p>

    <h2>The top bar — the system's pulse</h2>
    <dl>
      <dt>seed</dt><dd>The starting randomness kernel. The same seed gives exactly the same run — so experiments can be repeated.</dd>
      <dt>gen</dt><dd>Generation: the simulation's time step. The system's age.</dd>
      <dt>nodes / edges</dt><dd>Number of living cells and connections between them. Complexity lives in the connections, not in the number of cells.</dd>
      <dt>energy</dt><dd>Total energy in the system. Oscillates with the seasons.</dd>
      <dt>🌍 season</dt><dd>Seasons make the light oscillate cyclically: ❄️ winter (scarcity) → 🌤️ spring → ☀️ summer (abundance) → 🍂 autumn. The shift forces the system to adapt again and again.</dd>
    </dl>

    <h2>The emergence numbers — are we measuring life?</h2>
    <dl>
      <dt>innovation <span class="tag">key metric</span></dt><dd>Phase transitions per 1000 generations. <b>The core question:</b> is the system still evolving? Near 0 = dead equilibrium. Above 5 = open-ended, it still invents new things.</dd>
      <dt>complexity</dt><dd>How rich and non-trivial the structure is. Driven by cheap connections and high mutation.</dd>
      <dt>modularity</dt><dd>How much the system clusters into separate groups — the earliest form of "organs".</dd>
      <dt>cycles</dt><dd>Closed feedback loops. A prerequisite for memory and computation.</dd>
      <dt>depth</dt><dd>How many steps a signal can travel — the system's "thinking depth".</dd>
      <dt>persistence</dt><dd>How stable the structures are over time. High = durable, robust patterns.</dd>
      <dt>spatial <span class="tag">phase 1</span></dt><dd>Spatial coherence: do connected cells cluster physically together as organized tissue (high), or lie scattered randomly (0)? Driven by receptors + chemotaxis. The first sign of self-organization you can SEE.</dd>
      <dt>communication <span class="tag">phase 3</span></dt><dd>How strongly do cells use the wireless signaling layer? 0 = no signaling. High = cells emit and sense signaling molecules and "talk" chemically without being wired.</dd>
      <dt>phase transitions</dt><dd>Number of sudden jumps in a metric. Each jump = a possible evolutionary moment. Shown as yellow lines in the graph.</dd>
    </dl>

    <h2>The graph & the network</h2>
    <dl>
      <dt>Trend graph (left)</dt><dd>Metrics over time: <span style="color:#58a6ff">complexity</span>, <span style="color:#3fb950">persistence</span> and <span style="color:#8b949e">nodes</span>. <span style="color:#d29922">Yellow vertical lines</span> = phase transitions. Here you see whether the system is rising, falling or standing still.</dd>
      <dt>Living network (right)</dt><dd>A snapshot of the cells and their connections. Nice to look at — but remember: <b>emergence is statistical, not visual.</b> The numbers tell you more than the dots.</dd>
    </dl>

    <h2>The controls — two roles</h2>
    <p style="color:#8b949e;font-size:13px;line-height:1.6"><b style="color:#58a6ff">Your frame</b> is the observer's tool: you do <b>not</b> control the experiment itself, only the frame around it.</p>
    <dl>
      <dt>Speed</dt><dd>How fast the simulation runs. Affects only the display, not the system's nature.</dd>
      <dt>CPU cap</dt><dd>What fraction of the server's CPU the dish may use. Your safety valve — so it never slows anything else down. Changes nothing about the experiment, only its resource use.</dd>
      <dt>Pause / Reset</dt><dd>Freeze or restart. Reset costs all life.</dd>
    </dl>
    <p style="color:#8b949e;font-size:13px;line-height:1.6;margin-top:14px"><b style="color:#3fb950">The gardener's conditions</b> are locked for you on purpose: energy, cost, mutation and season are <b>the gardener's experiment knobs</b>. If you and the robot both turned the same conditions, your data would mix and the evidence chain would be useless. You can follow the values live — but it's the robot that does the research.</p>

    <h2>The gardener</h2>
    <p style="color:#8b949e;font-size:13px;line-height:1.6">An autonomous robot tends the dish every 6 hours. It may adjust the <b>conditions</b> (not the rules), forms its own hypotheses, tests them and writes everything to the logbook. At the bottom you see its latest intervention. The full evidence chain lives in the repository.</p>

    <p class="sub" style="margin-top:24px">Press <b>Esc</b> or ✕ to close. Enjoy the dish. 🧫</p>
  </div>
</div>
<script>
const cv=document.getElementById('c'),cx=cv.getContext('2d');
const tr=document.getElementById('trend'),tcx=tr.getContext('2d');
function resize(){
  // Network canvas follows its wrapper; trend canvas follows its flex area
  const nw=document.getElementById('netwrap');
  cv.width=nw.clientWidth;cv.height=nw.clientHeight;
  tr.width=tr.clientWidth;tr.height=tr.clientHeight;
}
resize();addEventListener('resize',resize);

async function post(u){return fetch(u,{method:'POST'}).then(r=>r.json())}

document.getElementById('speed').oninput=e=>{
  document.getElementById('spd').textContent=e.target.value;
  post('/api/speed/'+e.target.value)};
document.getElementById('cpu').oninput=e=>{
  document.getElementById('cpuv').textContent=e.target.value};
document.getElementById('cpu').onchange=e=>{
  post('/api/cpucap/'+e.target.value)};
document.getElementById('toggle').onclick=async()=>{
  const c=await post('/api/toggle');
  document.getElementById('toggle').textContent=c.running?'Pause':'Resume';
  document.getElementById('status').textContent=c.running?'● running':'❚❚ paused';
  document.getElementById('status').style.color=c.running?'#3fb950':'#d29922'};
document.getElementById('reset').onclick=async()=>{
  if(confirm('Reset the petri dish? All life is lost.'))await post('/api/reset')};

function draw(s){
  cx.fillStyle='#0a0e14';cx.fillRect(0,0,cv.width,cv.height);
  const W=cv.width,H=cv.height,pad=26;
  if(!s.nodes.length)return;
  // AUTO-ZOOM: find the nodes' bounding box and scale so the cluster fills the field.
  // Without this, a few dense cells (chemotaxis) become a single dot.
  let minX=1,maxX=0,minY=1,maxY=0;
  s.nodes.forEach(n=>{minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x);
                      minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y);});
  let spanX=maxX-minX,spanY=maxY-minY;
  // avoid division by zero + keep a reasonable zoom cap for very dense clusters
  spanX=Math.max(spanX,0.05);spanY=Math.max(spanY,0.05);
  const cx0=(minX+maxX)/2,cy0=(minY+maxY)/2;
  // equal scale on both axes (preserve shape), fill ~90% of the field
  const sc=Math.min((W-2*pad)/spanX,(H-2*pad)/spanY)*0.9;
  const px=n=>W/2+(n.x-cx0)*sc, py=n=>H/2+(n.y-cy0)*sc;
  const pos={};s.nodes.forEach(n=>pos[n.id]=n);
  // edges
  cx.lineWidth=0.6;
  s.edges.forEach(e=>{const a=pos[e.s],b=pos[e.d];if(!a||!b)return;
    cx.strokeStyle=e.w>0?'rgba(88,166,255,0.28)':'rgba(248,81,73,0.22)';
    cx.beginPath();cx.moveTo(px(a),py(a));cx.lineTo(px(b),py(b));cx.stroke()});
  // nodes
  s.nodes.forEach(n=>{const r=3.5+Math.min(9,n.e/3);
    const g=Math.floor(120+n.a*100);
    cx.fillStyle=`rgb(${80},${g},${140})`;
    cx.beginPath();cx.arc(px(n),py(n),r,0,7);cx.fill()});
}
function drawTrend(h){
  const W=tr.width,H=tr.height,padL=6,padB=16,padT=10;
  tcx.fillStyle='#080b10';tcx.fillRect(0,0,W,H);
  if(!h||h.length<2){tcx.fillStyle='#6e7681';tcx.font='12px system-ui';
    tcx.fillText('gathering data …',12,24);return;}
  const gw=W-padL*2, gh=H-padB-padT;
  const xAt=i=>padL+i/(h.length-1)*gw;
  // Phase-transition markers: a vertical line each time the phases counter rises
  tcx.strokeStyle='rgba(210,153,34,0.35)';tcx.lineWidth=1;
  for(let i=1;i<h.length;i++){
    if((h[i].phases||0)>(h[i-1].phases||0)){
      const x=xAt(i);tcx.beginPath();tcx.moveTo(x,padT);tcx.lineTo(x,padT+gh);tcx.stroke();
    }
  }
  // Helper: draw a metric normalized to its own max (own scale)
  function line(key,col,lw){
    const max=Math.max(...h.map(d=>d[key]||0),1e-6);
    tcx.strokeStyle=col;tcx.lineWidth=lw||1.5;tcx.beginPath();
    h.forEach((d,i)=>{const x=xAt(i),y=padT+gh-(d[key]||0)/max*gh*0.94;
      i?tcx.lineTo(x,y):tcx.moveTo(x,y)});tcx.stroke();
  }
  line('nodes','#8b949e',1);
  line('pers','#3fb950',1.5);
  line('cplx','#58a6ff',2);
  // x-axis label: generation span
  tcx.fillStyle='#6e7681';tcx.font='10px system-ui';
  tcx.fillText('gen '+h[0].gen,padL,H-4);
  const lbl='gen '+h[h.length-1].gen;
  tcx.fillText(lbl,W-padL-tcx.measureText(lbl).width,H-4);
}
async function tick(){
  try{const s=await(await fetch('/api/state')).json();
    document.getElementById('seed').textContent=s.seed;
    document.getElementById('gen').textContent=s.generation;
    document.getElementById('nodes').textContent=s.nodes.length;
    document.getElementById('edges').textContent=s.edges.length;
    document.getElementById('energy').textContent=
      s.nodes.reduce((a,n)=>a+n.e,0).toFixed(0);
    // Season indicator: phase -1 (winter/scarcity) .. +1 (summer/abundance)
    const sp=s.season_phase;
    const sEl=document.getElementById('season');
    if(sp===null||sp===undefined){sEl.style.display='none';}
    else{
      sEl.style.display='';
      let icon,txt;
      if(sp>0.5){icon='☀️';txt='summer';}
      else if(sp>0){icon='🌤️';txt='spring';}
      else if(sp>-0.5){icon='🍂';txt='autumn';}
      else{icon='❄️';txt='winter';}
      document.getElementById('season_txt').textContent=txt+' '+(sp>=0?'+':'')+sp.toFixed(2);
      sEl.firstChild.textContent=icon+' ';
    }
    const em=s.emergence||{};
    for(const k of ['complexity','modularity','cycles','depth','persistence','spatial','comm']){
      const el=document.getElementById('m_'+k);
      if(el&&em[k]!==undefined)el.textContent=em[k];
    }
    document.getElementById('m_phases').textContent=(s.phase_events||[]).length;
    // Innovation = faseovergange pr. 1000 gen over historik-vinduet
    const h=s.history||[];
    if(h.length>1){
      const dgen=(h[h.length-1].gen-h[0].gen)||1;
      const dph=(h[h.length-1].phases||0)-(h[0].phases||0);
      const innov=dgen>0?Math.max(0,dph/dgen*1000):0;
      document.getElementById('m_innovation').textContent=innov.toFixed(1);
    }
    draw(s);drawTrend(h);
    // The gardener's locked conditions (display only)
    const p=s.params||{};
    const g=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v};
    g('g_influx',p.energy_influx);g('g_cost',p.edge_cost);
    g('g_mut',p.mutation_rate);g('g_season',p.seasons??0);
    g('g_chemo',p.chemotaxis??0);
    g('g_hered',(p.heredity_struct||p.heredity)??0);
    g('g_sig',p.signaling??0);
  }catch(e){}
}
async function tickLog(){
  try{const d=await(await fetch('/api/logbog')).json();
    const w=document.getElementById('logwrap');
    const head=w.firstElementChild;
    w.innerHTML='';w.appendChild(head);
    // Show only the gardener's interventions + catastrophes — not report body text
    const rows=d.lines.filter(l=>/gardener|CATASTROPHE|intervention|adjusted|gartner|KATASTROFE|indgreb|justerede/i.test(l));
    const show=(rows.length?rows:d.lines.slice(-6));
    show.slice().reverse().slice(0,12).forEach(l=>{
      const div=document.createElement('div');
      if(/KATASTROFE|CATASTROPHE/.test(l))div.className='phase';
      div.textContent=l.replace(/\\*\\*/g,'').replace(/^- /,'');
      w.appendChild(div);
    });
  }catch(e){}
}
setInterval(tick,500);tick();
setInterval(tickLog,4000);tickLog();
// Help overlay: open/close the about overlay
const ov=document.getElementById('overlay');
document.getElementById('helpbtn').onclick=()=>ov.classList.add('show');
document.getElementById('helpclose').onclick=()=>ov.classList.remove('show');
ov.onclick=e=>{if(e.target===ov)ov.classList.remove('show')};
addEventListener('keydown',e=>{if(e.key==='Escape')ov.classList.remove('show')});
// Tandhjul: vis/skjul kontrolpanel (din ramme). Skjult som standard.
const ctrl=document.getElementById('ctrl');
document.getElementById('settingsbtn').onclick=()=>{
  ctrl.classList.toggle('hidden');
  if(!ctrl.classList.contains('hidden'))ctrl.scrollIntoView({behavior:'smooth',block:'nearest'});
};
</script></body></html>"""
