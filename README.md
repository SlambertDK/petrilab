# PetriLab 🧫

**An open artificial-life sandbox where complexity emerges from fixed physics — and an
autonomous research gardener forms hypotheses, runs controlled experiments, and records an
honest evidence chain, unattended.**

Most artificial-life demos show pretty patterns. PetriLab's differentiator is the
**auto-research loop**: a scheduled agent treats the simulation as a laboratory. It proposes
falsifiable hypotheses, tests each one against a control (one mechanism at a time), and logs
both confirmations *and* honest negative results. This repository ships a real evidence chain
of 9 hypotheses produced this way — 6 confirmed, 3 inconclusive.

---

## The core idea

A digital petri dish. Cells grow, form connections, and die under **fixed natural laws**.
The rules — the system's "physics" — never change. Only the **conditions** (energy influx,
connection cost, mutation rate, seasons) may be tuned. That single invariant is what makes the
findings valid:

> **Fixed rules, tunable conditions.** If you could change the rules to get a result, you'd
> prove nothing. By freezing the rules and only turning condition-knobs, every confirmed effect
> is a real property of the system, not of the experimenter.

The question we chase: **can a system, under the right conditions, keep evolving forever
instead of settling into a dead equilibrium (homeostasis)?**

---

## What makes it different: the research gardener

An autonomous "gardener" tends the dish on a schedule (e.g. every 6 hours). It is **not** allowed
to touch the rules. It may only:

1. Read the current state and metrics.
2. Propose a falsifiable hypothesis about a condition or feature-flag.
3. Run a controlled A/B experiment (feature ON vs. control OFF) across seeds.
4. Judge the result against a pre-declared threshold.
5. Log the outcome — **including negative results** — to an append-only evidence chain.

This turns the simulation into a self-driving laboratory. The `research.py` module and the
gardener pattern (see [`docs/GARDENER.md`](docs/GARDENER.md)) let you wire it to any scheduler.

---

## Results so far

Every finding below was produced by the controlled experiment harness. Negative and
inconclusive results are kept on purpose — that's the point.

| ID | Hypothesis (mechanism) | Primary metric | Effect | Verdict |
|----|------------------------|----------------|--------|---------|
| H0001 | Lower edge cost raises complexity | complexity | **+138%** | ✅ confirmed |
| H0002 | Prune threshold is inactive | complexity | −4% | ⚪ inconclusive |
| H0003 | Seasons (cyclic light) break homeostasis | innovation | **+375%** | ✅ confirmed |
| H0004 | Endogenous selection raises post-shock recovery | recovery | **+3.7%** | ✅ confirmed |
| H0005 | Catastrophes alone don't raise lasting innovation | innovation | −25% | ⚪ inconclusive |
| H0006 | Chemotaxis (phase 1) → cells self-organize into tissue | spatial | **+175%** | ✅ confirmed |
| H0007 | Bias heredity (phase 2 v1) raises persistence | persistence | −0.5% | ⚪ inconclusive |
| H0008 | **Structural** heredity (phase 2 v2) raises complexity | complexity | **+27%** | ✅ confirmed |
| H0009 | Signaling molecules (phase 3) raise innovation | innovation | **+233%** | ✅ confirmed |

**The key insight** came from a *failure*: H0007 (inheriting a single bias scalar) did nothing,
but H0008 (inheriting the mother cell's **connection pattern**) worked. Information lives in the
*connections*, not in the cells. That reframing drove the whole phase-2/phase-3 design.

Full evidence chain with timestamps and thresholds: [`RESULTS.md`](RESULTS.md).

---

## Quickstart

Requires Python 3.11+.

    git clone https://github.com/slambertdk/petrilab.git
    cd petrilab
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ./run.sh

Then open **http://localhost:8770** in your browser. The dashboard is fully responsive
(desktop + mobile) and has a built-in **About** overlay explaining every metric.

### Run a controlled experiment yourself

Reproduce a confirmed finding from the command line:

    .venv/bin/python experiment.py

### Drive the research module

    .venv/bin/python research.py --help

---

## Architecture

| File | Role |
|------|------|
| `engine.py` | The deterministic simulation engine. Seeded and reproducible. Six feature flags (seasons, endogenous selection, chemotaxis, structural heredity, signaling), all default **OFF** = control. |
| `metrics.py` | Emergence metrics: complexity, modularity, cycles, depth, persistence, spatial coherence, communication. |
| `experiment.py` | Controlled experiment harness: run one condition vs. control across seeds, aggregate, judge. |
| `research.py` | The research module: propose / test / register hypotheses → findings log. |
| `server.py` | FastAPI live dashboard with auto-zoom network view + responsive UI. |

See [`docs/RESEARCH.md`](docs/RESEARCH.md) for the full research design and
[`docs/GARDENER.md`](docs/GARDENER.md) for the auto-research how-to.

---

## Design principles

- **Reproducible.** Same seed = same run. Every experiment can be repeated.
- **Honest science.** Negative results stay in the record.
- **One mechanism at a time.** Each feature is tested in isolation against a control.
- **Fixed rules.** The engine's laws are frozen; only conditions vary.

---

## License

MIT © Henrik Lambert. See [`LICENSE`](LICENSE).

This is a research artifact, released so others can read, run, fork, and build on it.
If it's useful in your own work, a citation or a link back is appreciated.
