"""
PetriLab v2 — the Gardener
==========================
An autonomous experimenter. It never touches rules/DNA (level B): it only tunes
RATIOS (energy, mutation, seasons, signaling...). Its job is to keep the dish
near the fertile regime and to run its own experiments when things stagnate.

Loop (self-generating-from-findings):
  1. Watch MODES novelty + complexity trend.
  2. If stagnating (novelty low / complexity flat) → propose an experiment:
     pick a tunable ratio, nudge it, and remember the pre-change baseline.
  3. After an evaluation window, MEASURE the effect. Keep the change if it
     improved the objective; otherwise revert. Log every decision with a reason.
  4. Each finding seeds the next hypothesis (bias toward knobs that helped).

Objective (decoupled from novelty alone to avoid gaming a single axis):
    score = 0.5*novelty + 0.3*complexity_norm + 0.2*ecology
"""
import random


class Gardener:
    # ratios the gardener may tune, with (min, max, nudge step)
    KNOBS = {
        "mutation_rate":       (0.03, 0.6, 0.05),
        "gene_mut_rate":       (0.05, 0.6, 0.05),
        "seasons":             (0.0, 0.9, 0.1),
        "season_len":          (400, 4000, 300),
        "signaling":           (0.0, 2.0, 0.2),
        "energy_influx":       (15.0, 80.0, 5.0),
        "structural_heredity": (0.0, 0.9, 0.1),
    }

    def __init__(self, eval_window=400, seed=0):
        self.rng = random.Random(seed)
        self.eval_window = eval_window
        self.log = []                 # [{gen, action, reason}]
        self.pending = None           # active experiment
        self.knob_credit = {k: 1.0 for k in self.KNOBS}  # which knobs tend to help
        self.last_score = None
        self.cooldown = 0
        self.phase = "idle"

    def _score(self, modes_rec):
        nov = modes_rec.get("novelty", 0)
        cplx = min(modes_rec.get("complexity", 0) / 8.0, 1.0)   # normalise
        eco = modes_rec.get("ecology", 0)
        return 0.5 * nov + 0.3 * cplx + 0.2 * eco

    def _logi(self, gen, action, reason):
        self.log.append({"gen": gen, "action": action, "reason": reason})
        if len(self.log) > 200:
            self.log = self.log[-200:]

    def observe(self, sim, modes_rec, falsi):
        """Called each gardener tick (e.g. every 50 gens)."""
        gen = sim.generation
        score = self._score(modes_rec)

        # --- resolve a pending experiment across visible phases ---
        if self.pending:
            self.pending["age"] += 1
            age = self.pending["age"]
            if age == 1:
                self.phase = "measure"      # step 3: gathering the effect
                self.last_score = score
                return
            # age >= 2 → step 4: LEARN (keep or revert)
            base = self.pending["baseline_score"]
            delta = score - base
            knob = self.pending["knob"]
            if delta > 0.01:
                self.knob_credit[knob] = min(3.0, self.knob_credit[knob] + 0.4)
                self._logi(gen, f"KEEP {knob}={round(getattr(sim, knob),3)}",
                           f"score {round(base,3)}→{round(score,3)} (+{round(delta,3)})")
            else:
                setattr(sim, knob, self.pending["old_value"])
                self.knob_credit[knob] = max(0.2, self.knob_credit[knob] - 0.2)
                self._logi(gen, f"REVERT {knob}→{round(self.pending['old_value'],3)}",
                           f"no gain (Δ{round(delta,3)}); restored")
            self.pending = None
            self.phase = "learn"
            self.cooldown = 2
            self.last_score = score
            return

        if self.cooldown > 0:
            self.cooldown -= 1
            self.phase = "idle"
            self.last_score = score
            return

        # --- decide whether to intervene ---
        stagnating = (modes_rec.get("novelty", 0) < 0.15) or falsi["verdict"] != "success"
        if not stagnating:
            # things are good — occasionally probe anyway to keep exploring
            if self.rng.random() > 0.15:
                self.last_score = score
                return
            reason = "healthy — exploratory probe"
        else:
            reason = f"stagnation (novelty={modes_rec.get('novelty')}, verdict={falsi['verdict']})"

        # --- pick a knob, biased toward ones that have helped (findings→hypothesis) ---
        knob = self._weighted_knob()
        lo, hi, step = self.KNOBS[knob]
        cur = getattr(sim, knob)
        direction = self.rng.choice([-1, 1])
        new = max(lo, min(hi, cur + direction * step))
        if new == cur:
            new = max(lo, min(hi, cur - direction * step))
        setattr(sim, knob, new)
        self.pending = {"knob": knob, "old_value": cur, "age": 0,
                        "baseline_score": score}
        self.phase = "test"
        self._logi(gen, f"TRY {knob}: {round(cur,3)}→{round(new,3)}", reason)
        self.last_score = score

    def _weighted_knob(self):
        knobs = list(self.KNOBS)
        weights = [self.knob_credit[k] for k in knobs]
        return self.rng.choices(knobs, weights=weights, k=1)[0]

    def state(self, sim):
        """Snapshot of the self-improvement loop for the dashboard."""
        # sort knobs by learned credit (what has helped most)
        ranked = sorted(self.knob_credit.items(), key=lambda kv: -kv[1])
        credit = [{"knob": k, "credit": round(v, 2),
                   "value": round(getattr(sim, k), 3) if hasattr(sim, k) else None}
                  for k, v in ranked]
        hypothesis = None
        if self.pending:
            p = self.pending
            hypothesis = {
                "knob": p["knob"],
                "from": round(p["old_value"], 3),
                "to": round(getattr(sim, p["knob"], p["old_value"]), 3),
                "baseline_score": round(p["baseline_score"], 3),
                "status": "testing",
            }
        # derive last resolved outcome from the log
        last_outcome = None
        for e in reversed(self.log):
            if e["action"].startswith(("KEEP", "REVERT")):
                last_outcome = e
                break
        return {
            "hypothesis": hypothesis,
            "last_outcome": last_outcome,
            "knob_credit": credit,
            "experiments_run": len([e for e in self.log if e["action"].startswith("TRY")]),
            "current_score": round(self.last_score, 3) if self.last_score is not None else None,
            "phase": self.phase,
        }
