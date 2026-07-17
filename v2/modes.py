"""
PetriLab v2 — measurement (MODES + falsification)
=================================================
Purpose-built OEE metrics for an INTERACTING system, following the MODES-toolbox
philosophy (Dolson et al.): measure change / novelty / ecology / complexity over
*persistent lineages*, not raw node counts. This is the deliberate replacement
for v1's broken novelty metric (which used an ever-growing 'seen' set, so novelty
decayed to 0 mechanically after ~500k gens regardless of dynamics).

Key anti-circularity choices (from the red-team):
  * The success OUTCOME (lineage_survival) is decoupled from novelty — it counts
    lineages, never "new patterns", so the falsification panel can't measure its
    own definition.
  * Novelty uses a SLIDING reference window, not an eternal set, so it reflects
    dynamics rather than library size.
"""
import math
import zlib
from collections import deque


class Modes:
    def __init__(self, window=200):
        # sliding references — bounded, so metrics track dynamics not history size
        self.recent_sigs = deque(maxlen=window)     # recent macrostate signatures
        self.seen_window = deque(maxlen=2000)        # bounded 'known' set (list form)
        self._seen_set = set()
        self.prev_census = {}                        # last lineage census (for change)
        self.prev_genome_mean = 0.0
        self.history = deque(maxlen=600)             # per-sample MODES record
        self.novelty_stream = deque(maxlen=400)      # for periodicity test
        self.persistent = {}                         # lineage_id -> gens survived

    # ---- coarse macrostate signature (discretised so jitter isn't "new") ----
    @staticmethod
    def _sig(cell_count, edge_count, lineage_count, avg_genome, avg_deg):
        def b(x, step):
            return int(x / step) if step else 0
        return "|".join(str(v) for v in (
            b(math.log1p(cell_count), 0.5),
            b(math.log1p(edge_count), 0.5),
            b(lineage_count, 2),
            b(avg_genome, 0.5),
            b(avg_deg, 1.0),
        ))

    def update(self, sim):
        cells = sim.cells
        n = len(cells)
        m = len(sim.edges)
        census = sim.lineage_census()
        L = len(census)
        gsizes = [len(c.genome) for c in cells.values()] or [0]
        avg_genome = sum(gsizes) / len(gsizes)
        avg_deg = (m / n) if n else 0.0

        # --- track lineage persistence (the decoupled survival outcome) ---
        for lid in census:
            self.persistent[lid] = self.persistent.get(lid, 0) + 1
        for lid in list(self.persistent):
            if lid not in census:
                del self.persistent[lid]

        # === MODES axes ===
        # NOVELTY: fraction of recent window that is unseen vs a SLIDING window
        sig = self._sig(n, m, L, avg_genome, avg_deg)
        is_new = sig not in self._seen_set
        if is_new:
            self._seen_set.add(sig)
            self.seen_window.append(sig)
            if len(self.seen_window) == self.seen_window.maxlen:
                old = self.seen_window[0]
                # let the set forget the oldest so novelty tracks dynamics
                if old not in list(self.seen_window)[1:]:
                    self._seen_set.discard(old)
        self.recent_sigs.append(1 if is_new else 0)
        novelty = sum(self.recent_sigs) / len(self.recent_sigs) if self.recent_sigs else 0.0

        # CHANGE: turnover of lineage composition since last sample (L1 on shares)
        change = self._composition_change(census)
        self.prev_census = dict(census)

        # ECOLOGY: Shannon evenness of the lineage distribution (diversity of niches)
        ecology = self._evenness(census)

        # COMPLEXITY: mean genome length (structural depth) blended with connectivity
        complexity = avg_genome * (0.5 + min(avg_deg, 10) / 10)

        rec = {
            "gen": sim.generation,
            "change": round(change, 4),
            "novelty": round(novelty, 4),
            "ecology": round(ecology, 4),
            "complexity": round(complexity, 4),
        }
        self.history.append(rec)
        self.novelty_stream.append(novelty)
        return rec, census

    @staticmethod
    def _evenness(census):
        tot = sum(census.values())
        if tot <= 0 or len(census) <= 1:
            return 0.0
        H = 0.0
        for c in census.values():
            pr = c / tot
            if pr > 0:
                H -= pr * math.log(pr)
        return H / math.log(len(census))   # 0..1 (1 = perfectly even)

    def _composition_change(self, census):
        tot = sum(census.values()) or 1
        prev_tot = sum(self.prev_census.values()) or 1
        keys = set(census) | set(self.prev_census)
        d = 0.0
        for k in keys:
            d += abs(census.get(k, 0) / tot - self.prev_census.get(k, 0) / prev_tot)
        return d / 2  # normalised 0..1

    # === Falsification contract (decoupled from novelty definition) ===
    def falsification(self, sim):
        census = sim.lineage_census()
        # 1) lineage_survival: are multiple lineages persisting (not collapsed to 1)?
        long_lived = sum(1 for g in self.persistent.values() if g >= 20)
        lineage_survival = long_lived >= 3
        # 2) novelty_alive: is novelty meaningfully > 0 (still minting new states)?
        recent_nov = list(self.novelty_stream)[-100:]
        novelty_alive = (sum(recent_nov) / len(recent_nov) if recent_nov else 0) > 0.05
        # 3) not_periodic: novelty stream is NOT a clean oscillation (class-2 trap)
        not_periodic = not self._looks_periodic(list(self.novelty_stream))
        if lineage_survival and novelty_alive and not_periodic:
            verdict = "success"
        elif not novelty_alive or not lineage_survival:
            verdict = "failure"
        else:
            verdict = "unresolved"
        return {
            "lineage_survival": lineage_survival,
            "novelty_alive": novelty_alive,
            "not_periodic": not_periodic,
            "verdict": verdict,
            "long_lived_lineages": long_lived,
        }

    @staticmethod
    def _looks_periodic(stream, min_len=120):
        """Cheap periodicity test: strong autocorrelation at some lag = oscillation."""
        if len(stream) < min_len:
            return False
        s = stream[-min_len:]
        mean = sum(s) / len(s)
        var = sum((x - mean) ** 2 for x in s) / len(s)
        if var < 1e-9:
            return True  # flat = trivially periodic/dead
        best = 0.0
        for lag in range(5, min_len // 2):
            cov = sum((s[i] - mean) * (s[i - lag] - mean) for i in range(lag, len(s)))
            ac = cov / (len(s) - lag) / var
            best = max(best, ac)
        return best > 0.7  # high autocorrelation → periodic
