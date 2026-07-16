"""
Petri dish — parameter experiment (offline harness).
=====================================================
Runs its own petri dishes in memory. Does NOT touch the live sim on the server.

Answers three questions:
  1) What does each parameter do?   -> single-parameter sweep (low->high)
  2) What do combinations do?       -> pair interaction (2D grid)
  3) Robustness over time?          -> stability + shock recovery

TARGETS we record for each run (after settling):
  survival     : did the system survive to the end (0/1)
  nodes_mean   : avg. number of cells in the end window
  edges_mean   : avg. number of connections
  complexity   : emergence metric (structure x activity)
  modularity   : does it clump into modules
  cycles       : internal feedback loops
  persistence  : how long structures survive
  volatility   : std/mean of node count in the end window  (LOW = robust/stable)
  recovery     : after 50% of cells are removed at shock — what fraction
                 of the pre-shock level is regained within 400 gen
                 (>1 = full healing, <1 = permanently damaged, ~0 = collapse)

Robustness is defined in two parts:
  - STABILITY  = low volatility (doesn't swing wildly on its own)
  - RESILIENCE = high recovery (recovers after shock = resistant to change)
"""

import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Petri

# --- Parameters and their sweep intervals (low, default, high) ---
# The default values match engine.py.
PARAM_RANGES = {
    "energy_influx":   [2.0, 4.0, 8.0, 12.0, 20.0],
    "edge_cost":       [0.005, 0.01, 0.02, 0.04, 0.08],
    "node_upkeep":     [0.01, 0.025, 0.05, 0.1, 0.2],
    "grow_threshold":  [6.0, 9.0, 12.0, 16.0, 22.0],
    "mutation_rate":   [0.02, 0.08, 0.15, 0.3, 0.5],
    "prune_threshold": [0.01, 0.025, 0.05, 0.1, 0.2],
}
DEFAULTS = {
    "energy_influx": 8.0, "edge_cost": 0.02, "node_upkeep": 0.05,
    "grow_threshold": 12.0, "mutation_rate": 0.15, "prune_threshold": 0.05,
    # Environment mechanisms (default OFF = control)
    "seasons": 0.0, "season_len": 2000.0, "endogenous": 0.0,
    "catastrophe": 0.0, "catastrophe_kill": 0.4,
    "chemotaxis": 0.0, "sense_radius": 0.25,
    "heredity": 0.0, "heredity_struct": 0.0,
    "signaling": 0.0, "signal_radius": 0.2,
}

WARMUP = 1500      # generations before we start measuring (settling)
MEASURE = 800      # measurement window after warmup
SHOCK_RECOVER = 400  # generations to recover after shock
SEEDS = [11, 23, 42, 77, 101]   # more seeds = softens stochastic noise


def _measure_window(sim, n):
    """Run n generations, collect metric time series."""
    series = {"nodes": [], "edges": [], "complexity": [], "modularity": [],
              "cycles": [], "persistence": [], "spatial": []}
    for _ in range(n):
        sim.step()
        series["nodes"].append(len(sim.nodes))
        series["edges"].append(len(sim.edges))
        m = sim.last_metrics.get("metrics", {})
        series["complexity"].append(m.get("complexity", 0))
        series["modularity"].append(m.get("modularity", 0))
        series["cycles"].append(m.get("cycles", 0))
        series["persistence"].append(m.get("persistence", 0))
        series["spatial"].append(m.get("spatial", 0))
    return series


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else 0.0


def run_one(params, seed, do_shock=True):
    """One complete run: warmup -> measure -> shock -> measure recovery."""
    full = dict(DEFAULTS)
    full.update(params)
    sim = Petri(seed=seed, params=full)

    # 1) Settling
    for _ in range(WARMUP):
        sim.step()
        if not sim.nodes:
            break

    if not sim.nodes:
        return {"survival": 0, "nodes_mean": 0, "edges_mean": 0,
                "complexity": 0, "modularity": 0, "cycles": 0,
                "persistence": 0, "volatility": 0, "recovery": 0}

    # 2) Measurement window (baseline)
    phases_before = len(sim.metrics.phase_events)
    s = _measure_window(sim, MEASURE)
    phases_after = len(sim.metrics.phase_events)
    nodes_mean = _mean(s["nodes"])
    node_std = statistics.pstdev(s["nodes"]) if len(s["nodes"]) > 1 else 0.0
    volatility = (node_std / nodes_mean) if nodes_mean > 0 else 0.0
    # Innovation: phase transitions per 1000 gen = "does the system keep evolving"
    innovation = (phases_after - phases_before) / (MEASURE / 1000.0)

    result = {
        "survival": 1 if sim.nodes else 0,
        "nodes_mean": round(nodes_mean, 2),
        "edges_mean": round(_mean(s["edges"]), 2),
        "complexity": round(_mean(s["complexity"]), 3),
        "modularity": round(_mean(s["modularity"]), 3),
        "cycles": round(_mean(s["cycles"]), 2),
        "persistence": round(_mean(s["persistence"]), 2),
        "spatial": round(_mean(s["spatial"]), 3),
        "volatility": round(volatility, 3),
        "innovation": round(innovation, 3),
    }

    # 3) SHOCK: remove 50% of the cells at random -> measure recovery
    if do_shock and sim.nodes:
        pre = nodes_mean if nodes_mean > 0 else len(sim.nodes)
        victims = sim.rng.sample(list(sim.nodes), k=len(sim.nodes) // 2)
        for vid in victims:
            sim.nodes.pop(vid, None)
        sim.edges = [e for e in sim.edges if e.src in sim.nodes and e.dst in sim.nodes]
        for _ in range(SHOCK_RECOVER):
            sim.step()
            if not sim.nodes:
                break
        post = len(sim.nodes)
        result["recovery"] = round(post / pre, 3) if pre > 0 else 0.0
    else:
        result["recovery"] = None
    return result


def run_condition(label, params):
    """Run all seeds for one parameter configuration, aggregate."""
    runs = [run_one(params, s) for s in SEEDS]
    agg = {}
    keys = ["survival", "nodes_mean", "edges_mean", "complexity",
            "modularity", "cycles", "persistence", "spatial", "volatility",
            "recovery", "innovation"]
    for k in keys:
        vals = [r[k] for r in runs if r.get(k) is not None]
        agg[k] = round(statistics.mean(vals), 3) if vals else 0.0
    agg["label"] = label
    agg["params"] = params
    return agg


def sweep_single():
    """Question 1: what does each parameter do on its own?"""
    out = {}
    for pname, values in PARAM_RANGES.items():
        rows = []
        for v in values:
            label = f"{pname}={v}"
            rows.append(run_condition(label, {pname: v}))
            print(f"  {label:28s} -> nodes {rows[-1]['nodes_mean']:6.1f} "
                  f"cplx {rows[-1]['complexity']:6.2f} vol {rows[-1]['volatility']:.2f} "
                  f"recov {rows[-1]['recovery']}", flush=True)
        out[pname] = rows
    return out


def sweep_pairs():
    """Question 2: selected pair interactions (the most interesting tensions)."""
    pairs = [
        ("energy_influx", "edge_cost"),      # food vs. cost = the core tension
        ("grow_threshold", "mutation_rate"), # ease of growth vs. chaos
        ("edge_cost", "prune_threshold"),    # two forms of pruning
    ]
    lo_hi = {  # only low+high to keep it manageable (2x2 per pair)
        "energy_influx": [2.0, 20.0], "edge_cost": [0.005, 0.08],
        "grow_threshold": [6.0, 22.0], "mutation_rate": [0.02, 0.5],
        "prune_threshold": [0.01, 0.2],
    }
    out = []
    for a, b in pairs:
        for va in lo_hi[a]:
            for vb in lo_hi[b]:
                label = f"{a}={va} & {b}={vb}"
                res = run_condition(label, {a: va, b: vb})
                out.append(res)
                print(f"  {label:40s} -> nodes {res['nodes_mean']:6.1f} "
                      f"cplx {res['complexity']:6.2f} recov {res['recovery']}", flush=True)
    return out


def main():
    t0 = time.time()
    print("=== BASELINE (defaults) ===", flush=True)
    base = run_condition("defaults", {})
    print(f"  nodes {base['nodes_mean']} cplx {base['complexity']} "
          f"vol {base['volatility']} recov {base['recovery']}", flush=True)

    print("\n=== QUESTION 1: single-parameter sweep ===", flush=True)
    single = sweep_single()

    print("\n=== QUESTION 2: pair interactions ===", flush=True)
    pairs = sweep_pairs()

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": {
            "warmup": WARMUP, "measure": MEASURE,
            "shock_recover": SHOCK_RECOVER, "seeds": SEEDS,
            "shock": "50% of cells removed after baseline measurement",
        },
        "baseline": base,
        "single_sweep": single,
        "pair_sweep": pairs,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    outpath = os.path.join(os.path.dirname(__file__), "data", "param_experiment.json")
    with open(outpath, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nDone in {out['elapsed_sec']}s. Written to {outpath}", flush=True)


if __name__ == "__main__":
    main()
