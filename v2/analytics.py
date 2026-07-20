#!/usr/bin/env python3
"""
analytics.py — the data-science layer for PetriLab.

Reads the gardener's observation log (data/observations.jsonl), builds simple,
honest statistical models over it, and renders a self-contained visual HTML
report (inline SVG, no external dependencies). Everything here is descriptive
and reproducible: no black boxes, every number traces back to the log.

Models built:
  1. Correlation matrix (Pearson r) between every condition knob and every
     outcome variable — "does this condition co-move with success?"
  2. Per-knob significance (t-test of Pearson r) — "is that correlation real
     or chance?"  |t| via r*sqrt((n-2)/(1-r^2)).
  3. Univariate linear regression outcome ~ knob (slope + R^2) for the headline
     outcomes (complexity, novelty, score).
  4. A "recipe for big cells": bucket experiments by each knob into low/high and
     compare mean complexity — the conditions that co-occur with the giant cells.

Exposed:
  build_models(path)      -> dict of models (JSON-serializable, for the API)
  render_report(models)   -> HTML string (the visual report)
  main()                  -> writes report.html next to the log
"""
import json
import math
import os
import html
from datetime import datetime, timezone
import stats_core as sc

HERE = os.path.dirname(os.path.abspath(__file__))
OBS_PATH = os.path.join(HERE, "data", "observations.jsonl")
REPORT_PATH = os.path.join(HERE, "report.html")

# outcome variables we model (targets)
OUTCOMES = ["complexity", "novelty", "ecology", "score", "cells", "max_genome"]
# condition knobs (features) — discovered from the data, but this is the canonical order
KNOBS = ["energy_influx", "mutation_rate", "gene_mut_rate", "signaling",
         "seasons", "season_len", "structural_heredity"]


# ----------------------------------------------------------------------
def load_rows(path=OBS_PATH, limit=20000):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows[-limit:]


def _col(rows, key):
    """Extract a numeric column, tolerating the nested 'conditions' dict."""
    out = []
    for r in rows:
        if key in KNOBS:
            v = (r.get("conditions") or {}).get(key)
        else:
            v = r.get(key)
        out.append(v if isinstance(v, (int, float)) else None)
    return out


def _pearson(xs, ys):
    """Pearson r over paired non-null values. Returns (r, n)."""
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None, n
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    if sxx < 1e-12 or syy < 1e-12:
        return None, n
    return sxy / math.sqrt(sxx * syy), n


def _r_significance(r, n):
    """t-test of a Pearson r: t = r*sqrt((n-2)/(1-r^2)). Returns (t, verdict)."""
    if r is None or n < 4 or abs(r) >= 1.0:
        return None, "insufficient"
    t = r * math.sqrt((n - 2) / (1 - r * r))
    if abs(t) >= 2.58:
        verdict = "significant"     # p < 0.01
    elif abs(t) >= 1.96:
        verdict = "likely"          # p < 0.05
    else:
        verdict = "chance"
    return t, verdict


def _linreg(xs, ys):
    """Univariate OLS ys ~ xs. Returns dict slope, intercept, r2, n."""
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx < 1e-12:
        return None
    slope = sxy / sxx
    intercept = my - slope * mx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 1e-12 else 0.0
    return {"slope": slope, "intercept": intercept, "r2": r2, "n": n}


def _recipe(rows, target="complexity"):
    """For each knob, split experiments at the knob's median into low/high and
    compare mean target. The 'lift' = mean(high) - mean(low) tells you which
    direction of each condition co-occurs with bigger cells."""
    out = []
    ys_all = _col(rows, target)
    for k in KNOBS:
        xs = _col(rows, k)
        pairs = [(x, y) for x, y in zip(xs, ys_all)
                 if isinstance(x, (int, float)) and isinstance(y, (int, float))]
        if len(pairs) < 8:
            continue
        xs_sorted = sorted(p[0] for p in pairs)
        med = xs_sorted[len(xs_sorted) // 2]
        low = [y for x, y in pairs if x <= med]
        high = [y for x, y in pairs if x > med]
        if not low or not high:
            continue
        ml = sum(low) / len(low)
        mh = sum(high) / len(high)
        out.append({"knob": k, "low_mean": ml, "high_mean": mh,
                    "lift": mh - ml, "median": med,
                    "n_low": len(low), "n_high": len(high)})
    out.sort(key=lambda d: -abs(d["lift"]))
    return out


# ----------------------------------------------------------------------
def build_models(path=OBS_PATH):
    rows = load_rows(path)
    n = len(rows)
    models = {
        "n_observations": n,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "gen_range": None,
        "correlations": {},   # outcome -> [{knob, r, rho, n, neff, t, p, p_adj, verdict}]
        "regressions": {},    # outcome -> {knob -> linreg}
        "recipe": [],         # knob lift toward complexity
        "interventions": [],  # per-knob paired-delta causal tests (the strong evidence)
        "trend": {},          # Mann-Kendall on complexity over time
        "outcome_summary": {},
        "method_notes": [],
    }
    if n == 0:
        return models

    gens = [r.get("gen") for r in rows if isinstance(r.get("gen"), (int, float))]
    if gens:
        models["gen_range"] = [min(gens), max(gens)]

    # outcome summary stats
    for oc in OUTCOMES:
        col = [v for v in _col(rows, oc) if isinstance(v, (int, float))]
        if col:
            m = sum(col) / len(col)
            models["outcome_summary"][oc] = {
                "mean": round(m, 4), "min": round(min(col), 4),
                "max": round(max(col), 4), "n": len(col)}

    # ---- correlation matrix, autocorrelation-corrected + FDR across the family ----
    # Build every knob x outcome test first, collect p-values, THEN apply
    # Benjamini-Hochberg once over the whole family (methodology 1.2 + 2.2).
    raw = {}          # (oc, knob) -> entry dict
    pvals = []        # [((oc,knob), p)]
    for oc in OUTCOMES:
        ys = _col(rows, oc)
        rho_y = sc.lag1_autocorr([v for v in ys if isinstance(v, (int, float))])
        for k in KNOBS:
            xs = _col(rows, k)
            r, cnt = sc.pearson(xs, ys)
            rho_x = sc.lag1_autocorr([v for v in xs if isinstance(v, (int, float))])
            # use the larger autocorrelation of the two series (conservative)
            rho = max(rho_x, rho_y)
            t, dfe, p, ne = sc.corr_ttest_neff(r, cnt, rho)
            sp, _ = sc.spearman(xs, ys)
            entry = {
                "knob": k, "r": (round(r, 3) if r is not None else None),
                "rho_spearman": (round(sp, 3) if sp is not None else None),
                "n": cnt, "neff": (round(ne, 1) if ne is not None else None),
                "autocorr": round(rho, 3),
                "t": (round(t, 2) if t is not None else None),
                "p": (round(p, 5) if p is not None else None),
                "p_adj": None, "verdict": "insufficient",
            }
            raw[(oc, k)] = entry
            pvals.append(((oc, k), p))

    bh = sc.benjamini_hochberg(pvals, alpha=0.10)
    for key, entry in raw.items():
        adj = bh.get(key, {})
        entry["p_adj"] = (round(adj["p_adj"], 5)
                          if adj.get("p_adj") is not None else None)
        # verdict now reflects Pearson/Spearman concordance AND FDR survival
        if entry["p"] is None:
            entry["verdict"] = "insufficient"
        elif adj.get("reject"):
            # concordance check: linear + rank must agree in sign
            r, sp = entry["r"], entry["rho_spearman"]
            concord = (r is not None and sp is not None and (r > 0) == (sp > 0))
            entry["verdict"] = "significant" if concord else "significant-nonlinear"
        else:
            entry["verdict"] = "chance"
    for oc in OUTCOMES:
        entries = [raw[(oc, k)] for k in KNOBS]
        entries.sort(key=lambda e: -(abs(e["r"]) if e["r"] is not None else -1))
        models["correlations"][oc] = entries

    models["method_notes"] = [
        "Correlation t-tests use the AR(1) effective sample size n_eff = "
        "n(1-rho)/(1+rho), not raw n, so autocorrelation in the run cannot "
        "manufacture significance.",
        "All %d knob x outcome tests are corrected together with "
        "Benjamini-Hochberg FDR at alpha=0.10 — a single 'significant' needs to "
        "survive the whole family, not just its own p<0.05." % len(pvals),
        "'significant' also requires Pearson and Spearman to agree in sign "
        "(linear + rank concordance); otherwise it is flagged nonlinear.",
    ]

    # regressions for headline outcomes
    for oc in ("complexity", "novelty", "score"):
        ys = _col(rows, oc)
        reg = {}
        for k in KNOBS:
            xs = _col(rows, k)
            lr = _linreg(xs, ys)
            if lr:
                reg[k] = {kk: round(vv, 6) for kk, vv in lr.items()}
        models["regressions"][oc] = reg

    # ---- causal layer: per-knob paired intervention deltas (methodology 3) ----
    # This is the STRONG evidence: each experiment is a real before/after nudge,
    # and every delta (kept AND reverted) is logged, so there is no selection bias.
    by_knob = {}
    for r in rows:
        k = r.get("knob")
        d = r.get("delta")
        if k in KNOBS and isinstance(d, (int, float)):
            by_knob.setdefault(k, []).append(d)
    iv = []
    for k in KNOBS:
        deltas = by_knob.get(k, [])
        if len(deltas) < 6:
            continue
        w = sc.wilcoxon_signed(deltas)
        st = sc.sign_test(deltas)
        dz = sc.cohens_dz(deltas)
        mean_d = sum(deltas) / len(deltas)
        iv.append({
            "knob": k, "n": len(deltas), "mean_delta": round(mean_d, 4),
            "cohens_dz": (round(dz, 3) if dz is not None else None),
            "wilcoxon_z": (round(w["z"], 2) if w["z"] is not None else None),
            "wilcoxon_p": (round(w["p"], 5) if w["p"] is not None else None),
            "sign_p": (round(st["p"], 5) if st["p"] is not None else None),
            "p": w["p"], "p_adj": None, "verdict": "insufficient",
        })
    # FDR across the intervention family too
    ivbh = sc.benjamini_hochberg([(e["knob"], e["p"]) for e in iv], alpha=0.10)
    for e in iv:
        adj = ivbh.get(e["knob"], {})
        e["p_adj"] = (round(adj["p_adj"], 5) if adj.get("p_adj") is not None else None)
        if e["p"] is None:
            e["verdict"] = "insufficient"
        elif adj.get("reject"):
            e["verdict"] = "causal-up" if e["mean_delta"] > 0 else "causal-down"
        else:
            e["verdict"] = "no-effect"
    iv.sort(key=lambda e: -(abs(e["mean_delta"])))
    models["interventions"] = iv

    # ---- robust trend on complexity over time (methodology 6) ----
    cx_series = [r.get("complexity") for r in rows
                 if isinstance(r.get("complexity"), (int, float))]
    mk = sc.mann_kendall(cx_series)
    mk["sens_slope"] = (round(sc.sens_slope(cx_series), 5)
                        if sc.sens_slope(cx_series) is not None else None)
    models["trend"] = mk

    # recipe for big cells
    models["recipe"] = _recipe(rows, "complexity")
    return models


# ----------------------------------------------------------------------
# ---- tiny inline-SVG chart helpers (no dependencies) ----
def _bar_chart(items, value_key, label_key, width=560, row_h=30,
               pos_color="#4ade80", neg_color="#f87171", fmt="{:+.3f}"):
    """Horizontal diverging bar chart from a list of dicts."""
    if not items:
        return "<p class='muted'>no data yet</p>"
    vals = [it.get(value_key) or 0 for it in items]
    mx = max((abs(v) for v in vals), default=1) or 1
    mid = width * 0.42
    h = row_h * len(items) + 10
    svg = [f"<svg viewBox='0 0 {width} {h}' width='100%' height='{h}' font-family='ui-monospace,monospace'>"]
    for i, it in enumerate(items):
        v = it.get(value_key) or 0
        y = i * row_h + 6
        bar = (v / mx) * (width - mid - 90)
        x = mid if v >= 0 else mid + bar
        color = pos_color if v >= 0 else neg_color
        label = html.escape(str(it.get(label_key, "")))
        svg.append(f"<text x='{mid-8}' y='{y+row_h*0.6}' text-anchor='end' "
                   f"fill='#cbd5e1' font-size='12'>{label}</text>")
        svg.append(f"<rect x='{x:.1f}' y='{y}' width='{abs(bar):.1f}' height='{row_h*0.62:.1f}' "
                   f"rx='3' fill='{color}' opacity='0.85'/>")
        svg.append(f"<text x='{mid + (bar if v>=0 else 0) + (6 if v>=0 else -6):.1f}' "
                   f"y='{y+row_h*0.6}' text-anchor='{'start' if v>=0 else 'end'}' "
                   f"fill='#94a3b8' font-size='11'>{fmt.format(v)}</text>")
    svg.append(f"<line x1='{mid}' y1='0' x2='{mid}' y2='{h}' stroke='#334155' stroke-width='1'/>")
    svg.append("</svg>")
    return "".join(svg)


def _verdict_badge(verdict):
    colors = {"significant": "#4ade80", "significant-nonlinear": "#a78bfa",
              "likely": "#fbbf24", "chance": "#64748b", "no-effect": "#64748b",
              "causal-up": "#4ade80", "causal-down": "#f87171",
              "insufficient": "#475569"}
    label = {"significant": "REAL (FDR)", "significant-nonlinear": "nonlinear (FDR)",
             "likely": "likely", "chance": "chance", "no-effect": "no effect",
             "causal-up": "CAUSAL ↑", "causal-down": "CAUSAL ↓",
             "insufficient": "too few"}.get(verdict, verdict)
    c = colors.get(verdict, "#64748b")
    return (f"<span style='background:{c}22;color:{c};border:1px solid {c}55;"
            f"border-radius:6px;padding:1px 7px;font-size:11px'>{label}</span>")


def _corr_table(entries):
    rows = ["<table class='corr'><tr><th>condition</th><th>r</th><th>ρ</th>"
            "<th>n→n_eff</th><th>p(adj)</th><th>verdict</th></tr>"]
    for e in entries:
        r = e["r"]
        c = "#4ade80" if (r or 0) >= 0 else "#f87171"
        neff = e.get("neff")
        nn = f"{e['n']}→{neff:.0f}" if neff is not None else str(e["n"])
        padj = e.get("p_adj")
        padj_s = "" if padj is None else f"{padj:.3f}"
        sp = e.get("rho_spearman")
        rows.append(
            f"<tr><td>{html.escape(e['knob'])}</td>"
            f"<td style='color:{c}'>{'' if r is None else f'{r:+.3f}'}</td>"
            f"<td>{'' if sp is None else f'{sp:+.2f}'}</td>"
            f"<td class='muted'>{nn}</td>"
            f"<td>{padj_s}</td>"
            f"<td>{_verdict_badge(e['verdict'])}</td></tr>")
    rows.append("</table>")
    return "".join(rows)


def render_report(models):
    n = models["n_observations"]
    gen_range = models.get("gen_range")
    gr = f"gen {gen_range[0]:,}–{gen_range[1]:,}" if gen_range else "—"

    # headline: what correlates with complexity (the "big cells")
    cplx = models["correlations"].get("complexity", [])
    strongest = next((e for e in cplx if e["verdict"] in
                      ("significant", "significant-nonlinear")), None)

    parts = [f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PetriLab — Data-Science Report</title>
<style>
 body{{margin:0;background:#0a0e14;color:#e2e8f0;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;line-height:1.55}}
 .wrap{{max-width:860px;margin:0 auto;padding:32px 20px 80px}}
 h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:19px;margin:38px 0 10px;color:#7dd3fc}}
 .sub{{color:#64748b;font-size:13px;margin-bottom:26px}}
 .card{{background:#0f1620;border:1px solid #1e293b;border-radius:14px;padding:18px 20px;margin:16px 0}}
 .muted{{color:#64748b}} .lede{{color:#cbd5e1}}
 table.corr{{width:100%;border-collapse:collapse;font-size:13px;font-family:ui-monospace,monospace}}
 table.corr th{{text-align:left;color:#64748b;font-weight:500;padding:4px 8px;border-bottom:1px solid #1e293b}}
 table.corr td{{padding:5px 8px;border-bottom:1px solid #141c28}}
 .kpi{{display:inline-block;margin-right:26px}} .kpi b{{font-size:22px;color:#f1f5f9}} .kpi span{{color:#64748b;font-size:12px;display:block}}
 .headline{{font-size:15px;background:#132018;border:1px solid #1f3a29;border-radius:12px;padding:14px 16px;color:#bbf7d0}}
 code{{background:#131b26;padding:1px 6px;border-radius:5px;font-size:12px;color:#93c5fd}}
 a{{color:#38bdf8}}
</style></head><body><div class='wrap'>
<h1>PetriLab — Data-Science Report</h1>
<div class='sub'>Auto-generated by the gardener from {n:,} logged experiments · {gr} · {models['generated_utc']}</div>
"""]

    if n < 8:
        parts.append(f"""<div class='card'><p class='lede'>The gardener has logged
<b>{n}</b> experiments so far. Models appear here once at least 8 experiments are
recorded — the observation log is filling up live as the gardener runs.</p>
<p class='muted'>The dataset is written to <code>data/observations.jsonl</code>,
one row per experiment: the condition it changed, the full condition vector, and
the outcome (complexity, novelty, ecology, cell count, biggest genome).</p></div>
</div></body></html>""")
        return "".join(parts)

    # KPIs
    os_ = models["outcome_summary"]
    def kpi(label, key, fmt="{:.1f}"):
        v = os_.get(key, {}).get("mean")
        mx = os_.get(key, {}).get("max")
        if v is None:
            return ""
        return (f"<div class='kpi'><b>{fmt.format(v)}</b>"
                f"<span>mean {label} (max {fmt.format(mx)})</span></div>")
    parts.append("<div class='card'>"
                 + kpi("complexity", "complexity")
                 + kpi("novelty", "novelty", "{:.3f}")
                 + kpi("cells", "cells", "{:.0f}")
                 + kpi("max genome", "max_genome", "{:.0f}")
                 + "</div>")

    # headline finding
    if strongest:
        d = "raising" if (strongest["r"] or 0) > 0 else "lowering"
        parts.append(f"<div class='headline'>📈 <b>Strongest signal:</b> "
                     f"<code>{html.escape(strongest['knob'])}</code> correlates with "
                     f"complexity (r={strongest['r']:+.3f}, {_verdict_badge(strongest['verdict'])}). "
                     f"The data says {d} it co-moves with bigger, more complex cells — "
                     f"not chance.</div>")
    else:
        parts.append("<div class='headline'>🔍 <b>No condition yet shows a "
                     "statistically significant correlation with complexity.</b> "
                     "So far the big-cell moments look like chance / oscillation, "
                     "not a controllable recipe. This is an honest null result — "
                     "the gardener keeps probing.</div>")

    # correlation section — one table per headline outcome
    parts.append("<h2>1 · What correlates with success?</h2>")
    parts.append("<p class='lede'>Pearson correlation between each condition and each "
                 "outcome, with a t-test verdict: is the correlation <b>real</b> or "
                 "just <b>chance</b>? This is the core question — does the knob move "
                 "the outcome, or did the big cells just happen?</p>")
    for oc in ("complexity", "novelty", "score"):
        ent = models["correlations"].get(oc, [])
        if ent:
            parts.append(f"<div class='card'><b>outcome: {oc}</b>{_corr_table(ent)}</div>")

    # method notes (honesty box)
    notes = models.get("method_notes", [])
    if notes:
        parts.append("<div class='card' style='border-color:#3b2f1a;background:#171207'>"
                     "<b style='color:#fbbf24'>How significance is judged</b><ul class='muted' "
                     "style='margin:8px 0 0;padding-left:18px;font-size:12.5px'>"
                     + "".join(f"<li>{html.escape(x)}</li>" for x in notes)
                     + "</ul></div>")

    # ---- causal section: the intervention deltas (the strong evidence) ----
    iv = models.get("interventions", [])
    parts.append("<h2>2 · Does pushing a knob actually cause a change?</h2>")
    parts.append("<p class='lede'>Correlation can be confounded. But the gardener runs "
                 "<b>real interventions</b>: it nudges one knob, measures the score "
                 "before and after, and logs the change — <i>including the ones it "
                 "reverts</i>. A paired test on those before/after deltas is genuine "
                 "causal evidence, not just association. Wilcoxon signed-rank + sign "
                 "test, FDR-corrected, with Cohen's d effect size.</p>")
    if iv:
        rows = ["<table class='corr'><tr><th>knob nudged</th><th>n</th>"
                "<th>mean Δscore</th><th>Cohen's d</th><th>Wilcoxon p</th>"
                "<th>verdict</th></tr>"]
        for e in iv:
            md = e["mean_delta"]
            c = "#4ade80" if md >= 0 else "#f87171"
            wp = e.get("wilcoxon_p")
            dz = e.get("cohens_dz")
            dz_s = "" if dz is None else f"{dz:+.2f}"
            wp_s = "" if wp is None else f"{wp:.4f}"
            rows.append(
                f"<tr><td>{html.escape(e['knob'])}</td><td class='muted'>{e['n']}</td>"
                f"<td style='color:{c}'>{md:+.4f}</td>"
                f"<td>{dz_s}</td>"
                f"<td>{wp_s}</td>"
                f"<td>{_verdict_badge(e['verdict'])}</td></tr>")
        rows.append("</table>")
        parts.append("<div class='card'>" + "".join(rows) + "</div>")
    else:
        parts.append("<div class='card muted'>Not enough per-knob interventions yet "
                     "(need ≥6 nudges per knob). Filling up as the gardener runs.</div>")

    # ---- trend section: Mann-Kendall (replaces peak-envelope OLS) ----
    tr = models.get("trend", {})
    parts.append("<h2>3 · Is complexity accumulating, or just oscillating?</h2>")
    parts.append("<p class='lede'>The central question: are the complexity peaks "
                 "<b>climbing over time</b> (real open-ended accumulation, class 4) or "
                 "just <b>repeating</b> (a bounded cycle, class 2)? Tested with the "
                 "Mann–Kendall trend test + Sen's slope — nonparametric, robust to "
                 "outliers, and deflated for autocorrelation. (We deliberately do "
                 "<i>not</i> fit a line to the peak envelope; that always looks like a "
                 "rising trend even for pure oscillation.)</p>")
    if tr.get("trend") in ("rising", "falling", "no-trend"):
        tv = tr["trend"]
        tcolor = {"rising": "#4ade80", "falling": "#f87171",
                  "no-trend": "#fbbf24"}.get(tv, "#64748b")
        tlabel = {"rising": "ACCUMULATING (rising trend)",
                  "falling": "declining",
                  "no-trend": "OSCILLATION (no monotone trend)"}.get(tv, tv)
        parts.append(
            f"<div class='card'><div style='font-size:16px;color:{tcolor};"
            f"font-weight:600;margin-bottom:6px'>{tlabel}</div>"
            f"<div class='muted' style='font-size:12.5px;font-family:ui-monospace,monospace'>"
            f"Mann–Kendall z (autocorr-corrected) = {tr.get('z_ac')} · "
            f"p = {tr.get('p_ac')} · Sen's slope = {tr.get('sens_slope')} "
            f"complexity/experiment · lag-1 autocorr ρ = {tr.get('rho')} · "
            f"n = {tr.get('n')}</div></div>")
    else:
        parts.append("<div class='card muted'>Not enough complexity history yet for a "
                     "trend test.</div>")
    # recipe section
    parts.append("<h2>4 · Recipe for big cells (exploratory)</h2>")
    parts.append("<p class='lede'>Each condition split at its median into low vs. high; "
                 "the bar is the <b>lift</b> in mean complexity from low→high. Longer "
                 "green bar = pushing that condition up co-occurs with bigger cells. "
                 "This is a coarse first pass — the causal test above is the stronger "
                 "evidence; treat these bars as leads, not conclusions.</p>")
    parts.append("<div class='card'>"
                 + _bar_chart(models["recipe"], "lift", "knob", fmt="{:+.2f}")
                 + "</div>")

    # regression detail
    parts.append("<h2>5 · Linear models (complexity ~ condition)</h2>")
    parts.append("<p class='lede'>Univariate least-squares fit per condition. "
                 "Slope = complexity change per unit of the knob; R² = how much of "
                 "the variation the knob alone explains. Low R² everywhere means "
                 "complexity is driven by interactions, not any single knob.</p>")
    reg = models["regressions"].get("complexity", {})
    reg_rows = ["<table class='corr'><tr><th>condition</th><th>slope</th><th>R²</th><th>n</th></tr>"]
    for k in sorted(reg, key=lambda kk: -reg[kk]["r2"]):
        rr = reg[k]
        reg_rows.append(f"<tr><td>{html.escape(k)}</td><td>{rr['slope']:+.3f}</td>"
                        f"<td>{rr['r2']:.3f}</td><td>{rr['n']}</td></tr>")
    reg_rows.append("</table>")
    parts.append("<div class='card'>" + "".join(reg_rows) + "</div>")

    parts.append(f"""<h2>Method &amp; threats to validity</h2><p class='muted'>Every number
above is computed directly from <code>data/observations.jsonl</code> ({n:,} rows), one
row per resolved gardener experiment (kept <i>and</i> reverted, so there is no
selection bias). Correlations are autocorrelation-corrected via the AR(1) effective
sample size and cross-checked with Spearman rank correlation; the whole test family is
FDR-controlled (Benjamini–Hochberg, α=0.10). The causal layer uses paired
before/after intervention deltas (Wilcoxon signed-rank + sign test, Cohen's d). Trend
uses Mann–Kendall + Sen's slope, autocorrelation-deflated — not a fit to the peak
envelope. Known limits: a single trajectory (n at the run level is 1), and the analysis
is univariate, so it cannot see effects that live only in knob interactions. No external
libraries; fully reproducible. Regenerates on demand at <code>/report</code>.</p>
<p class='muted'><a href='/'>← observatory</a> · <a href='/paper'>paper</a> · <a href='/deck'>deck</a></p>
</div></body></html>""")
    return "".join(parts)


def main():
    models = build_models()
    htmlout = render_report(models)
    with open(REPORT_PATH, "w") as f:
        f.write(htmlout)
    print(f"wrote {REPORT_PATH} ({len(htmlout)} bytes, "
          f"{models['n_observations']} observations)")


if __name__ == "__main__":
    main()
