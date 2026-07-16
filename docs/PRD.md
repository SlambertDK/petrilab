# PRD — PetriLab (open-source release)

## One-liner
An open artificial-life sandbox where complexity emerges from fixed physics — and an
**autonomous research gardener** forms hypotheses, runs controlled experiments, and records
an honest evidence chain, unattended.

## Why this is worth releasing
Most ALife demos show pretty patterns. PetriLab's differentiator is the **auto-research loop**:
a scheduled agent that treats the simulation as a lab — proposing falsifiable hypotheses,
testing each against a control (one mechanism at a time), and logging confirmations *and*
honest negative results. The repo ships a real evidence chain (9 hypotheses, 6 confirmed,
3 inconclusive/negative) produced this way.

## Target audience
ALife / complexity researchers, generative-systems tinkerers, and anyone curious about
open-ended evolution. Not a product with customers — a **research artifact** meant to be
read, run, forked, and cited.

## Scope (this release)
IN:
- Deterministic engine (seeded, reproducible) with 4 proven feature-flags:
  seasons, endogenous selection, chemotaxis (phase 1), structural heredity (phase 2),
  signaling (phase 3). Each flag defaults OFF = control.
- Metrics layer (complexity, modularity, cycles, depth, persistence, spatial, communication).
- Experiment harness: run one condition vs. control across seeds, aggregate, judge.
- Research module: propose / test / register hypotheses -> findings log.
- Live web dashboard (FastAPI) with auto-zoom network view + responsive mobile/desktop UI.
- Auto-research "gardener" pattern documented so anyone can wire it to their own scheduler.

OUT (explicitly):
- The owner's personal gardener logbook and live state (kept private; repo starts clean).
- Any machine-specific service files, tokens, Tailscale/host references.
- Product/marketing framing — this is research, framed as research.

## Non-negotiables
- **English throughout**: code comments, identifiers where user-facing, and 100% of UI labels.
- **Reproducible**: `pip install -r requirements.txt` + one command to run. Fresh-clone verified.
- **No secrets, no personal data, no hardcoded paths.** Already clean; keep it clean.
- **Honest science**: negative results stay in RESULTS.md. That's the point.
- **Fixed rules, tunable conditions**: the core invariant. Rules (physics) never change;
  only conditions (energy, cost, mutation, seasons, flags) do. This is what makes findings valid.

## Deliverables & task breakdown
1. Clean staging repo (no venv, no live data). ✅
2. Translate engine.py — comments + any user-facing strings -> English.
3. Translate metrics.py, experiment.py, research.py -> English.
4. Translate the entire dashboard UI in server.py -> English labels + help overlay.
5. README.md — narrative (homeostasis break), the gardener loop, results table, quickstart, screenshot.
6. LICENSE (MIT, Henrik Lambert), requirements.txt, .gitignore, run.sh.
7. RESULTS.md (evidence chain from findings.md), docs/RESEARCH.md (design), docs/GARDENER.md (auto-research how-to).
8. Verify: fresh venv, run server, smoke-test endpoints + a headless experiment.
9. Create public GitHub repo, push, verify a clean clone installs and runs.

## Success criteria
- A stranger can `git clone`, install, run, and see the dashboard in <5 minutes.
- They understand within one screen of README *what* it is and *why* it matters.
- They can reproduce at least one confirmed finding by running the experiment harness.
- Zero Danish strings remain in any user-facing surface.
- Zero secrets or personal data in git history.
