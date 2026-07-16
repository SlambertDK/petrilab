"""
Emergence metrics for the petri dish.
Objectively measures what you CANNOT see with the naked eye.
Everything here is pure math — no AI. It is the measuring apparatus
the gardener (and Henrik) reads off.
"""

import math
from collections import deque


class Metrics:
    def __init__(self):
        # Rolling history for phase-transition detection
        self.series = {
            "modularity": deque(maxlen=400),
            "cycles": deque(maxlen=400),
            "depth": deque(maxlen=400),
            "persistence": deque(maxlen=400),
            "complexity": deque(maxlen=400),
            "spatial": deque(maxlen=400),
            "comm": deque(maxlen=400),
        }
        self.node_lifespans = {}   # id -> how many generations it has lived
        self.phase_events = []     # detected jumps
        self._last_phase = {}      # metric -> (gen, direction) for cooldown

    # -----------------------------------------------------------
    def compute(self, sim):
        nodes = sim.nodes
        edges = sim.edges
        n = len(nodes)
        m = len(edges)

        # 1) COMPLEXITY: structure per node (edges/node) weighted by activity
        avg_deg = (m / n) if n else 0.0
        activity = sum(abs(x.activation) for x in nodes.values()) / n if n else 0.0
        complexity = avg_deg * (0.5 + activity)

        # 2) MODULARITY: clusters via simple connection density.
        #    Builds adjacency lists, measures how "clumped" the graph is.
        adj = {nid: set() for nid in nodes}
        for e in edges:
            if e.src in adj and e.dst in adj:
                adj[e.src].add(e.dst)
                adj[e.dst].add(e.src)
        # clustering coefficient (fraction of triangles) = proxy for modularity
        tri = 0
        tot = 0
        for nid, nb in adj.items():
            nb = list(nb)
            k = len(nb)
            if k < 2:
                continue
            tot += k * (k - 1) / 2
            for i in range(len(nb)):
                for j in range(i + 1, len(nb)):
                    if nb[j] in adj[nb[i]]:
                        tri += 1
        modularity = (tri / tot) if tot else 0.0

        # 3) CYCLES: count directed cycles (proxy: edges that close back)
        #    Est. via edges where dst can reach src. Cheap approximation:
        #    number of edges that participate in mutual/tight loops.
        edge_set = {(e.src, e.dst) for e in edges}
        cycles = sum(1 for (a, b) in edge_set if (b, a) in edge_set)

        # 4) DEPTH: longest signal chain (BFS from high-energy nodes, capped)
        depth = self._max_depth(adj, nodes)

        # 5) PERSISTENCE: avg. lifespan of currently living nodes
        for nid in nodes:
            self.node_lifespans[nid] = self.node_lifespans.get(nid, 0) + 1
        dead = [nid for nid in self.node_lifespans if nid not in nodes]
        for nid in dead:
            del self.node_lifespans[nid]
        persistence = (sum(self.node_lifespans.values()) / n) if n else 0.0

        # 6) SPATIAL COHERENCE: are connected cells physically close to
        #    each other? Measures self-organization objectively.
        #    0 = connections go crisscross (random).
        #    High = connected cells clump together = organized "tissue".
        #    Baseline ~0.52 = expected connection length at random placement.
        if m and n > 1:
            tot_len = 0.0
            cnt = 0
            for e in edges:
                a = nodes.get(e.src); b = nodes.get(e.dst)
                if a is None or b is None:
                    continue
                tot_len += ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
                cnt += 1
            avg_len = (tot_len / cnt) if cnt else 0.52
            spatial = max(0.0, 1.0 - avg_len / 0.52)
        else:
            spatial = 0.0

        # 7) COMMUNICATION (PHASE 3): how strongly are the signal genes
        #    expressed in the living population? Measures whether the cells
        #    actually use the wireless signal layer. 0 = no signaling
        #    (genes near zero or OFF).
        if n:
            comm = sum(abs(nd.emit) * abs(nd.sensitivity)
                       for nd in nodes.values()) / n
            comm = round(min(1.0, comm), 3)
        else:
            comm = 0.0

        vals = {
            "modularity": round(modularity, 4),
            "cycles": cycles,
            "depth": depth,
            "persistence": round(persistence, 1),
            "complexity": round(complexity, 3),
            "spatial": round(spatial, 3),
            "comm": comm,
        }

        # Store in time series + check for phase transitions
        for k, v in vals.items():
            self.series[k].append(v)
        events = self._detect_phase(sim.generation, vals)

        return {"metrics": vals, "phase_events": events}

    # -----------------------------------------------------------
    def _max_depth(self, adj, nodes, cap=6):
        """Longest shortest-path chain from the most energy-rich nodes. Capped."""
        if not nodes:
            return 0
        starts = sorted(nodes.values(), key=lambda x: -x.energy)[:3]
        best = 0
        for s in starts:
            seen = {s.id}
            frontier = [s.id]
            d = 0
            while frontier and d < cap:
                nxt = []
                for u in frontier:
                    for v in adj.get(u, ()):
                        if v not in seen:
                            seen.add(v)
                            nxt.append(v)
                if nxt:
                    d += 1
                frontier = nxt
            best = max(best, d)
        return best

    # -----------------------------------------------------------
    def _detect_phase(self, gen, vals):
        """Phase transition = a sustained STEP in a metric, not just noise.
        Compares the newest window against the preceding window."""
        events = []
        W = 40  # window
        for k, v in vals.items():
            s = self.series[k]
            if len(s) < 2 * W:
                continue
            recent = list(s)[-W:]
            older = list(s)[-2 * W:-W]
            mu_r = sum(recent) / W
            mu_o = sum(older) / W
            var_o = sum((x - mu_o) ** 2 for x in older) / W
            sd_o = math.sqrt(var_o) if var_o > 0 else 0.0
            # Step if the shift is large relative to prior noise level
            if sd_o > 0 and abs(mu_r - mu_o) > 3 * sd_o and abs(mu_r - mu_o) > 0.05 * (abs(mu_o) + 1):
                direction = "up" if mu_r > mu_o else "down"
                # Cooldown: same metric+direction is logged only once per 150 gen
                last = self._last_phase.get(k)
                if last and last[1] == direction and gen - last[0] < 150:
                    continue
                self._last_phase[k] = (gen, direction)
                ev = {
                    "gen": gen,
                    "metric": k,
                    "from": round(mu_o, 3),
                    "to": round(mu_r, 3),
                    "direction": direction,
                }
                events.append(ev)
                self.phase_events.append(ev)
                if len(self.phase_events) > 200:
                    self.phase_events = self.phase_events[-200:]
        return events
