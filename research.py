"""
Petri dish — autonomous research engine.
=========================================
Not a simulation we tinker with, but a machine that runs the
scientific method: form hypothesis -> predict -> test -> judge ->
register -> learn. Tries solutions, rejects hypotheses, finds new ones.

TWO LAYERS:
  CODE (this file): register, executor, judge, finding log. Mechanical,
                    deterministic, free. No AI.
  REASONING (gardener cron): proposes hypotheses, interprets, decides
                    what to test next, concludes. Creative.

A hypothesis is a JSON record with a FALSIFIABLE prediction:
  {
    "id": "H0007",
    "claim": "human-readable claim",
    "param": "edge_cost",          # what we vary (or 'custom')
    "test": {                       # how we test
        "kind": "compare",          # compare two conditions
        "a": {"edge_cost": 0.02},   # control
        "b": {"edge_cost": 0.005},  # treatment
        "metric": "complexity",     # which outcome we look at
        "direction": "b>a",         # the prediction: b higher than a
        "min_effect": 0.15          # smallest relative difference to "count"
    },
    "status": "proposed",           # proposed|confirmed|refuted|inconclusive
    "evidence": [...], "created": "...", "judged": "..."
  }

The judge is honest: confirms ONLY if the effect is large enough AND in the
predicted direction. Otherwise refute or inconclusive. No wishful thinking.
"""

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from experiment import run_condition, DEFAULTS

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REGISTER = os.path.join(DATA, "hypotheses.json")
FINDINGS = os.path.join(DATA, "findings.md")


# --------------------------------------------------------------------
# Register I/O
# --------------------------------------------------------------------
def _load():
    if not os.path.exists(REGISTER):
        return {"next_id": 1, "hypotheses": []}
    with open(REGISTER) as f:
        return json.load(f)


def _save(reg):
    os.makedirs(DATA, exist_ok=True)
    with open(REGISTER, "w") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


def _finding(msg):
    """Append-only finding log — chain of evidence for later learning and conclusion."""
    os.makedirs(DATA, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(FINDINGS, "a") as f:
        f.write(f"- **{ts}** {msg}\n")


# --------------------------------------------------------------------
# Propose a hypothesis (called by the gardener reasoning)
# --------------------------------------------------------------------
def propose(claim, test, param="custom", author="gardener"):
    reg = _load()
    hid = f"H{reg['next_id']:04d}"
    reg["next_id"] += 1
    h = {
        "id": hid,
        "claim": claim,
        "param": param,
        "test": test,
        "status": "proposed",
        "author": author,
        "evidence": [],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "judged": None,
    }
    reg["hypotheses"].append(h)
    _save(reg)
    _finding(f"[{hid}] PROPOSED: {claim}")
    return hid


# --------------------------------------------------------------------
# Test + judge one hypothesis
# --------------------------------------------------------------------
def _relative_effect(a, b):
    """Relative difference (b-a)/|a|, robust against zero."""
    denom = abs(a) if abs(a) > 1e-9 else 1e-9
    return (b - a) / denom


def test_hypothesis(hid):
    reg = _load()
    h = next((x for x in reg["hypotheses"] if x["id"] == hid), None)
    if not h:
        return {"error": f"unknown hypothesis {hid}"}
    t = h["test"]

    if t.get("kind") != "compare":
        return {"error": f"unknown test type {t.get('kind')}"}

    metric = t["metric"]
    res_a = run_condition(f"{hid}-A", t["a"])
    res_b = run_condition(f"{hid}-B", t["b"])
    va, vb = res_a.get(metric, 0.0), res_b.get(metric, 0.0)
    eff = _relative_effect(va, vb)

    # --- 95% CI on the difference (b - a) via per-seed bootstrap ---
    # A verdict is only trustworthy if the effect survives stochastic noise.
    raw_a = res_a.get("_raw", {}).get(metric, [])
    raw_b = res_b.get("_raw", {}).get(metric, [])
    ci_lo, ci_hi, ci_excludes_zero = None, None, None
    if len(raw_a) >= 3 and len(raw_b) >= 3:
        import random as _rnd
        _r = _rnd.Random(12345)
        diffs = []
        for _ in range(2000):
            ma = sum(_r.choice(raw_a) for _ in raw_a) / len(raw_a)
            mb = sum(_r.choice(raw_b) for _ in raw_b) / len(raw_b)
            diffs.append(mb - ma)
        diffs.sort()
        ci_lo = round(diffs[int(0.025 * len(diffs))], 4)
        ci_hi = round(diffs[int(0.975 * len(diffs))], 4)
        ci_excludes_zero = (ci_lo > 0) or (ci_hi < 0)

    # Direction: predicted "b>a" or "b<a"
    direction = t.get("direction", "b>a")
    min_eff = t.get("min_effect", 0.15)
    if direction == "b>a":
        predicted_ok = eff >= min_eff
    elif direction == "b<a":
        predicted_ok = eff <= -min_eff
    else:
        predicted_ok = abs(eff) >= min_eff

    # Honest verdict — now gated on the CI excluding zero.
    # If the CI crosses zero the effect is not distinguishable from noise,
    # no matter how big the point estimate looks.
    if ci_excludes_zero is False:
        status = "inconclusive"   # effect not separable from stochastic noise
    elif predicted_ok:
        status = "confirmed"
    elif abs(eff) < min_eff:
        status = "inconclusive"   # effect too small to say anything
    else:
        status = "refuted"        # effect in the OPPOSITE direction of predicted

    evidence = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metric": metric,
        "a_value": va, "b_value": vb,
        "relative_effect": round(eff, 4),
        "ci95_diff": [ci_lo, ci_hi],
        "ci_excludes_zero": ci_excludes_zero,
        "direction_predicted": direction,
        "min_effect": min_eff,
        "full_a": {k: v for k, v in res_a.items() if k != "_raw"},
        "full_b": {k: v for k, v in res_b.items() if k != "_raw"},
    }
    h["evidence"].append(evidence)
    h["status"] = status
    h["judged"] = evidence["when"]
    _save(reg)

    verdict = {"confirmed": "CONFIRMED", "refuted": "REFUTED",
               "inconclusive": "INCONCLUSIVE"}[status]
    _finding(f"[{hid}] {verdict}: {h['claim']} "
             f"({metric}: A={va} B={vb}, effect={eff:+.1%}, requirement={direction} ≥{min_eff:.0%})")
    return {"id": hid, "status": status, "effect": round(eff, 4),
            "a": va, "b": vb, "metric": metric}


# --------------------------------------------------------------------
# Run all untested hypotheses
# --------------------------------------------------------------------
def run_pending(limit=3):
    reg = _load()
    pending = [h["id"] for h in reg["hypotheses"] if h["status"] == "proposed"]
    out = []
    for hid in pending[:limit]:
        out.append(test_hypothesis(hid))
    return out


# --------------------------------------------------------------------
# Status overview (for gardener context)
# --------------------------------------------------------------------
def summary():
    reg = _load()
    by_status = {}
    for h in reg["hypotheses"]:
        by_status.setdefault(h["status"], []).append(h)
    lines = [f"Total hypotheses: {len(reg['hypotheses'])}"]
    for st in ("proposed", "confirmed", "refuted", "inconclusive"):
        hs = by_status.get(st, [])
        if hs:
            lines.append(f"  {st}: {len(hs)}")
    return {
        "counts": {k: len(v) for k, v in by_status.items()},
        "confirmed": [{"id": h["id"], "claim": h["claim"]} for h in by_status.get("confirmed", [])],
        "proposed": [{"id": h["id"], "claim": h["claim"]} for h in by_status.get("proposed", [])],
        "text": "\n".join(lines),
    }


# --------------------------------------------------------------------
# CLI: used by the gardener cron and manually
# --------------------------------------------------------------------
def _seed_initial():
    """So the register isn't empty: two hypotheses derived from the atlas findings."""
    if _load()["hypotheses"]:
        return "register not empty — skipping seed"
    propose(
        claim="Lower edge_cost increases complexity (cheap connections => richer net)",
        param="edge_cost",
        test={"kind": "compare", "a": {"edge_cost": 0.02}, "b": {"edge_cost": 0.005},
              "metric": "complexity", "direction": "b>a", "min_effect": 0.2},
        author="system-seed",
    )
    propose(
        claim="prune_threshold is inactive (edge_cost does the pruning, so prune changes nothing)",
        param="prune_threshold",
        test={"kind": "compare", "a": {"prune_threshold": 0.05}, "b": {"prune_threshold": 0.2},
              "metric": "complexity", "direction": "either", "min_effect": 0.15},
        author="system-seed",
    )
    return "seeded 2 initial hypotheses"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "seed":
        print(_seed_initial())
    elif cmd == "run":
        print(json.dumps(run_pending(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 3),
                         ensure_ascii=False, indent=2))
    elif cmd == "status":
        print(summary()["text"])
    else:
        print("usage: research.py [seed|run [N]|status]")
