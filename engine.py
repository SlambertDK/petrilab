"""
Petri dish — stochastic growth-and-death network.
------------------------------------------------
Henrik's idea: build complexity from the bottom up. Reward the system for growing
(new nodes + connections), but let each connection COST energy. The
unsustainable gets pruned away. No goals are defined. Only the tension
between "be complex" and "complexity costs".

No external world yet (v0) — pure resource competition.
Energy drips in ("light"), nodes compete for it, mutate, divide,
and die if they run out. Everything is stochastic with a logged seed.
"""

import json
import math
import os
import random
import time
from dataclasses import dataclass, field, asdict

from metrics import Metrics


# --- Logbook: append-only chain of evidence for the article ---
LOGBOOK_PATH = os.path.join(os.path.dirname(__file__), "data", "logbog.md")
# --- Phase log: raw phase transitions (noise), kept separate from the chain of evidence ---
PHASELOG_PATH = os.path.join(os.path.dirname(__file__), "data", "phase_log.md")


def _logbook(msg, actor="system"):
    """Write one dated line to the logbook. Append, never overwrite."""
    os.makedirs(os.path.dirname(LOGBOOK_PATH), exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGBOOK_PATH, "a") as f:
        f.write(f"- **{ts}** [{actor}] {msg}\n")


def _phaselog(msg):
    """Raw phase transitions → separate file, so the main logbook stays clean."""
    os.makedirs(os.path.dirname(PHASELOG_PATH), exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(PHASELOG_PATH, "a") as f:
        f.write(f"- **{ts}** {msg}\n")


@dataclass
class Node:
    id: int
    x: float          # position (for visualization only)
    y: float
    energy: float
    bias: float       # the node's intrinsic "propensity" to fire
    activation: float = 0.0
    age: int = 0
    # PHASE 3: signal genes. Evolution discovers their use on its own.
    emit: float = 0.0        # how much signaling molecule the cell secretes (scaled by activation)
    sensitivity: float = 0.0  # how strongly the cell responds to surrounding signal
    # PHASE 4 (open_genotype): an OPTIONAL variable-length genome. When the
    # open_genotype flag is OFF this stays None and the cell behaves exactly as
    # before (fixed 3-scalar genotype = the control). When ON, the genome is a
    # list of "genes" (each a small float triple) whose LENGTH can grow via gene
    # duplication at division — removing the a-priori complexity ceiling. The
    # cell's effective bias is derived from the genome so a longer genome can
    # encode strictly more structure than a shorter one.
    genome: list = None


@dataclass
class Edge:
    src: int
    dst: int
    weight: float
    usage: float = 0.0   # rolling measure of how much the connection is used


class Petri:
    """One petri dish. Runs generation by generation."""

    def __init__(self, seed=None, params=None):
        # --- Seed: stochastic, but logged so a run can be reproduced ---
        self.seed = seed if seed is not None else random.randrange(2**31)
        self.rng = random.Random(self.seed)

        # --- Parameters (can be adjusted live from the dashboard) ---
        p = params or {}
        self.energy_influx   = p.get("energy_influx", 8.0)    # "light" per gen
        self.edge_cost       = p.get("edge_cost", 0.02)       # cost per connection
        self.node_upkeep     = p.get("node_upkeep", 0.05)     # basal cost per node
        self.grow_threshold  = p.get("grow_threshold", 12.0)  # energy needed to divide
        self.mutation_rate   = p.get("mutation_rate", 0.15)
        self.prune_threshold = p.get("prune_threshold", 0.05) # weak edges die
        self.max_nodes       = p.get("max_nodes", 4000)       # hard safety limit

        # --- Environment mechanisms (feature flags, default OFF = unchanged behavior) ---
        # So the research engine can use "flag=0" as a pure control.
        self.seasons      = float(p.get("seasons", 0.0))       # amplitude 0-1 on cyclic light
        self.season_len   = float(p.get("season_len", 2000))   # generations per season cycle
        self.endogenous   = float(p.get("endogenous", 0.0))    # 0=random light, 1=light follows activity
        self.catastrophe  = float(p.get("catastrophe", 0.0))   # probability/gen of a shock (e.g. 0.0005)
        self.catastrophe_kill = float(p.get("catastrophe_kill", 0.4))  # fraction killed by a shock
        # PHASE 1: receptors + chemotaxis. 0=OFF (control), >0=strength.
        # ON: connections form toward NEARBY cells (receptor sensing),
        # and connected cells pull toward each other in space (chemotaxis).
        self.chemotaxis   = float(p.get("chemotaxis", 0.0))    # movement strength toward neighbors
        self.sense_radius = float(p.get("sense_radius", 0.25))  # receptor range
        # PHASE 2: cell division with heredity. 0=OFF (control: random bias).
        # ON: daughter cells inherit the mother's bias + small mutation → real
        # selection WITH memory (good patterns are inherited instead of lost).
        self.heredity     = float(p.get("heredity", 0.0))      # 0=no heredity, >0=heredity strength
        # PHASE 2 v2: structural heredity. 0=OFF. ON: on division the daughter copies
        # some of the mother's connections (with mutation) → real heredity of PATTERN,
        # not just a scalar. Information lives in the topology, so it is "thick" enough
        # hereditary material to carry selection.
        self.heredity_struct = float(p.get("heredity_struct", 0.0))  # prob. per edge of being inherited
        # PHASE 3: signaling molecules. 0=OFF. ON: cells secrete signal into the space
        # and cells with a receptor (sensitivity) nearby are affected — a
        # wireless communication layer on top of the connections. What the signal
        # is used for is NOT predetermined; evolution discovers the use on its own.
        self.signaling    = float(p.get("signaling", 0.0))     # strength of the signal coupling
        self.signal_radius = float(p.get("signal_radius", 0.2))  # how far the signal reaches
        # PHASE 4: open genotype. 0=OFF (control: fixed 3-scalar cell = complexity
        # ceiling). >0=ON: cells carry a variable-length genome that can GROW via
        # gene duplication at division, removing the a-priori ceiling. The value
        # is the per-division probability of a length-changing mutation
        # (duplicate / insert / delete a gene). This is the one mechanism that
        # attacks the ceiling itself rather than unfolding more of a closed space.
        self.open_genotype = float(p.get("open_genotype", 0.0))
        self.genome_cap    = int(p.get("genome_cap", 200))  # hard safety limit on genome length
        self.last_event = None  # for dashboard/log

        # --- State ---
        self.nodes: dict[int, Node] = {}
        self.edges: list[Edge] = []
        self.next_id = 0
        self.generation = 0
        self.history = []  # time series for graphs
        self.metrics = Metrics()
        self.last_metrics = {"metrics": {}, "phase_events": []}

        self._seed_world()

    # ---------------------------------------------------------------
    def _seed_world(self):
        """Start: a handful of random cells. Knows nothing in advance."""
        for _ in range(6):
            self._spawn_node(
                x=self.rng.uniform(0, 1),
                y=self.rng.uniform(0, 1),
                energy=self.rng.uniform(4, 8),
            )

    def _new_genome(self):
        """A fresh minimal genome: one gene = a (weight, offset, scale) triple."""
        return [[self.rng.gauss(0, 0.5), self.rng.gauss(0, 0.3), self.rng.gauss(0, 0.3)]]

    def _genome_bias(self, genome):
        """Derive the cell's effective bias from its genome. A longer genome can
        encode strictly more structure: bias is a bounded sum of per-gene
        contributions, so added genes add expressive capacity."""
        if not genome:
            return 0.0
        s = sum(g[0] * math.tanh(g[1] + g[2]) for g in genome)
        return math.tanh(s)  # bounded, but the internal structure is unbounded

    def _mutate_genome(self, genome):
        """Copy a genome with mutation. With open_genotype ON this can CHANGE
        LENGTH — duplicate a gene (the historical engine of biological complexity
        growth), insert a fresh gene, or delete one. Point-mutates values too."""
        g = [list(gene) for gene in genome]  # deep copy
        # point mutation on every gene value
        for gene in g:
            for i in range(len(gene)):
                if self.rng.random() < 0.3:
                    gene[i] += self.rng.gauss(0, 0.1)
        # length-changing mutation, gated by open_genotype probability
        if self.rng.random() < self.open_genotype:
            roll = self.rng.random()
            if roll < 0.5 and len(g) < self.genome_cap:      # DUPLICATE a gene
                idx = self.rng.randrange(len(g))
                g.insert(idx, list(g[idx]))
            elif roll < 0.8 and len(g) < self.genome_cap:    # INSERT a fresh gene
                g.append([self.rng.gauss(0, 0.5), self.rng.gauss(0, 0.3), self.rng.gauss(0, 0.3)])
            elif len(g) > 1:                                  # DELETE a gene
                del g[self.rng.randrange(len(g))]
        return g

    def _spawn_node(self, x, y, energy, parent_bias=None, parent=None):
        # PHASE 4: open genotype path. When ON, the daughter inherits a mutated,
        # possibly-longer genome and derives its bias from it. This removes the
        # fixed-scalar complexity ceiling.
        genome = None
        if self.open_genotype > 0:
            if parent is not None and parent.genome:
                genome = self._mutate_genome(parent.genome)
            else:
                genome = self._new_genome()
            bias = self._genome_bias(genome)
        # PHASE 2: if heredity is ON and there is a mother, inherit bias + small mutation.
        elif parent_bias is not None and self.heredity > 0:
            bias = parent_bias + self.rng.gauss(0, 0.1)
        else:
            bias = self.rng.gauss(0, 0.5)
        # PHASE 3: signal genes. Inherited from mother (with mutation) if structural
        # heredity is ON, otherwise random start. Only active when signaling is on.
        if parent is not None and self.heredity_struct > 0:
            emit = parent.emit + self.rng.gauss(0, 0.1)
            sens = parent.sensitivity + self.rng.gauss(0, 0.1)
        else:
            emit = self.rng.gauss(0, 0.5)
            sens = self.rng.gauss(0, 0.5)
        n = Node(
            id=self.next_id,
            x=max(0, min(1, x)),
            y=max(0, min(1, y)),
            energy=energy,
            bias=bias,
            emit=emit,
            sensitivity=sens,
            genome=genome,
        )
        self.nodes[n.id] = n
        self.next_id += 1
        return n

    # ---------------------------------------------------------------
    def step(self):
        """One generation. Order: light → activation → growth → death."""
        self.generation += 1
        nodes = self.nodes

        # 1) LIGHT: energy drips in. Can be modulated by seasons (cyclic)
        #    and distributed either randomly (default) or by activity
        #    (endogenous selection: cells in active circuits are rewarded → they become
        #     each other's selection pressure, a moving target rather than a fixed one).
        if nodes:
            live = list(nodes.values())

            # Season modulation: light oscillates between (1-amp) and (1+amp)
            influx = self.energy_influx
            if self.seasons > 0:
                phase = math.sin(2 * math.pi * self.generation / max(self.season_len, 1))
                influx = self.energy_influx * (1.0 + self.seasons * phase)
            drops = max(0, int(influx))

            if self.endogenous > 0:
                # Weighted draw: probability blended between uniform and
                # activity. endogenous=1 => purely activity-driven.
                acts = [abs(n.activation) + 0.05 for n in live]
                tot = sum(acts)
                weights = [
                    (1 - self.endogenous) / len(live) + self.endogenous * (a / tot)
                    for a in acts
                ]
                for _ in range(drops):
                    self.rng.choices(live, weights=weights, k=1)[0].energy += 1.0
            else:
                for _ in range(drops):
                    self.rng.choice(live).energy += 1.0

        # 1b) CATASTROPHE: a rare shock removes a fraction of the cells
        if self.catastrophe > 0 and nodes and self.rng.random() < self.catastrophe:
            k = int(len(nodes) * self.catastrophe_kill)
            if k > 0:
                victims = self.rng.sample(list(nodes), k=k)
                for vid in victims:
                    nodes.pop(vid, None)
                self.last_event = {"gen": self.generation, "type": "catastrophe",
                                   "killed": k}
                _logbook(f"CATASTROPHE gen {self.generation}: {k} cells wiped out "
                         f"({int(self.catastrophe_kill*100)}%)", actor="environment")

        # 2) ACTIVATION: nodes influence each other via connections
        incoming = {nid: 0.0 for nid in nodes}
        for e in self.edges:
            src = nodes.get(e.src)
            if src is None:
                continue
            signal = math.tanh(src.activation + src.bias) * e.weight
            if e.dst in incoming:
                incoming[e.dst] += signal
                e.usage = 0.9 * e.usage + 0.1 * abs(signal)

        # 2b) SIGNALING MOLECULES (PHASE 3): wireless communication layer.
        # Each cell secretes signal (emit × activation) into its local area;
        # cells with a receptor (sensitivity) within signal_radius are affected.
        # No wire needed — it is chemical communication through the "fluid".
        if self.signaling > 0 and len(nodes) > 1:
            live = list(nodes.values())
            for n in live:
                field = 0.0
                for m in live:
                    if m.id == n.id:
                        continue
                    if abs(m.x - n.x) < self.signal_radius and \
                       abs(m.y - n.y) < self.signal_radius:
                        field += m.emit * m.activation
                incoming[n.id] += self.signaling * n.sensitivity * math.tanh(field)

        for nid, n in nodes.items():
            n.activation = math.tanh(incoming[nid] + n.bias)
            n.age += 1

        # 3) COST: each node pays upkeep + a share of the edge cost
        edge_count = {nid: 0 for nid in nodes}
        for e in self.edges:
            if e.src in edge_count:
                edge_count[e.src] += 1
        for nid, n in nodes.items():
            n.energy -= self.node_upkeep + self.edge_cost * edge_count[nid]

        # 4) GROWTH: energy-rich nodes divide or form connections
        if len(nodes) < self.max_nodes:
            for n in list(nodes.values()):
                if n.energy > self.grow_threshold and self.rng.random() < 0.5:
                    n.energy /= 2
                    child = self._spawn_node(
                        x=n.x + self.rng.gauss(0, 0.05),
                        y=n.y + self.rng.gauss(0, 0.05),
                        energy=n.energy,
                        parent_bias=n.bias,   # PHASE 2: daughter inherits mother's bias
                        parent=n,             # PHASE 3: inheritance of signal genes
                    )
                    # new connection mother→child
                    self.edges.append(Edge(n.id, child.id,
                                           weight=self.rng.gauss(0, 1)))
                    # PHASE 2 v2: daughter inherits the mother's connection pattern.
                    # Copy some of the mother's outgoing connections to the daughter
                    # (with weight mutation) → structural heredity of topology.
                    if self.heredity_struct > 0:
                        mother_edges = [e for e in self.edges
                                        if e.src == n.id and e.dst != child.id]
                        for e in mother_edges:
                            if self.rng.random() < self.heredity_struct:
                                self.edges.append(Edge(
                                    child.id, e.dst,
                                    weight=e.weight + self.rng.gauss(0, 0.2)))
                elif n.energy > self.grow_threshold * 0.6 and \
                        self.rng.random() < self.mutation_rate and len(nodes) > 1:
                    # form a connection — toward a NEARBY cell if receptors are ON, otherwise random
                    if self.chemotaxis > 0:
                        # receptor: pick a cell within sense radius (senses neighbors)
                        near = [m for m in nodes.values()
                                if m.id != n.id
                                and abs(m.x - n.x) < self.sense_radius
                                and abs(m.y - n.y) < self.sense_radius]
                        other = self.rng.choice(near).id if near else None
                    else:
                        o = self.rng.choice(list(nodes.keys()))
                        other = o if o != n.id else None
                    if other is not None:
                        n.energy -= 1.0
                        self.edges.append(Edge(n.id, other,
                                               weight=self.rng.gauss(0, 1)))

        # 5) MUTATION: weights drift randomly
        for e in self.edges:
            if self.rng.random() < self.mutation_rate * 0.3:
                e.weight += self.rng.gauss(0, 0.2)

        # 5b) CHEMOTAXIS (PHASE 1): connected cells pull toward each other in space.
        # Active connections pull harder → active circuits physically clump together.
        # Result: self-organization — cells form tissue rather than random spread.
        if self.chemotaxis > 0 and self.edges:
            pull = {nid: [0.0, 0.0] for nid in nodes}
            for e in self.edges:
                a = nodes.get(e.src); b = nodes.get(e.dst)
                if a is None or b is None:
                    continue
                # pull strength grows with how much the connection is used
                s = self.chemotaxis * (0.3 + e.usage)
                pull[e.src][0] += (b.x - a.x) * s
                pull[e.src][1] += (b.y - a.y) * s
                pull[e.dst][0] += (a.x - b.x) * s
                pull[e.dst][1] += (a.y - b.y) * s
            for nid, n in nodes.items():
                # small step toward neighbors, kept within the dish [0,1]
                n.x = min(1.0, max(0.0, n.x + 0.01 * pull[nid][0]))
                n.y = min(1.0, max(0.0, n.y + 0.01 * pull[nid][1]))

        # 6) DEATH: empty nodes die, weak/unused connections are pruned
        dead = [nid for nid, n in nodes.items() if n.energy <= 0]
        for nid in dead:
            del nodes[nid]
        self.edges = [
            e for e in self.edges
            if e.src in nodes and e.dst in nodes
            and (abs(e.weight) > self.prune_threshold or e.usage > 0.01)
        ]

        # 7) LOG time series
        total_e = sum(n.energy for n in nodes.values())
        _m = self.last_metrics.get("metrics", {})
        self.history.append({
            "gen": self.generation,
            "nodes": len(nodes),
            "edges": len(self.edges),
            "energy": round(total_e, 1),
            "cplx": round(_m.get("complexity", 0), 2),
            "pers": round(_m.get("persistence", 0), 2),
            "phases": len(self.metrics.phase_events),
        })
        if len(self.history) > 2000:
            self.history = self.history[-2000:]

        # 8) MEASURE emergence (expensive — only every 10th gen)
        if self.generation % 10 == 0 and nodes:
            result = self.metrics.compute(self)
            self.last_metrics = result
            # Log phase transitions to the separate phase log (not the chain of evidence)
            for ev in result["phase_events"]:
                _phaselog(
                    f"PHASE TRANSITION gen {ev['gen']}: {ev['metric']} "
                    f"{ev['direction']} {ev['from']} → {ev['to']}"
                )

    # ---------------------------------------------------------------
    def snapshot(self):
        """Lightweight snapshot for the dashboard."""
        return {
            "seed": self.seed,
            "generation": self.generation,
            "params": {
                "energy_influx": self.energy_influx,
                "edge_cost": self.edge_cost,
                "node_upkeep": self.node_upkeep,
                "grow_threshold": self.grow_threshold,
                "mutation_rate": self.mutation_rate,
                "prune_threshold": self.prune_threshold,
                "seasons": self.seasons,
                "season_len": self.season_len,
                "endogenous": self.endogenous,
                "catastrophe": self.catastrophe,
                "chemotaxis": self.chemotaxis,
                "heredity": self.heredity,
                "heredity_struct": self.heredity_struct,
                "signaling": self.signaling,
            },
            "season_phase": (
                math.sin(2 * math.pi * self.generation / max(self.season_len, 1))
                if self.seasons > 0 else None
            ),
            "nodes": [
                {"id": n.id, "x": round(n.x, 3), "y": round(n.y, 3),
                 "e": round(n.energy, 1), "a": round(n.activation, 2)}
                for n in self.nodes.values()
            ],
            "edges": [
                {"s": e.src, "d": e.dst, "w": round(e.weight, 2)}
                for e in self.edges
            ],
            "history": self.history[-300:],
            "emergence": self.last_metrics.get("metrics", {}),
            "phase_events": self.metrics.phase_events[-20:],
        }

    def set_param(self, key, value):
        if hasattr(self, key):
            setattr(self, key, float(value))
            return True
        return False

    def save(self, path):
        state = {
            "seed": self.seed,
            "generation": self.generation,
            "next_id": self.next_id,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "history": self.history[-2000:],
            "params": {
                "energy_influx": self.energy_influx, "edge_cost": self.edge_cost,
                "node_upkeep": self.node_upkeep, "grow_threshold": self.grow_threshold,
                "mutation_rate": self.mutation_rate, "prune_threshold": self.prune_threshold,
                "seasons": self.seasons, "season_len": self.season_len,
                "endogenous": self.endogenous, "catastrophe": self.catastrophe,
                "catastrophe_kill": self.catastrophe_kill,
                "chemotaxis": self.chemotaxis, "sense_radius": self.sense_radius,
                "heredity": self.heredity,
                "heredity_struct": self.heredity_struct,
                "signaling": self.signaling,
            },
        }
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, path)

    def load(self, path):
        with open(path) as f:
            state = json.load(f)
        self.seed = state["seed"]
        self.generation = state["generation"]
        self.next_id = state["next_id"]
        self.nodes = {n["id"]: Node(**n) for n in state["nodes"]}
        self.edges = [Edge(**e) for e in state["edges"]]
        self.history = state.get("history", [])
        # Reload saved parameters (so seasons etc. survive a restart)
        for k, v in state.get("params", {}).items():
            if hasattr(self, k):
                setattr(self, k, v)
