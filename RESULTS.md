# Evidence chain

Every entry below was produced by the controlled experiment harness (`experiment.py`),
one mechanism at a time, tested against a control. Confirmed, inconclusive, and negative
results are all kept — that honesty is the point of the project.

Each experiment runs a feature **ON** (condition B) versus **OFF** (control A) across seeds,
aggregates a primary metric, and judges it against a pre-declared threshold.

## Confirmed

| ID | Mechanism | Metric | Control (A) | Condition (B) | Effect | Threshold |
|----|-----------|--------|-------------|---------------|--------|-----------|
| **H0001** | Lower edge cost → cheaper connections → richer network | complexity | 9.886 | 23.556 | **+138.3%** | B>A ≥20% |
| **H0003** | Seasons (cyclic light) break homeostasis; the system keeps evolving | innovation | 2.0 | 9.5 | **+375.0%** | B>A ≥50% |
| **H0004** | Endogenous selection (light follows activity) raises post-shock recovery | recovery | 0.978 | 1.014 | **+3.7%** | B>A ≥3% |
| **H0006** | Chemotaxis (phase 1): receptors + attraction → cells self-organize into tissue | spatial | 0.361 | 0.992 | **+174.8%** | B>A ≥30% |
| **H0008** | Structural heredity (phase 2 v2): daughter inherits mother's **connections** + mutation | complexity | 9.886 | 12.527 | **+26.7%** | B>A ≥15% |
| **H0009** | Signaling molecules (phase 3): cells emit + sense signals, affecting neighbors wirelessly | innovation | 1.5 | 5.0 | **+233.3%** | B>A ≥30% |

## Inconclusive / negative

| ID | Mechanism | Metric | Control (A) | Condition (B) | Effect | Threshold | Note |
|----|-----------|--------|-------------|---------------|--------|-----------|------|
| **H0002** | Prune threshold is inactive (edge cost already does the pruning) | complexity | 9.886 | 9.449 | −4.4% | either ≥15% | No measurable effect — edge cost dominates. |
| **H0005** | Catastrophes alone don't raise lasting innovation (system resets, doesn't learn) | innovation | 2.0 | 1.5 | −25.0% | B>A ≥50% | Confirms the *null*: shocks without memory don't drive open-endedness. |
| **H0007** | Bias heredity (phase 2 v1): daughter inherits a single bias scalar + mutation | persistence | 37.534 | 37.364 | −0.5% | B>A ≥15% | **The productive failure.** A scalar is too thin to carry selection — which pointed directly at H0008. |

## The lesson from H0007 → H0008

H0007 tried to inherit a single number (bias) and moved nothing. H0008 inherited the mother
cell's **connection pattern** — a subgraph — and complexity jumped +27%. The takeaway that
shaped the rest of the design:

> **Information lives in the connections, not in the cells.** Heritable structure carries
> selection; a heritable scalar does not.

## Phase progression

1. **Phase 1 — chemotaxis** ✅ (+175% spatial): cells organize into tissue.
2. **Phase 2 v1 — bias heredity** ⚪ (inconclusive): scalar inheritance too thin.
3. **Phase 2 v2 — structural heredity** ✅ (+27% complexity): connection inheritance carries selection.
4. **Phase 3 — signaling** ✅ (+233% innovation): a wireless chemical layer keeps the system
   restless — high innovation with flat complexity, i.e. the open-ended quality the project chases.
