"""
PetriLab v2 — hypothesis queue & 2x2 factorial experiments
==========================================================
The data-science report (analytics.py) flags knob PAIRS as *candidate*
interactions — hypotheses the univariate layer cannot confirm. A single-knob
nudge can never prove an interaction: you must vary BOTH knobs in a controlled
design and measure whether one knob's effect DEPENDS on the other's level.

This module is the missing bridge in the continuous-improvement loop:

    observe -> flag candidate -> QUEUE -> controlled 2x2 test -> verdict -> learn

A FactorialExperiment tests one candidate pair (A, B) with a 2x2 design:

        cell        A      B
        ll          lo     lo
        hl          hi     lo
        lh          lo     hi
        hh          hi     hi

Each cell is held for an evaluation window and its objective score sampled.
The interaction contrast is

        interaction = (hh - lh) - (hl - ll)

i.e. "how much bigger is A's effect (hi-lo) when B is high vs. when B is low".
One full sweep of 4 cells yields ONE interaction estimate (a replicate). We run
several replicates and apply a sign test / mean-vs-SE test across replicates,
so a verdict rests on repeated controlled measurements, not a single sweep.

The queue holds candidates; the gardener runs the head item one cell at a time
(exactly the "one at a time" the user asked for), then advances. Everything is
level-B: only ratios are moved, rules/DNA are never touched.
"""
import math


# lifecycle states surfaced to the UI loop
QUEUED = "queued"
TESTING = "testing"
CONCLUDED = "concluded"


# ---------------------------------------------------------------------------
# THEORY-DRIVEN hypotheses: knob pairs where there is a mechanistic reason to
# expect the effect of one knob on complexity to DEPEND on the other's level.
# These are seeded a priori (not because the data flagged them) and tested with
# the SAME controlled 2x2 that falsifies the data-driven candidates — so we can
# honestly compare whether reasoned predictions survive better than blind
# screening. Each is a genuine, directional prediction, not a fishing expedition.
THEORY_PAIRS = [
    ("mutation_rate", "structural_heredity",
     "Mutation supplies variation; structural heredity decides how much survives "
     "to the next generation. High mutation should only build complexity when "
     "heredity is high enough to retain the good structure — otherwise it washes "
     "out. Classic error-threshold / heritability interaction."),
    ("energy_influx", "signaling",
     "Signalling is metabolically expensive. Multicellular coordination (the route "
     "to complexity) should pay off only when energy influx is high enough to "
     "afford it; under scarcity, signalling is pure cost. Energy should gate the "
     "signalling benefit."),
    ("mutation_rate", "gene_mut_rate",
     "Two mutation channels acting on the same genome. Their effects should be "
     "sub-additive (redundant) or super-additive (compounding) rather than "
     "independent — total mutational load, not either alone, likely drives the "
     "error-catastrophe boundary."),
    ("seasons", "structural_heredity",
     "Seasonal change rewards adaptability; structural heredity rewards stability. "
     "These pull in opposite directions, so the complexity payoff of one should "
     "depend on the level of the other — a stability-vs-adaptability trade-off."),
    ("energy_influx", "mutation_rate",
     "Energy sets carrying capacity and thus effective population size; population "
     "size sets how strongly selection can purge deleterious mutations. The same "
     "mutation rate should behave very differently under abundance vs scarcity."),
    ("season_len", "seasons",
     "Amplitude (seasons) and period (season_len) of environmental change jointly "
     "define the selective regime. Fast+large vs slow+large are different worlds, "
     "so their effects on complexity should not simply add."),
]


class FactorialExperiment:
    """A 2x2 controlled interaction test for one knob pair, driven cell by cell."""

    CELLS = ("ll", "hl", "lh", "hh")

    def __init__(self, knob_a, knob_b, bounds_a, bounds_b,
                 replicates=3, settle_ticks=1, source="report", rationale=""):
        self.a = knob_a
        self.b = knob_b
        # where this hypothesis came from: "report" = data-driven candidate flagged
        # by the interaction screen; "theory" = mechanistic prediction seeded a priori.
        # The 2x2 test falsifies both identically — tagging just lets us honestly
        # compare whether theory-driven guesses survive better than blind screening.
        self.source = source
        self.rationale = rationale
        # low/high levels for each knob: use the tunable range's inner quartiles
        # so we probe a real contrast without slamming into the bounds.
        lo_a, hi_a = bounds_a
        lo_b, hi_b = bounds_b
        self.level_a = {"lo": lo_a + 0.25 * (hi_a - lo_a),
                        "hi": lo_a + 0.75 * (hi_a - lo_a)}
        self.level_b = {"lo": lo_b + 0.25 * (hi_b - lo_b),
                        "hi": lo_b + 0.75 * (hi_b - lo_b)}
        self.replicates = replicates
        self.settle_ticks = settle_ticks   # ticks to wait after setting before sampling
        # progress
        self.state = QUEUED
        self.rep = 0             # completed replicates
        self.cell_idx = 0        # index into CELLS for the current sweep
        self.settle = 0          # ticks waited in the current cell
        self.samples = {}        # cell -> list of scores (current sweep)
        self.contrasts = []      # one interaction estimate per completed replicate
        self.verdict = None      # 'interaction-confirmed' | 'no-interaction' | 'inconclusive'
        self.effect = None       # mean interaction contrast
        self.p = None            # sign/SE test p-value across replicates
        self.saved_a = None      # original knob values, restored on completion
        self.saved_b = None

    # --- cell targeting -------------------------------------------------
    def _cell_levels(self, cell):
        la = "hi" if cell in ("hl", "hh") else "lo"
        lb = "hi" if cell in ("lh", "hh") else "lo"
        return self.level_a[la], self.level_b[lb]

    @property
    def pair(self):
        return f"{self.a}*{self.b}"

    @property
    def current_cell(self):
        return self.CELLS[self.cell_idx]

    # --- the driver: called once per gardener tick while this exp is head --
    def step(self, sim, score, setattr_knob):
        """Advance the experiment by one tick. Returns True when the whole
        experiment (all replicates) is finished."""
        if self.state == QUEUED:
            # remember originals so we can restore the dish afterwards
            self.saved_a = getattr(sim, self.a)
            self.saved_b = getattr(sim, self.b)
            self.state = TESTING
            self._apply_cell(sim, setattr_knob)
            self.settle = 0
            return False

        # settling: let the dish respond to the new levels before sampling
        if self.settle < self.settle_ticks:
            self.settle += 1
            return False

        # sample this cell
        cell = self.current_cell
        self.samples.setdefault(cell, []).append(score)

        # advance to next cell in the sweep
        self.cell_idx += 1
        if self.cell_idx < len(self.CELLS):
            self._apply_cell(sim, setattr_knob)
            self.settle = 0
            return False

        # a full 2x2 sweep is done -> one interaction contrast
        ll = _mean(self.samples.get("ll"))
        hl = _mean(self.samples.get("hl"))
        lh = _mean(self.samples.get("lh"))
        hh = _mean(self.samples.get("hh"))
        if None not in (ll, hl, lh, hh):
            self.contrasts.append((hh - lh) - (hl - ll))
        self.rep += 1
        self.cell_idx = 0
        self.samples = {}

        if self.rep < self.replicates:
            self._apply_cell(sim, setattr_knob)   # start next replicate
            self.settle = 0
            return False

        # all replicates done -> verdict, restore dish
        self._conclude()
        setattr_knob(sim, self.a, self.saved_a)
        setattr_knob(sim, self.b, self.saved_b)
        self.state = CONCLUDED
        return True

    def _apply_cell(self, sim, setattr_knob):
        va, vb = self._cell_levels(self.current_cell)
        setattr_knob(sim, self.a, va)
        setattr_knob(sim, self.b, vb)

    def _conclude(self):
        c = self.contrasts
        self.effect = _mean(c)
        n = len(c)
        if n < 2 or self.effect is None:
            self.verdict = "inconclusive"
            self.p = None
            return
        # mean-vs-SE test across replicate contrasts (is the interaction != 0?)
        mean = self.effect
        sd = math.sqrt(sum((x - mean) ** 2 for x in c) / (n - 1))
        if sd < 1e-9:
            # all replicates agree exactly -> treat as strong if non-zero
            self.p = 0.0 if abs(mean) > 1e-6 else 1.0
        else:
            t = mean / (sd / math.sqrt(n))
            self.p = _t_sf_2sided(abs(t), n - 1)
        # verdict: needs both statistical signal AND a materially sized effect
        if self.p is not None and self.p < 0.05 and abs(mean) > 0.01:
            self.verdict = "interaction-confirmed"
        elif self.p is not None and self.p < 0.20 and abs(mean) > 0.01:
            self.verdict = "leaning"
        else:
            self.verdict = "no-interaction"

    # --- progress for the UI -------------------------------------------
    def progress(self):
        total = self.replicates * len(self.CELLS)
        done = self.rep * len(self.CELLS) + self.cell_idx
        return {
            "pair": self.pair,
            "a": self.a, "b": self.b,
            "source": self.source, "rationale": self.rationale,
            "state": self.state,
            "cell": self.current_cell if self.state == TESTING else None,
            "rep": self.rep, "replicates": self.replicates,
            "done": done, "total": total,
            "frac": round(done / total, 3) if total else 0.0,
            "contrasts": [round(x, 4) for x in self.contrasts],
            "verdict": self.verdict,
            "effect": round(self.effect, 4) if self.effect is not None else None,
            "p": round(self.p, 4) if self.p is not None else None,
        }

    def to_dict(self):
        return {
            "a": self.a, "b": self.b,
            "source": self.source, "rationale": self.rationale,
            "level_a": self.level_a, "level_b": self.level_b,
            "replicates": self.replicates, "settle_ticks": self.settle_ticks,
            "state": self.state, "rep": self.rep, "cell_idx": self.cell_idx,
            "settle": self.settle, "samples": self.samples,
            "contrasts": self.contrasts, "verdict": self.verdict,
            "effect": self.effect, "p": self.p,
            "saved_a": self.saved_a, "saved_b": self.saved_b,
        }

    @classmethod
    def from_dict(cls, d):
        exp = cls(d["a"], d["b"], (0, 1), (0, 1),
                  replicates=d.get("replicates", 3),
                  settle_ticks=d.get("settle_ticks", 1),
                  source=d.get("source", "report"),
                  rationale=d.get("rationale", ""))
        exp.level_a = d.get("level_a", exp.level_a)
        exp.level_b = d.get("level_b", exp.level_b)
        exp.state = d.get("state", QUEUED)
        exp.rep = d.get("rep", 0)
        exp.cell_idx = d.get("cell_idx", 0)
        exp.settle = d.get("settle", 0)
        exp.samples = d.get("samples", {}) or {}
        exp.contrasts = d.get("contrasts", []) or []
        exp.verdict = d.get("verdict")
        exp.effect = d.get("effect")
        exp.p = d.get("p")
        exp.saved_a = d.get("saved_a")
        exp.saved_b = d.get("saved_b")
        return exp


class HypothesisQueue:
    """Ordered queue of candidate interaction pairs + the archive of verdicts."""

    def __init__(self, max_archive=30):
        self.queue = []          # list of FactorialExperiment (QUEUED)
        self.active = None       # FactorialExperiment (TESTING)
        self.archive = []        # list of concluded progress dicts (newest first)
        self.max_archive = max_archive
        self.seen = set()        # pairs already queued/tested (dedupe)

    def enqueue_candidates(self, candidates, bounds, max_queue=8, priority=False):
        """candidates: list of dicts with 'a','b' (and optional 'p_adj','source',
        'rationale'). Adds any not already queued/active/recently-concluded.
        priority=True inserts at the FRONT of the queue (used for theory-driven
        hypotheses so a priori predictions get tested ahead of the data sweep)."""
        added = 0
        for c in candidates:
            a, b = c.get("a"), c.get("b")
            if not a or not b or a == b:
                continue
            key = tuple(sorted((a, b)))
            if key in self.seen:
                continue
            if a not in bounds or b not in bounds:
                continue
            exp = FactorialExperiment(a, b, bounds[a], bounds[b],
                                      source=c.get("source", "report"),
                                      rationale=c.get("rationale", ""))
            if priority:
                self.queue.insert(0, exp)
            else:
                self.queue.append(exp)
            self.seen.add(key)
            added += 1
            if len(self.queue) >= max_queue:
                break
        return added

    def ensure_active(self):
        """Promote the head of the queue to active if nothing is testing."""
        if self.active is None and self.queue:
            self.active = self.queue.pop(0)
        return self.active

    def complete_active(self):
        """Archive the finished active experiment and clear the slot."""
        if self.active is not None:
            self.archive.insert(0, self.active.progress())
            self.archive = self.archive[: self.max_archive]
            # allow the same pair to be re-queued later if the report keeps flagging it
            key = tuple(sorted((self.active.a, self.active.b)))
            self.seen.discard(key)
            self.active = None

    def state(self):
        return {
            "queued": [{"pair": e.pair, "a": e.a, "b": e.b, "state": QUEUED,
                        "source": e.source, "rationale": e.rationale}
                       for e in self.queue],
            "active": self.active.progress() if self.active else None,
            "archive": self.archive[:12],
            "counts": {"queued": len(self.queue),
                       "concluded": len(self.archive)},
        }

    def to_dict(self):
        return {
            "queue": [e.to_dict() for e in self.queue],
            "active": self.active.to_dict() if self.active else None,
            "archive": self.archive[: self.max_archive],
            "seen": [list(k) for k in self.seen],
        }

    def load_dict(self, d):
        if not d:
            return
        self.queue = [FactorialExperiment.from_dict(x) for x in d.get("queue", [])]
        self.active = (FactorialExperiment.from_dict(d["active"])
                       if d.get("active") else None)
        self.archive = d.get("archive", []) or []
        self.seen = set(tuple(sorted(k)) for k in d.get("seen", []) if len(k) == 2)


# --- small stats helpers (stdlib only) ---------------------------------
def _mean(xs):
    if not xs:
        return None
    return sum(xs) / len(xs)


def _t_sf_2sided(t, df):
    """Two-sided survival function of Student's t via a regularized incomplete
    beta. Pure stdlib; adequate for the small df we use here."""
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    p = _betai(df / 2.0, 0.5, x)
    return max(0.0, min(1.0, p))


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a
    return front * _betacf(a, b, x)


def _betacf(a, b, x, itmax=200, eps=3e-7):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h
