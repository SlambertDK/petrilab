"""
PetriLab v2 — the Gardener
==========================
An autonomous experimenter. It never touches rules/DNA (level B): it only tunes
RATIOS (energy, mutation, seasons, signaling...). Its job is to keep the dish
near the fertile regime and to run its own experiments when things stagnate.

Loop (self-generating-from-findings):
  1. Watch MODES novelty + complexity trend.
  2. If stagnating (novelty low / complexity flat) -> propose an experiment:
     pick a tunable ratio, nudge it, and remember the pre-change baseline.
  3. After an evaluation window, MEASURE the effect. Keep the change if it
     improved the objective; otherwise revert. Log every decision with a reason.
  4. Each finding updates a durable per-knob effect estimate (a decayed running
     mean of delta) that biases the next hypothesis toward knobs that genuinely
     helped -- learning that survives restarts and does not wash out.

Objective (decoupled from novelty alone to avoid gaming a single axis):
    score = 0.5*novelty + 0.3*complexity_norm + 0.2*ecology

Memory model (why this is a rebuild):
  * knob STATS: per-knob decayed running mean of delta (EWMA) + trial count +
    running sum, instead of a single drifting credit counter that collapsed all
    knobs to the floor. Selection uses optimistic-init + UCB so good knobs stay
    ahead of bad ones and are picked more, while still exploring.
  * PERSISTENCE: to_dict()/load_dict() serialize the whole brain so the server
    can snapshot it to disk and restore it on startup -> learning survives
    restarts.
  * CONCLUSIONS: every N experiments the gardener summarizes trends across many
    experiments and APPENDS durable, dated conclusions to data/findings.md,
    including a clearly-marked '## ACTION NEEDED' block when it concludes
    something only an engine change (level A, which it may never make) could fix.
"""
import json
import math
import os
import random
from datetime import datetime, timezone

import hypotheses
from hypotheses import HypothesisQueue


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

    # learning constants
    EWMA_ALPHA = 0.25       # weight of the newest delta in the running mean
    OPTIMISTIC_INIT = 0.02  # prior mean effect (>0) so untried knobs get explored
    UCB_C = 0.03            # exploration bonus scale in the UCB selection term
    CONCLUDE_EVERY = 25     # experiments between durable findings.md summaries

    def __init__(self, eval_window=400, seed=0, findings_path=None):
        self.rng = random.Random(seed)
        self.eval_window = eval_window
        self.log = []                 # [{gen, action, reason}]
        self.pending = None           # active experiment
        # --- per-knob effect statistics (the real memory) ---
        # mean  : decayed running mean of delta (EWMA) -> "does this knob help?"
        # count : number of resolved trials -> confidence
        # sum   : running sum of deltas -> durable total effect for reporting
        # last  : last observed delta
        self.knob_stats = {
            k: {"mean": self.OPTIMISTIC_INIT, "count": 0, "sum": 0.0, "last": 0.0,
                "amean": 0.0, "m2": 0.0, "acount": 0}
            for k in self.KNOBS
        }
        self.last_score = None
        self.cooldown = 0
        self.phase = "idle"
        self.experiments_run = 0      # durable cumulative experiment counter
        self.last_conclusion_at = 0   # experiments_run at last findings write
        self.reheat_seen = 0          # count of reheats observed (for conclusions)
        self._last_last_event = None  # dedup engine last_event across ticks
        self.stuck_since_gen = None   # first gen verdict became non-success
        # rolling record of (gen, complexity) to detect whether peaks GROW over time
        # (real accumulation, Wolfram class 4) or merely REPEAT (oscillation, class 2)
        self.cplx_history = []        # list of [gen, complexity], capped
        self.CPLX_HISTORY_MAX = 240
        # --- hypothesis queue: candidate interaction pairs -> controlled 2x2 tests ---
        # This closes the loop: the report flags candidate knob-pair interactions,
        # they are queued here, and the gardener runs ONE at a time as a real 2x2
        # factorial experiment (varying both knobs) to confirm or reject it.
        self.hyp = HypothesisQueue()
        self.hyp_refresh_at = 0       # experiments_run at last candidate refresh
        self.HYP_REFRESH_EVERY = 20   # pull fresh candidates from report this often
        self.findings_path = findings_path or os.path.join(
            os.path.dirname(__file__), "data", "findings.md")
        # data-science observation log: one JSON row per resolved experiment
        # (knob touched + its value -> the outcome variables at that moment).
        # This is the dataset the models are trained on.
        self.observations_path = os.path.join(
            os.path.dirname(self.findings_path), "observations.jsonl")

    # ---- backward-compat view: some UI code reads knob_credit ----
    @property
    def knob_credit(self):
        """Legacy accessor: a positive, comparable 'credit' derived from the
        durable stats (optimistic mean scaled into a friendly range)."""
        return {k: self._credit(k) for k in self.KNOBS}

    def _credit(self, knob):
        s = self.knob_stats[knob]
        # map mean effect into a positive weight; keep good knobs clearly above bad
        return round(1.0 + 20.0 * s["mean"], 3)

    def _score(self, modes_rec):
        nov = modes_rec.get("novelty", 0)
        cplx = min(modes_rec.get("complexity", 0) / 8.0, 1.0)   # normalise
        eco = modes_rec.get("ecology", 0)
        return 0.5 * nov + 0.3 * cplx + 0.2 * eco

    def _logi(self, gen, action, reason):
        self.log.append({"gen": gen, "action": action, "reason": reason})
        if len(self.log) > 200:
            self.log = self.log[-200:]

    # ---------------------------------------------------------------
    def observe(self, sim, modes_rec, falsi):
        """Called each gardener tick (e.g. every 50 gens)."""
        gen = sim.generation
        score = self._score(modes_rec)

        # record complexity for trend analysis (growing peaks vs. mere oscillation)
        cx = modes_rec.get("complexity")
        if cx is not None:
            self.cplx_history.append([gen, float(cx)])
            if len(self.cplx_history) > self.CPLX_HISTORY_MAX:
                self.cplx_history = self.cplx_history[-self.CPLX_HISTORY_MAX:]

        # track how long the verdict has been unresolved/failing (for ACTION NEEDED)
        if falsi.get("verdict") == "success":
            self.stuck_since_gen = None
        elif self.stuck_since_gen is None:
            self.stuck_since_gen = gen

        # observe engine reheating events (level-A mechanism firing) for conclusions
        ev = getattr(sim, "last_event", None)
        if ev and ev != self._last_last_event:
            if str(ev).startswith("reheat@"):
                self.reheat_seen += 1
            self._last_last_event = ev

        # --- resolve a pending experiment across visible phases ---
        if self.pending:
            self.pending["age"] += 1
            age = self.pending["age"]
            if age == 1:
                self.phase = "measure"      # step 3: gathering the effect
                self.last_score = score
                return
            # step 4: LEARN (keep or revert)
            base = self.pending["baseline_score"]
            delta = score - base
            knob = self.pending["knob"]
            self._record_effect(knob, delta)
            self.experiments_run += 1
            self._log_observation(sim, modes_rec, falsi, knob, base, score, delta)
            if delta > 0.01:
                self._logi(gen, f"KEEP {knob}={round(getattr(sim, knob),3)}",
                           f"score {round(base,3)}->{round(score,3)} (+{round(delta,3)})")
            else:
                setattr(sim, knob, self.pending["old_value"])
                self._logi(gen, f"REVERT {knob}->{round(self.pending['old_value'],3)}",
                           f"no gain (d{round(delta,3)}); restored")
            self.pending = None
            self.phase = "learn"
            self.cooldown = 2
            self.last_score = score
            # periodically distil many experiments into durable conclusions
            if self.experiments_run - self.last_conclusion_at >= self.CONCLUDE_EVERY:
                self._write_conclusions(sim, modes_rec, falsi)
                self.last_conclusion_at = self.experiments_run
            return

        if self.cooldown > 0:
            self.cooldown -= 1
            self.phase = "idle"
            self.last_score = score
            return

        # --- hypothesis queue: run one controlled 2x2 factorial cell per tick ---
        # This takes priority over single-knob probes: when a candidate interaction
        # is being tested, the gardener is busy varying BOTH knobs in a controlled
        # design. One cell measured per tick -> "one at a time", exactly.
        active = self.hyp.ensure_active()
        if active is not None:
            finished = active.step(sim, score, self._set_knob)
            self.phase = f"factorial:{active.pair}:{active.current_cell}"
            if finished:
                prog = active.progress()
                self._logi(gen, f"INTERACTION {active.pair}: {active.verdict}",
                           f"effect={prog['effect']} p={prog['p']} "
                           f"over {prog['rep']} replicates")
                self.hyp.complete_active()
            self.last_score = score
            return

        # --- decide whether to intervene ---
        stagnating = (modes_rec.get("novelty", 0) < 0.15) or falsi["verdict"] != "success"
        if not stagnating:
            # things are good -- occasionally probe anyway to keep exploring
            if self.rng.random() > 0.15:
                self.last_score = score
                return
            reason = "healthy -- exploratory probe"
        else:
            reason = f"stagnation (novelty={modes_rec.get('novelty')}, verdict={falsi['verdict']})"

        # --- pick a knob, biased toward ones that have helped (findings->hypothesis) ---
        knob = self._weighted_knob()
        lo, hi, step = self.KNOBS[knob]
        cur = getattr(sim, knob)
        direction = self.rng.choice([-1, 1])
        new = max(lo, min(hi, cur + direction * step))
        if new == cur:
            new = max(lo, min(hi, cur - direction * step))
        setattr(sim, knob, new)
        self.pending = {"knob": knob, "old_value": cur, "age": 0,
                        "baseline_score": score, "at_bound": (new in (lo, hi))}
        self.phase = "test"
        self._logi(gen, f"TRY {knob}: {round(cur,3)}->{round(new,3)}", reason)
        self.last_score = score

    # ---------------------------------------------------------------
    def _record_effect(self, knob, delta):
        """Update the durable per-knob effect estimate with the newest delta.
        A decayed running mean (EWMA) remembers what helped without letting the
        estimate collapse to a floor: a knob with a positive history keeps a
        positive mean even after some failed trials."""
        s = self.knob_stats[knob]
        s["count"] += 1
        s["sum"] += delta
        s["last"] = delta
        # Welford online mean/variance of the raw deltas (for significance testing:
        # is this knob's average effect real, or just noise around zero?)
        s["acount"] += 1
        d0 = delta - s["amean"]
        s["amean"] += d0 / s["acount"]
        s["m2"] += d0 * (delta - s["amean"])
        if s["count"] == 1:
            # first real observation replaces the optimistic prior
            s["mean"] = delta
        else:
            s["mean"] = (1 - self.EWMA_ALPHA) * s["mean"] + self.EWMA_ALPHA * delta

    def _weighted_knob(self):
        """UCB-style selection: exploit knobs with a high mean effect, but add an
        exploration bonus that shrinks as a knob is tried more. Optimistic init
        guarantees untried knobs are explored early. Scores are shifted positive
        and used as softmax weights so selection stays stochastic (keeps probing)
        while genuinely favouring what has worked."""
        total = sum(s["count"] for s in self.knob_stats.values()) + 1
        knobs = list(self.KNOBS)
        ucb = {}
        for k in knobs:
            s = self.knob_stats[k]
            bonus = self.UCB_C * math.sqrt(math.log(total + 1) / (s["count"] + 1))
            ucb[k] = s["mean"] + bonus
        # softmax over UCB values (temperature keeps exploration alive)
        temp = 0.02
        mx = max(ucb.values())
        weights = [math.exp((ucb[k] - mx) / temp) for k in knobs]
        return self.rng.choices(knobs, weights=weights, k=1)[0]

    # ---------------------------------------------------------------
    def _set_knob(self, sim, knob, value):
        """Set a tunable ratio, clamped to its declared bounds. Used by the
        factorial experiments so a 2x2 cell can never push a knob out of range."""
        if knob in self.KNOBS:
            lo, hi, _ = self.KNOBS[knob]
            value = max(lo, min(hi, value))
        setattr(sim, knob, value)

    def enqueue_from_models(self, models):
        """Queue new candidate interaction pairs from an already-built report.
        The heavy model build happens OFF the gardener tick (in the server's
        report thread); the gardener never blocks on it — it just receives the
        candidates. This keeps the sim loop and /api/state responsive."""
        if not models:
            return 0
        cands = []
        for e in models.get("interactions_2way", []):
            if e.get("verdict") == "candidate":
                a, b = e.get("a"), e.get("b")
                if a and b:
                    cands.append({"a": a, "b": b, "p_adj": e.get("p_adj")})
        if not cands:
            return 0
        bounds = {k: (v[0], v[1]) for k, v in self.KNOBS.items()}
        return self.hyp.enqueue_candidates(cands, bounds)

    def seed_theory_hypotheses(self):
        """Queue the a-priori, mechanistically-motivated interaction pairs
        (hypotheses.THEORY_PAIRS) ahead of the data-driven candidates. These are
        predictions I expect to interact for a stated reason; the same controlled
        2x2 test falsifies them, so tagging source='theory' lets us compare whether
        reasoned guesses survive better than blind screening. Idempotent: dedupe
        by pair means re-calling won't double-queue."""
        bounds = {k: (v[0], v[1]) for k, v in self.KNOBS.items()}
        cands = [{"a": a, "b": b, "source": "theory", "rationale": why}
                 for (a, b, why) in hypotheses.THEORY_PAIRS
                 if a in self.KNOBS and b in self.KNOBS]
        return self.hyp.enqueue_candidates(cands, bounds, max_queue=99, priority=True)

    # ---------------------------------------------------------------
    def _significance(self, s):
        """Decide whether a knob's average effect is a real signal or just noise,
        using a one-sample t-test against the null 'effect = 0'.

        t = mean / (sd / sqrt(n)).  |t| > ~2.6 -> <1% chance the effect is noise
        (correlates); |t| > ~2.0 -> <5% (likely real); otherwise the sign is not
        distinguishable from random drift, no matter how many trials. This is the
        difference between 'this knob correlates with success' and 'this knob's
        average just happens to be slightly off zero'."""
        n = s["count"]
        if n < 8:
            return f"too few trials (n={n})"
        na = s.get("acount", 0)
        if na < 8:
            return f"variance still warming up (n={na})"
        var = s["m2"] / (na - 1) if na > 1 else 0.0
        sd = math.sqrt(var)
        if sd < 1e-12:
            return "no variance (degenerate)"
        se = sd / math.sqrt(na)
        t = s["amean"] / se
        direction = "helps" if s["amean"] > 0 else "hurts"
        if abs(t) >= 2.58:
            return f"SIGNIFICANT: {direction} (t={t:+.1f}, p<0.01) — real correlation"
        if abs(t) >= 1.96:
            return f"likely {direction} (t={t:+.1f}, p<0.05)"
        return f"not distinguishable from chance (t={t:+.1f})"

    def complexity_trend(self):
        """Are complexity peaks GROWING over time (real accumulation, class 4) or
        just REPEATING (oscillation, class 2)? Fit a least-squares line to the
        upper envelope (top-quartile points) of recent complexity history and
        report its slope and correlation. A clearly positive slope with decent
        fit = peaks are climbing = accumulation. Slope ~0 = the same high notes,
        replayed = oscillation."""
        h = self.cplx_history
        if len(h) < 24:
            return {"verdict": "insufficient", "n": len(h)}
        vals = [c for _, c in h]
        thr = sorted(vals)[int(len(vals) * 0.75)]      # top quartile = the peaks
        pts = [(g, c) for g, c in h if c >= thr]
        if len(pts) < 6:
            return {"verdict": "insufficient", "n": len(pts)}
        n = len(pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        mx = sum(xs) / n
        my = sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        if sxx < 1e-9 or syy < 1e-9:
            return {"verdict": "flat", "slope": 0.0, "r": 0.0, "n": n}
        slope = sxy / sxx
        r = sxy / math.sqrt(sxx * syy)
        span = xs[-1] - xs[0]
        rise = slope * span                             # peak growth across the window
        rel = rise / my if my else 0.0                  # growth relative to peak height
        if r >= 0.35 and rel > 0.12:
            verdict = "peaks GROWING — accumulation (class-4-like)"
        elif r <= -0.35 and rel < -0.12:
            verdict = "peaks SHRINKING — decaying"
        else:
            verdict = "peaks REPEATING — oscillation (class-2-like)"
        return {"verdict": verdict, "slope": round(slope, 6), "r": round(r, 2),
                "peak_growth_pct": round(rel * 100, 1), "n": n}

    def significance_report(self):
        """Machine-readable version for the dashboard / API: per-knob t-stat and verdict."""
        out = {}
        for k, s in self.knob_stats.items():
            n = s["count"]
            na = s.get("acount", 0)
            if n < 8 or na < 8:
                out[k] = {"n": n, "vn": na, "t": None, "verdict": "insufficient"}
                continue
            var = s["m2"] / (na - 1) if na > 1 else 0.0
            sd = math.sqrt(var)
            se = sd / math.sqrt(na) if sd > 1e-12 else None
            t = (s["amean"] / se) if se else None
            if t is None:
                verdict = "degenerate"
            elif abs(t) >= 2.58:
                verdict = "significant"
            elif abs(t) >= 1.96:
                verdict = "likely"
            else:
                verdict = "chance"
            out[k] = {"n": n, "vn": na, "mean": round(s["amean"], 5),
                      "t": (round(t, 2) if t is not None else None), "verdict": verdict}
        return out

    def _log_observation(self, sim, modes_rec, falsi, knob, base, score, delta):
        """Append one experiment row to observations.jsonl — the training set for
        the models. Captures the knob that was moved and its value, all the knob
        settings at the time, and the outcome variables (the MODES axes, cell
        count, biggest cell, falsification verdict). Never raises."""
        try:
            row = {
                "gen": sim.generation,
                "exp": self.experiments_run,
                "knob": knob,
                "knob_value": round(float(getattr(sim, knob, 0.0)), 5),
                # full condition vector at decision time (features)
                "conditions": {k: round(float(getattr(sim, k, 0.0)), 5)
                               for k in self.KNOBS},
                # outcome variables (targets)
                "novelty": modes_rec.get("novelty"),
                "complexity": modes_rec.get("complexity"),
                "ecology": modes_rec.get("ecology"),
                "change": modes_rec.get("change"),
                "cells": len(getattr(sim, "cells", {}) or {}),
                "lineages": len(sim.lineage_census()) if hasattr(sim, "lineage_census") else None,
                "max_genome": self._max_genome(sim),
                "score": round(score, 5),
                "delta": round(delta, 5),
                "verdict": falsi.get("verdict"),
            }
            os.makedirs(os.path.dirname(self.observations_path), exist_ok=True)
            with open(self.observations_path, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:
            self._logi(sim.generation, "OBS-LOG-ERROR", str(e)[:120])

    @staticmethod
    def _max_genome(sim):
        try:
            return max((len(c.genome) for c in sim.cells.values()), default=0)
        except Exception:
            return 0

    def _write_conclusions(self, sim, modes_rec, falsi):
        """Distil many experiments into durable, dated conclusions appended to
        findings.md. Also emits an ACTION NEEDED block when the gardener hits a
        wall only an engine (level-A) change could break -- it never messages
        anyone, it only writes the file."""
        try:
            os.makedirs(os.path.dirname(self.findings_path), exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            gen = sim.generation
            lines = []
            lines.append(f"\n## {ts} — gardener conclusions @ gen {gen}")
            lines.append(f"- experiments run (cumulative): {self.experiments_run}")
            lines.append(f"- current verdict: {falsi.get('verdict')}, "
                         f"novelty={modes_rec.get('novelty')}, "
                         f"complexity={modes_rec.get('complexity')}, "
                         f"ecology={modes_rec.get('ecology')}")

            # rank knobs by durable mean effect
            ranked = sorted(self.knob_stats.items(), key=lambda kv: -kv[1]["mean"])
            lines.append("- knob effect (does it correlate, or is it chance?):")
            for k, s in ranked:
                if s["count"] == 0:
                    lines.append(f"    - {k}: untried")
                    continue
                verdict = self._significance(s)
                lines.append(f"    - {k}: mean {s['mean']:+.4f} over "
                             f"{s['count']} trials -> {verdict}")

            if self.reheat_seen:
                lines.append(f"- engine reheating fired {self.reheat_seen}x "
                             f"(anti-stagnation triggered)")

            # pattern detection: are the big-complexity moments accumulating or repeating?
            tr = self.complexity_trend()
            if tr.get("verdict") not in ("insufficient",):
                extra = ""
                if tr.get("r") is not None and "peak_growth_pct" in tr:
                    extra = f" (r={tr['r']}, peak growth {tr['peak_growth_pct']}% over window)"
                lines.append(f"- complexity peaks: {tr['verdict']}{extra}")

            if self.stuck_since_gen is not None:
                stuck_for = gen - self.stuck_since_gen
                lines.append(f"- verdict stuck at non-success for {stuck_for} gens "
                             f"(since gen {self.stuck_since_gen})")

            # --- ACTION NEEDED detection (level-A limits the gardener cannot cross) ---
            actions = self._detect_action_needed(sim, modes_rec, falsi)
            if actions:
                lines.append("\n## ACTION NEEDED")
                lines.append(f"_(flagged {ts} @ gen {gen}; the gardener is level-B "
                             f"and can only tune ratios — the following likely need "
                             f"an engine/rules change a human must make)_")
                for a in actions:
                    lines.append(f"- {a}")

            with open(self.findings_path, "a") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:  # never let a logging failure kill the loop
            self._logi(sim.generation, "CONCLUDE-ERROR", str(e)[:120])

    def _detect_action_needed(self, sim, modes_rec, falsi):
        """Return a list of situations the gardener concludes it cannot fix by
        tuning ratios alone."""
        actions = []
        # 1) a knob pinned at its bound but still historically wanting more
        for k, (lo, hi, step) in self.KNOBS.items():
            cur = getattr(sim, k, None)
            if cur is None:
                continue
            s = self.knob_stats[k]
            if s["count"] >= 3 and s["mean"] > 0.01:
                if abs(cur - hi) < 1e-9:
                    actions.append(
                        f"knob '{k}' is pinned at its MAX ({hi}) and still shows a "
                        f"positive mean effect ({s['mean']:+.4f}) — the useful range "
                        f"may be capped too low; consider widening the engine bound.")
                elif abs(cur - lo) < 1e-9:
                    actions.append(
                        f"knob '{k}' is pinned at its MIN ({lo}) and still shows a "
                        f"positive mean effect ({s['mean']:+.4f}) — the useful range "
                        f"may be capped too high; consider widening the engine bound.")
        # 2) long flat stagnation despite exploring most knobs
        tried = sum(1 for s in self.knob_stats.values() if s["count"] > 0)
        if (self.stuck_since_gen is not None
                and sim.generation - self.stuck_since_gen > 50000
                and tried >= max(1, len(self.KNOBS) - 1)):
            actions.append(
                f"score/verdict has been non-success for "
                f"{sim.generation - self.stuck_since_gen} gens despite exploring "
                f"{tried}/{len(self.KNOBS)} knobs — ratio tuning appears exhausted; "
                f"a new mechanism (level-A: rules/genotype/output layer) is likely "
                f"required to move further.")
        return actions

    # ---------------------------------------------------------------
    def state(self, sim):
        """Snapshot of the self-improvement loop for the dashboard."""
        # sort knobs by learned credit (what has helped most)
        ranked = sorted(self.knob_stats.items(), key=lambda kv: -kv[1]["mean"])
        credit = [{"knob": k,
                   "credit": self._credit(k),
                   "mean_effect": round(s["mean"], 4),
                   "trials": s["count"],
                   "value": round(getattr(sim, k), 3) if hasattr(sim, k) else None}
                  for k, s in ranked]
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
            "experiments_run": self.experiments_run,
            "current_score": round(self.last_score, 3) if self.last_score is not None else None,
            "phase": self.phase,
            "hypotheses": self.hyp.state(),
        }

    # ---------------------------------------------------------------
    # persistence: serialize/restore the whole brain so learning survives restarts
    def to_dict(self):
        return {
            "version": 2,
            "log": self.log[-200:],
            "knob_stats": self.knob_stats,
            "experiments_run": self.experiments_run,
            "last_conclusion_at": self.last_conclusion_at,
            "reheat_seen": self.reheat_seen,
            "stuck_since_gen": self.stuck_since_gen,
            "cplx_history": self.cplx_history[-self.CPLX_HISTORY_MAX:],
            "last_score": self.last_score,
            "cooldown": self.cooldown,
            "phase": self.phase,
            # keep an in-flight experiment so a restart mid-test doesn't lose it
            "pending": self.pending,
            "hyp": self.hyp.to_dict(),
            "hyp_refresh_at": self.hyp_refresh_at,
        }

    def load_dict(self, d):
        if not d:
            return
        self.log = d.get("log", []) or []
        saved = d.get("knob_stats", {}) or {}
        for k in self.KNOBS:
            if k in saved and isinstance(saved[k], dict):
                s = saved[k]
                self.knob_stats[k] = {
                    "mean": float(s.get("mean", self.OPTIMISTIC_INIT)),
                    "count": int(s.get("count", 0)),
                    "sum": float(s.get("sum", 0.0)),
                    "last": float(s.get("last", 0.0)),
                    "amean": float(s.get("amean", 0.0)),
                    "m2": float(s.get("m2", 0.0)),
                    "acount": int(s.get("acount", 0)),
                }
        self.experiments_run = int(d.get("experiments_run", 0))
        self.last_conclusion_at = int(d.get("last_conclusion_at", 0))
        self.reheat_seen = int(d.get("reheat_seen", 0))
        self.stuck_since_gen = d.get("stuck_since_gen", None)
        self.cplx_history = d.get("cplx_history", []) or []
        self.last_score = d.get("last_score", None)
        self.cooldown = int(d.get("cooldown", 0))
        self.phase = d.get("phase", "idle")
        self.pending = d.get("pending", None)
        try:
            self.hyp.load_dict(d.get("hyp"))
        except Exception:
            pass
        self.hyp_refresh_at = int(d.get("hyp_refresh_at", 0))
