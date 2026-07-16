# Research design

PetriLab asks one question: **can a system, under the right conditions, sustain open-ended
evolution instead of collapsing into homeostasis?** This document describes the method and the
phase plan that produced the evidence chain in [`../RESULTS.md`](../RESULTS.md).

## The invariant: fixed rules, tunable conditions

The engine's rules are frozen. Cells are born, connect, spend energy, and die by laws that never
change. Only **conditions** may be tuned — energy influx, connection cost, mutation rate, seasons,
and opt-in feature flags. Every feature flag defaults **OFF**, so the default state is always the
control. A finding is only accepted if turning one condition-knob moves a primary metric past a
pre-declared threshold, versus an identical control.

## Measuring emergence

We refuse to judge "life" by eye. The network view is intentionally secondary; **emergence is
statistical, not visual.** The metrics in `metrics.py`:

- **complexity** — information richness of the connection structure.
- **modularity** — clustering into separable groups (proto-"organs").
- **cycles** — closed feedback loops (prerequisite for memory/computation).
- **depth** — longest signal chain (computational depth).
- **persistence** — stability of structures over time.
- **spatial** — spatial coherence: do connected cells physically cluster into tissue?
- **communication** — how strongly cells use the wireless signaling layer.
- **innovation** (the key metric) — phase transitions per 1000 generations. Near 0 = dead
  equilibrium; high = open-ended, still inventing.

## Method: one mechanism at a time

Each hypothesis isolates a single mechanism and runs it ON vs. OFF across shared seeds. The
primary metric and threshold are declared *before* the run. Results — confirmations and nulls
alike — are appended to an immutable evidence chain. See [`GARDENER.md`](GARDENER.md) for how the
autonomous loop drives this.

## Phase plan

### Phase 0 — the physics baseline
Establish that basic condition-knobs behave. **H0001** (cheaper edges → +138% complexity)
confirmed the engine is sensitive to conditions in a legible way. **H0002** (prune threshold)
came back inactive — edge cost already dominates pruning.

### Phase 1 — self-organization (chemotaxis)
Give cells receptors and a chemotactic pull toward connected neighbors. **H0006** confirmed
(+175% spatial): connected cells cluster physically into tissue. The first *self-organization*
you can see — but, crucially, measured, not eyeballed.

### Breaking homeostasis (seasons, endogenous selection, catastrophes)
- **H0003** ✅ (+375% innovation): cyclic seasons keep the system adapting instead of settling.
- **H0004** ✅ (+3.7% recovery): endogenous selection (light follows activity) improves
  post-shock recovery.
- **H0005** ⚪: catastrophes *alone* don't raise lasting innovation — the system resets without
  learning. A useful null: shocks without memory aren't enough.

### Phase 2 — heredity
- **v1, H0007** ⚪: inherit a single bias scalar from the mother cell. No effect. A scalar is too
  thin to carry selection.
- **v2, H0008** ✅ (+27% complexity): inherit the mother cell's **connection pattern** (a subgraph)
  with mutation. This carries selection. **Information lives in the connections, not the cells.**

### Phase 3 — signaling
**H0009** ✅ (+233% innovation): cells gain two genes — emit and sensitivity — and communicate
through a wireless chemical layer on top of the wired structure. The result is a *restless*
system: innovation soars while complexity stays flat. That combination — perpetual novelty
without runaway complexity — is the open-ended quality the project set out to find.

## What's next

Later phases point toward coupling the signaling output to a simple agent inside a small world,
to test whether evolution can learn to *control* something — sense → process → act. That is a
larger build and is not part of this release.
