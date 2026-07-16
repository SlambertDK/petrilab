# The research gardener — auto-research how-to

The gardener is what turns PetriLab from a simulation into a **self-driving laboratory**.
It is a scheduled agent (a cron job, a script, an LLM-driven loop — your choice) that tends
the dish autonomously and keeps an honest evidence chain.

## The one rule

> The gardener may change **conditions**, never **rules**.

Conditions are the tunable knobs: energy influx, edge cost, mutation rate, season amplitude,
and the feature flags (chemotaxis, structural heredity, signaling, …). The rules — the engine's
physics in `engine.py` — are frozen. This separation is what makes every finding valid: a result
obtained by turning a condition-knob is a real property of the system, not an artifact of the
experimenter rewriting the laws mid-experiment.

## The loop

Each time the gardener runs, it performs one research cycle:

1. **Observe.** Read `/api/state` (or call the engine directly): current metrics, trends,
   living nodes, active conditions, recent phase transitions.
2. **Propose.** Form a single falsifiable hypothesis about one condition or feature flag,
   with a predicted primary metric and a pre-declared threshold. Register it via `research.py`.
3. **Test.** Run a controlled experiment with `experiment.py`: the feature **ON** (condition B)
   versus **OFF** (control A), across multiple seeds. One mechanism at a time — never two.
4. **Judge.** Compare the aggregated primary metric against the threshold. Confirmed,
   inconclusive, or refuted.
5. **Record.** Append the verdict — *including negative results* — to the evidence chain
   (`data/findings.md`, `data/hypotheses.json`). Never overwrite, never hide a null.

## Wiring it to a scheduler

The reference deployment runs the gardener every 6 hours. Any scheduler works. A minimal cron
entry that runs a gardener script four times a day:

    0 */6 * * * cd /path/to/petrilab && .venv/bin/python gardener.py >> data/gardener.log 2>&1

Your `gardener.py` (not shipped — it's deployment-specific) should implement the five steps
above. The building blocks are all here:

- `research.py` — propose / test / register / list hypotheses.
- `experiment.py` — `run_condition(...)` and the `DEFAULTS` baseline for A/B runs.
- `server.py` `/api/state` — live observation surface.

## Why negative results are mandatory

The gardener's credibility rests on keeping the nulls. H0002, H0005 and H0007 in
[`../RESULTS.md`](../RESULTS.md) all failed or came back inconclusive — and H0007's failure is
exactly what pointed the way to H0008's success. A research log that only records wins is
marketing, not science. The gardener logs everything.

## Guardrails worth keeping

- **One mechanism per experiment.** If you test two flags at once, you can't attribute the effect.
- **Declare the threshold before running.** No moving the goalposts after seeing the data.
- **Same seeds for A and B.** Control the randomness so the difference is the mechanism, not luck.
- **Observer's frame stays separate.** A human tuning the dashboard must not touch the gardener's
  condition-knobs, or the two data streams contaminate each other. In the UI these are locked
  and shown read-only for exactly this reason.
