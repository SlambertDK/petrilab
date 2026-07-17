"""
PetriLab v2 — engine
====================
Bottom-up artificial life. Cells carry a variable-length genome, divide with
heredity, communicate via diffusing signal, and compete for energy under
seasons. No goal, no fitness target — only the tension "be complex" vs
"complexity costs".

v2 changes over v1 (why we rebuilt):
  * LINEAGE tracking: every cell carries lineage_id (root ancestor) + parent_id.
    This is what makes MODES-style OEE measurement possible — we can ask which
    *lineages* persist, not just count nodes.
  * Heredity + signaling + open genome ON by default (v1 shipped them OFF, so it
    could never accumulate — it just oscillated with the seasons: the class-2 trap).
  * Tuned so the population sits at hundreds of cells, not 19 — a state space big
    enough for sustained novelty to be possible at all (Occam: a poor system can't
    be rich no matter how you measure it).
  * Gardener drives it (see gardener.py); the engine only exposes ratios to tune.

Everything stochastic with a logged seed → reproducible.
"""
import json
import math
import os
import random
import time
from dataclasses import dataclass, field, asdict


@dataclass
class Cell:
    id: int
    x: float
    y: float
    energy: float
    genome: list          # variable-length list of [w, a, b] gene triples
    lineage_id: int       # root ancestor id — stable label for the whole line
    parent_id: int        # immediate mother (-1 for seed cells)
    emit: float = 0.0
    sensitivity: float = 0.0
    activation: float = 0.0
    age: int = 0
    birth_gen: int = 0


@dataclass
class Edge:
    src: int
    dst: int
    weight: float
    usage: float = 0.0


class Petri:
    """One dish. Runs generation by generation. Gardener tunes the ratios."""

    # ---- parameters the gardener is allowed to tune (level B: ratios only) ----
    TUNABLE = {
        "energy_influx", "edge_cost", "node_upkeep", "grow_threshold",
        "mutation_rate", "prune_threshold", "seasons", "season_len",
        "signaling", "signal_radius", "chemotaxis", "sense_radius",
        "gene_mut_rate", "structural_heredity",
    }

    def __init__(self, seed=None, params=None):
        self.seed = seed if seed is not None else random.randrange(2**31)
        self.rng = random.Random(self.seed)
        p = params or {}

        # --- resource economy ---
        self.energy_influx   = float(p.get("energy_influx", 40.0))   # "light" per gen
        self.edge_cost       = float(p.get("edge_cost", 0.015))
        self.node_upkeep     = float(p.get("node_upkeep", 0.04))
        self.grow_threshold  = float(p.get("grow_threshold", 10.0))
        self.prune_threshold = float(p.get("prune_threshold", 0.05))
        self.max_nodes       = int(p.get("max_nodes", 3500))         # hard safety (memory)

        # --- variation ---
        self.mutation_rate      = float(p.get("mutation_rate", 0.15))   # edge weight drift
        self.gene_mut_rate      = float(p.get("gene_mut_rate", 0.25))   # genome point/length mut
        self.genome_cap         = int(p.get("genome_cap", 120))
        self.structural_heredity= float(p.get("structural_heredity", 0.5))  # edge inheritance prob

        # --- environment ---
        self.seasons      = float(p.get("seasons", 0.5))
        self.season_len   = float(p.get("season_len", 1800))
        self.signaling    = float(p.get("signaling", 1.0))
        self.signal_radius = float(p.get("signal_radius", 0.18))
        self.chemotaxis   = float(p.get("chemotaxis", 1.0))
        self.sense_radius = float(p.get("sense_radius", 0.22))

        # --- state ---
        self.cells: dict[int, Cell] = {}
        self.edges: list[Edge] = []
        self.next_id = 0
        self.generation = 0
        self.last_event = None

        self._seed_world()

    # ---------------------------------------------------------------
    def _seed_world(self, k=24):
        for _ in range(k):
            self._spawn(
                x=self.rng.uniform(0, 1), y=self.rng.uniform(0, 1),
                energy=self.rng.uniform(5, 9), genome=self._new_genome(),
                lineage_id=None, parent_id=-1,
            )

    def _new_genome(self):
        return [[self.rng.gauss(0, 0.5), self.rng.gauss(0, 0.3), self.rng.gauss(0, 0.3)]]

    def _genome_bias(self, genome):
        if not genome:
            return 0.0
        s = sum(g[0] * math.tanh(g[1] + g[2]) for g in genome)
        return math.tanh(s)

    def _mutate_genome(self, genome):
        g = [list(gene) for gene in genome]
        for gene in g:
            for i in range(len(gene)):
                if self.rng.random() < 0.3:
                    gene[i] += self.rng.gauss(0, 0.1)
        if self.rng.random() < self.gene_mut_rate:
            roll = self.rng.random()
            if roll < 0.5 and len(g) < self.genome_cap:       # duplicate
                idx = self.rng.randrange(len(g))
                g.insert(idx, list(g[idx]))
            elif roll < 0.8 and len(g) < self.genome_cap:     # insert fresh
                g.append([self.rng.gauss(0, 0.5), self.rng.gauss(0, 0.3), self.rng.gauss(0, 0.3)])
            elif len(g) > 1:                                   # delete
                del g[self.rng.randrange(len(g))]
        return g

    def _spawn(self, x, y, energy, genome, lineage_id, parent_id,
               emit=None, sens=None):
        cid = self.next_id
        if lineage_id is None:
            lineage_id = cid  # a seed cell founds its own lineage
        c = Cell(
            id=cid,
            x=max(0, min(1, x)), y=max(0, min(1, y)),
            energy=energy, genome=genome,
            lineage_id=lineage_id, parent_id=parent_id,
            emit=emit if emit is not None else self.rng.gauss(0, 0.5),
            sensitivity=sens if sens is not None else self.rng.gauss(0, 0.5),
            birth_gen=self.generation,
        )
        self.cells[cid] = c
        self.next_id += 1
        return c

    # ---------------------------------------------------------------
    def step(self):
        self.generation += 1
        cells = self.cells
        if not cells:
            self._seed_world(8)  # reseed rather than sit dead
            return

        live = list(cells.values())

        # 1) LIGHT with seasons
        influx = self.energy_influx
        if self.seasons > 0:
            phase = math.sin(2 * math.pi * self.generation / max(self.season_len, 1))
            influx = self.energy_influx * (1.0 + self.seasons * phase)
        for _ in range(max(0, int(influx))):
            self.rng.choice(live).energy += 1.0

        # 2) ACTIVATION via edges
        incoming = {cid: 0.0 for cid in cells}
        for e in self.edges:
            src = cells.get(e.src)
            if src is None:
                continue
            sig = math.tanh(src.activation + self._genome_bias(src.genome)) * e.weight
            if e.dst in incoming:
                incoming[e.dst] += sig
                e.usage = 0.9 * e.usage + 0.1 * abs(sig)

        # 2b) SIGNALING molecules (diffuse, local)
        if self.signaling > 0 and len(live) > 1:
            for n in live:
                fieldv = 0.0
                for m in live:
                    if m.id != n.id and abs(m.x - n.x) < self.signal_radius \
                       and abs(m.y - n.y) < self.signal_radius:
                        fieldv += m.emit * m.activation
                incoming[n.id] += self.signaling * n.sensitivity * math.tanh(fieldv)

        for cid, n in cells.items():
            n.activation = math.tanh(incoming[cid] + self._genome_bias(n.genome))
            n.age += 1

        # 3) COST
        edge_count = {cid: 0 for cid in cells}
        for e in self.edges:
            if e.src in edge_count:
                edge_count[e.src] += 1
        for cid, n in cells.items():
            n.energy -= self.node_upkeep + self.edge_cost * edge_count[cid]

        # 4) GROWTH: divide (with heredity) or wire up
        if len(cells) < self.max_nodes:
            for n in list(cells.values()):
                if n.energy > self.grow_threshold and self.rng.random() < 0.5:
                    n.energy /= 2
                    child = self._spawn(
                        x=n.x + self.rng.gauss(0, 0.05),
                        y=n.y + self.rng.gauss(0, 0.05),
                        energy=n.energy,
                        genome=self._mutate_genome(n.genome),   # HEREDITY (default on)
                        lineage_id=n.lineage_id,                # child stays in mother's line
                        parent_id=n.id,
                        emit=n.emit + self.rng.gauss(0, 0.1),
                        sens=n.sensitivity + self.rng.gauss(0, 0.1),
                    )
                    self.edges.append(Edge(n.id, child.id, weight=self.rng.gauss(0, 1)))
                    if self.structural_heredity > 0:            # inherit topology
                        for e in [e for e in self.edges if e.src == n.id and e.dst != child.id]:
                            if self.rng.random() < self.structural_heredity:
                                self.edges.append(Edge(child.id, e.dst,
                                                       weight=e.weight + self.rng.gauss(0, 0.2)))
                elif n.energy > self.grow_threshold * 0.6 and \
                        self.rng.random() < self.mutation_rate and len(cells) > 1:
                    if self.chemotaxis > 0:
                        near = [m for m in cells.values()
                                if m.id != n.id and abs(m.x - n.x) < self.sense_radius
                                and abs(m.y - n.y) < self.sense_radius]
                        other = self.rng.choice(near).id if near else None
                    else:
                        o = self.rng.choice(list(cells.keys()))
                        other = o if o != n.id else None
                    if other is not None:
                        n.energy -= 1.0
                        self.edges.append(Edge(n.id, other, weight=self.rng.gauss(0, 1)))

        # 5) WEIGHT drift
        for e in self.edges:
            if self.rng.random() < self.mutation_rate * 0.3:
                e.weight += self.rng.gauss(0, 0.2)

        # 5b) CHEMOTAXIS: used edges pull cells together → tissue
        if self.chemotaxis > 0 and self.edges:
            pull = {cid: [0.0, 0.0] for cid in cells}
            for e in self.edges:
                a = cells.get(e.src); b = cells.get(e.dst)
                if a is None or b is None:
                    continue
                s = self.chemotaxis * (0.3 + e.usage)
                pull[e.src][0] += (b.x - a.x) * s; pull[e.src][1] += (b.y - a.y) * s
                pull[e.dst][0] += (a.x - b.x) * s; pull[e.dst][1] += (a.y - b.y) * s
            for cid, n in cells.items():
                n.x = min(1.0, max(0.0, n.x + 0.01 * pull[cid][0]))
                n.y = min(1.0, max(0.0, n.y + 0.01 * pull[cid][1]))

        # 6) DEATH + prune
        for cid in [cid for cid, n in cells.items() if n.energy <= 0]:
            del cells[cid]
        self.edges = [e for e in self.edges
                      if e.src in cells and e.dst in cells
                      and (abs(e.weight) > self.prune_threshold or e.usage > 0.01)]

    # ---------------------------------------------------------------
    def lineage_census(self):
        """Population per living lineage — the raw material for MODES metrics."""
        census = {}
        for n in self.cells.values():
            census[n.lineage_id] = census.get(n.lineage_id, 0) + 1
        return census

    def set_param(self, key, value):
        if key in self.TUNABLE and hasattr(self, key):
            setattr(self, key, float(value))
            return True
        return False

    def params_dict(self):
        return {k: getattr(self, k) for k in sorted(self.TUNABLE)}
