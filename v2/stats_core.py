#!/usr/bin/env python3
"""
stats_core.py — hardened statistical primitives for PetriLab's data-science layer.

Pure Python (stdlib `math` only, no numpy/scipy) so it runs anywhere the server
runs. Every function is deliberately small, documented, and traceable to a named
method in the methodology guide (petrilab_statistical_methodology.md). The point
of this module is to replace the naive t-test / OLS-on-peaks with methods that are
honest about the two things that break inference here:

  (1) the observations are an autocorrelated time-series from ONE running sim, and
  (2) we run many tests at once (multiple comparisons).

Methods implemented:
  pearson / spearman            — linear + rank correlation (triangulation)
  lag1_autocorr / n_eff         — AR(1) effective sample size (Bartlett/Bayley 1946)
  corr_ttest_neff               — correlation t-test using n_eff, not n
  benjamini_hochberg            — FDR control across the whole test family
  sign_test / wilcoxon_signed   — paired intervention-delta tests (causal, nonparametric)
  cohens_dz                     — standardized effect size for the deltas
  mann_kendall / sens_slope     — robust monotone-trend detection (replaces peak-OLS)
  norm_cdf                      — standard normal CDF via math.erf (stdlib, not scipy)
"""
import math


# ----------------------------------------------------------------------
# normal CDF (stdlib erf — explicitly NOT scipy)
def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _two_sided_p(z):
    return 2.0 * (1.0 - norm_cdf(abs(z)))


# ----------------------------------------------------------------------
# correlations
def pearson(xs, ys):
    """Pearson r over paired finite values. Returns (r, n)."""
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


def _rankdata(vals):
    """Average ranks (1-based), ties share the mean rank."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # mean of ranks i+1..j+1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation = Pearson on ranks. Returns (rho, n).

    Triangulation partner for Pearson: catches monotone-but-nonlinear links and
    is robust to outliers. If Pearson and Spearman disagree, the relationship is
    nonlinear or outlier-driven and should not be reported as a clean linear one.
    """
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None, n
    rx = _rankdata([p[0] for p in pairs])
    ry = _rankdata([p[1] for p in pairs])
    return pearson(rx, ry)[0], n


# ----------------------------------------------------------------------
# autocorrelation / effective sample size  (methodology §1.2)
def lag1_autocorr(xs):
    """Lag-1 autocorrelation rho of a series (finite values, in order)."""
    v = [x for x in xs if isinstance(x, (int, float))]
    n = len(v)
    if n < 4:
        return 0.0
    m = sum(v) / n
    denom = sum((x - m) ** 2 for x in v)
    if denom < 1e-12:
        return 0.0
    num = sum((v[t] - m) * (v[t + 1] - m) for t in range(n - 1))
    return num / denom


def n_eff(n, rho):
    """AR(1) effective sample size: n*(1-rho)/(1+rho), clamped to [2, n].

    Negative lag-1 autocorrelation only helps independence, so we floor rho at 0
    to avoid inflating n_eff above n (methodology §1.2).
    """
    rho = max(0.0, min(0.999, rho))
    ne = n * (1.0 - rho) / (1.0 + rho)
    return max(2.0, min(float(n), ne))


def corr_ttest_neff(r, n, rho):
    """Correlation t-test corrected for autocorrelation via n_eff.

    Standard test is t = r*sqrt((n-2)/(1-r^2)) with df = n-2. We substitute the
    effective sample size so serial dependence cannot manufacture significance.
    Returns (t, df_eff, p_two_sided, neff).
    """
    if r is None or n < 4 or abs(r) >= 1.0:
        return None, None, None, None
    ne = n_eff(n, rho)
    if ne < 4:
        return None, ne, None, ne
    t = r * math.sqrt((ne - 2.0) / (1.0 - r * r))
    # normal approximation to the t-distribution p-value (df_eff is usually large)
    p = _two_sided_p(t)
    return t, ne - 2.0, p, ne


# ----------------------------------------------------------------------
# multiple comparisons  (methodology §2.2)
def benjamini_hochberg(pvals, alpha=0.10):
    """Benjamini-Hochberg FDR. Input: list of (key, p) with p possibly None.
    Returns dict key -> {'p', 'p_adj', 'reject'} controlling FDR at alpha.

    Finds the largest rank k with p_(k) <= (k/m)*alpha, rejects the k smallest.
    Adjusted p-values are the monotone step-up transform.
    """
    valid = [(k, p) for k, p in pvals if isinstance(p, (int, float))]
    m = len(valid)
    out = {k: {"p": p, "p_adj": None, "reject": False} for k, p in pvals}
    if m == 0:
        return out
    valid.sort(key=lambda kp: kp[1])
    # step-up adjusted p-values
    adj = [0.0] * m
    prev = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        val = min(prev, valid[i][1] * m / rank)
        adj[i] = val
        prev = val
    # largest k with p_(k) <= (k/m)*alpha
    kmax = 0
    for i in range(m):
        if valid[i][1] <= (i + 1) / m * alpha:
            kmax = i + 1
    for i, (k, p) in enumerate(valid):
        out[k] = {"p": p, "p_adj": adj[i], "reject": (i < kmax)}
    return out


# ----------------------------------------------------------------------
# paired intervention-delta tests  (methodology §3 — the causal ones)
def sign_test(deltas):
    """Exact two-sided sign test on paired deltas (H0: median = 0).
    Returns dict n_pos, n_neg, p. Assumption-free directional test.
    """
    pos = sum(1 for d in deltas if d > 0)
    neg = sum(1 for d in deltas if d < 0)
    N = pos + neg
    if N == 0:
        return {"n_pos": 0, "n_neg": 0, "p": None}
    # exact binomial tail at p=0.5
    def binom_cdf(k, N):
        return sum(math.comb(N, i) for i in range(0, k + 1)) / (2.0 ** N)
    lo = min(pos, neg)
    p = min(1.0, 2.0 * binom_cdf(lo, N))
    return {"n_pos": pos, "n_neg": neg, "p": p}


def wilcoxon_signed(deltas):
    """Wilcoxon signed-rank test on paired deltas (H0: symmetric about 0).
    Normal approximation with tie + continuity correction (methodology §3.3).
    Uses direction AND magnitude, so more powerful than the sign test.
    Returns dict W_plus, z, p, n.
    """
    d = [x for x in deltas if isinstance(x, (int, float)) and x != 0]
    N = len(d)
    if N < 6:
        return {"W_plus": None, "z": None, "p": None, "n": N}
    ranks = _rankdata([abs(x) for x in d])
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    mu = N * (N + 1) / 4.0
    # tie correction: subtract sum(t^3 - t)/48 over groups of tied |d|
    absd = [abs(x) for x in d]
    counts = {}
    for a in absd:
        counts[a] = counts.get(a, 0) + 1
    tie = sum(c ** 3 - c for c in counts.values() if c > 1)
    var = N * (N + 1) * (2 * N + 1) / 24.0 - tie / 48.0
    if var <= 0:
        return {"W_plus": w_plus, "z": None, "p": None, "n": N}
    # continuity correction toward the mean
    cc = 0.5 if w_plus < mu else -0.5
    z = (w_plus - mu + cc) / math.sqrt(var)
    return {"W_plus": w_plus, "z": z, "p": _two_sided_p(z), "n": N}


def cohens_dz(deltas):
    """Standardized effect size for paired deltas: mean/sd (methodology §5.1)."""
    d = [x for x in deltas if isinstance(x, (int, float))]
    n = len(d)
    if n < 3:
        return None
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    sd = math.sqrt(var)
    if sd < 1e-12:
        return None
    return m / sd


# ----------------------------------------------------------------------
# robust trend detection  (methodology §6 — replaces peak-envelope OLS)
def mann_kendall(xs):
    """Mann-Kendall monotone-trend test with tie-corrected variance and
    continuity correction. Nonparametric: only uses signs of pairwise diffs,
    so robust to non-normality and outliers. Returns dict S, z, p, trend, n.

    NOTE: vanilla MK assumes serial independence; positive autocorrelation
    inflates its false-positive rate. We report an autocorrelation-deflated
    z as well (Hamed-Rao-style n_eff scaling) so the caller can be conservative.
    """
    v = [x for x in xs if isinstance(x, (int, float))]
    n = len(v)
    if n < 8:
        return {"S": None, "z": None, "p": None, "trend": "insufficient", "n": n}
    S = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            S += (v[j] > v[i]) - (v[j] < v[i])
    # tie-corrected variance
    counts = {}
    for x in v:
        counts[x] = counts.get(x, 0) + 1
    tie = sum(t * (t - 1) * (2 * t + 5) for t in counts.values() if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var <= 0:
        return {"S": S, "z": None, "p": None, "trend": "degenerate", "n": n}
    if S > 0:
        z = (S - 1) / math.sqrt(var)
    elif S < 0:
        z = (S + 1) / math.sqrt(var)
    else:
        z = 0.0
    # autocorrelation-deflated z (conservative): scale variance by n/n_eff
    rho = lag1_autocorr(v)
    ne = n_eff(n, rho)
    z_ac = z * math.sqrt(ne / n) if n > 0 else z
    p_ac = _two_sided_p(z_ac)
    trend = ("rising" if z_ac > 1.96 else "falling" if z_ac < -1.96
             else "no-trend")
    return {"S": S, "z": round(z, 3), "z_ac": round(z_ac, 3),
            "p": round(_two_sided_p(z), 5), "p_ac": round(p_ac, 5),
            "rho": round(rho, 3), "trend": trend, "n": n}


def sens_slope(xs):
    """Sen's slope: median of all pairwise slopes (x_j - x_i)/(j - i).
    Robust, outlier-resistant trend magnitude (methodology §6.1).
    """
    v = [x for x in xs if isinstance(x, (int, float))]
    n = len(v)
    if n < 4:
        return None
    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            slopes.append((v[j] - v[i]) / (j - i))
    slopes.sort()
    m = len(slopes)
    if m == 0:
        return None
    if m % 2 == 1:
        return slopes[m // 2]
    return 0.5 * (slopes[m // 2 - 1] + slopes[m // 2])
