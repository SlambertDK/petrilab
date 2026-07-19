# PetriLab: Steering an Open Genome Toward the Edge of Chaos

### An open-ended-evolution engine with an autonomous experimenter and a falsification-first measurement contract

**Henrik Lambert**
*Independent researcher · PetriLab project*
Preprint — 2026-07-19

---

## Abstract

Open-ended evolution (OEE) — the capacity of a system to keep generating novelty, complexity, and new *kinds* of entities indefinitely — remains largely unrealised in artificial systems, most of which converge on a fixed point or oscillate forever within a bounded repertoire [10]. We present **PetriLab**, an artificial-life engine built around three commitments. First, an **open genome**: cells carry variable-length gene lists and reproduce with heritable structure and mutation, so the substrate is not length-bounded a priori. Second, a **level-B autonomous experimenter** (the "Gardener") that steers only *ratios* — energy influx, mutation, seasons, signalling — and never the rules or the genotype-to-phenotype map, so that every accepted finding is an A/B result against a frozen-rules control. Third, a **falsification-first measurement suite** in the spirit of the MODES toolbox [1] and evolutionary-activity statistics [2], which measures novelty, ecology, and complexity over *persistent lineages* rather than raw counts, and which is deliberately decoupled from the survival outcome it is meant to test. We situate the design in a four-field convergence on the *edge of chaos* — Wolfram's class-4 dynamics [13], Langton's λ [11], self-organised criticality [12], and a recent rigorous branching-threshold study [30] — and argue that PetriLab's central problem is distinguishing genuine accumulating novelty (class 4) from seasonal oscillation (class 2). We report honest observations: monoculture collapse in long runs, an immigration guard that restores lineage diversity, stagnation, and reheating. We are explicit about two unbroken walls — an expressivity ceiling where `tanh(sum)` collapses the phenotype to one dimension, and a novelty metric that cannot yet cleanly separate oscillation from true innovation. PetriLab does **not** yet satisfy the "new types of entities" hallmark of OEE.

---

## 1. Introduction

The defining puzzle of open-ended evolution is that biological evolution has produced an unbroken, escalating stream of novelty for billions of years, while almost every artificial evolutionary system does the opposite: it finds a good-enough configuration and stops. Objective-driven optimisation is especially prone to this — Miller's neural-creature simulator converges cleanly on a task and then "can run for millions of generations and never get any better" once the gene pool loses diversity [29]. The same collapse appears across genetic algorithms as *premature convergence*: a single early "superindividual" sweeps the population, diversity falls to near zero, and search stalls in a local optimum [23, 24]. A system that has converged is, for an OEE project, a *failed* run, not a solved one [23].

PetriLab asks one question, stated plainly in its research design: **can a system, under the right conditions, sustain open-ended evolution instead of collapsing into homeostasis?** [RESEARCH.md]. The project's history is a sequence of ways the answer came back "no, and here is why". The most instructive failure is a semantic one: an early novelty metric used an ever-growing "seen" set, so measured novelty decayed to zero mechanically after roughly 500k generations regardless of the underlying dynamics [modes.py]. Even after that was fixed, the deeper problem remained: roughly half of the apparent "seasonal novelty" turned out to be *oscillation* pumping the counter rather than accumulation [RESEARCH-grundlag]. The system was breathing with the seasons, but learning nothing new.

That failure mode has a precise name. Wolfram's empirical taxonomy of cellular automata places uniform/periodic behaviour in classes 1–2, chaos in class 3, and the rare, computationally rich regime — localised structures that move, collide, persist, and transform information — in class 4 [13], the regime whose canonical exemplar (Rule 110) was proven Turing-complete [14]. Seasonal oscillation that repeats forever is class 2: periodic, information-preserving, but not information-*creating* [wolfram report]. The distinction PetriLab must draw — genuine accumulating novelty versus seasonal oscillation — is, almost literally, the distinction between class 4 and class 2.

This paper describes what PetriLab actually is, why each design choice is defensible against the OEE and complexity literature, how the measurement contract is built to *falsify* rather than flatter the OEE claim, and — at length — where it still fails.

## 2. Background & related work

### 2.1 Four fields, one edge

A striking convergence runs through the sources that ground this project: four otherwise unrelated fields describe the same phenomenon under four names [SYNTESE]. Wolfram's class-4 "complex" regime sits between order (classes 1–2) and chaos (class 3) [13]. Langton's parameter λ measures how "active" a CA rule is, and the most computationally capable rules cluster at a critical λ in the transition zone he named the *edge of chaos* — the narrow band where information can be stored, transmitted, *and* transformed [11]. Bak, Tang and Wiesenfeld's self-organised criticality (SOC) describes the same tension from the dynamical side: a system that pulls itself toward a critical state with power-law-distributed avalanches [12]. And simulated annealing's critical temperature $T_c$ marks a phase transition where a single control knob carries the system from exploration to consolidation, with structure forming precisely in the critical band [simulated-annealing report].

The most rigorous member of this family is Almaghrabi's branching-threshold study [30]. Modelling multi-step search as a stochastic tree with branching factor $b$ and per-step success probability $p$, and invoking Galton-Watson theory [31], it shows that the expected number of all-correct paths is $(bp)^d$, so $bp = 1$ is a sharp threshold separating a subcritical regime (correct paths exponentially rare) from a supercritical one (paths proliferate). Across 4,169,000 Monte Carlo trials it demonstrates a sharp crossover, identifies the critical point objectively via peak *susceptibility* $\chi(C) = dP_\text{succ}/d\ln C$, and — crucially for us — collapses data from many $(b,p)$ combinations onto a single curve when plotted against $bp$ [30]. Where Langton's λ and Wolfram's classes are qualitative, $bp=1$ is a computable control parameter. Two of its findings bear directly on PetriLab: *branching dominates* (adding independent branches beats re-sampling the same node), and the *order-parameter collapse* is a stringent test for whether a candidate control parameter is the real axis [30].

### 2.2 The OEE literature and its hallmarks

The OEE II editorial names three hallmarks of open-endedness: ongoing generation of novelty, growth of complexity, and the appearance of new *types* of entities [10]. PetriLab treats this as its specification, and is candid that it meets only the first two at best — it produces "more of the same cell type", not new types [RESEARCH-grundlag]. Taylor's requirements analysis diagnoses the underlying problem: for open-endedness, "the reachable phenotype space must expand as evolution proceeds" [6], and his later taxonomy distinguishes exploratory, expansive, and transformational novelty — only the latter two enlarge the space of possibilities [7]. The theory of major evolutionary transitions adds the distinction between *limited* and *unlimited* heredity: a system with only a few effectively distinct heritable states cannot support unbounded complexity, and gene duplication helps only if duplicates can neofunctionalise [8]. Adams et al. give a formal criterion — genuine unbounded evolution requires that the *update rule itself* be modifiable by the state [5] — and Hickinbotham et al. push this furthest, arguing the genome should be executable code that can modify its own expression, so that no fixed semantic ceiling is imposed [9].

### 2.3 The measurement literature

Measuring OEE honestly is as hard as achieving it. The MODES toolbox provides four filtered metrics (change, novelty, ecology, complexity) gated by a **persistence filter** — count a state only if it survives $N$ generations — which removes exactly the oscillation flicker that plagued our early runs [1]. Bedau, Snyder and Packard's evolutionary-activity statistics prescribe a **shadow/null model**: run a randomised twin of the system and subtract its activity, so that only the *excess* counts as genuine adaptive novelty [2]. Novelty search reframes selection itself: reward behavioural difference rather than objective performance, using kNN sparsity against a growing archive, which automatically assigns low scores to recurring states [3]; its local-competition variant prunes within novelty neighbourhoods to preserve niches rather than collapse toward one optimum [4]. MAP-Elites makes diversity an explicit target by keeping an archive of elites across behavioural niches [15].

### 2.4 Mechanism and encoding

The genetic-algorithm and evolved-creature literature supplies the mechanistic vocabulary. Holland formalised the GA [23] and Goldberg popularised it [24]; Sims' evolved virtual creatures showed that a compact, recursive, *generative* encoding plus a dynamic (competitive) pressure yields emergent complexity no one designed [25]. NEAT contributes historical markings, speciation to protect young innovations, and "start minimal, grow complexity" [17]; HyperNEAT and CPPNs [18], L-systems [19], Push/linear GP [20], growing neural controllers [21], and neural cellular automata [22] each break an expressivity ceiling in a different way. POET co-evolves environments and agents so the challenge never settles [27]. And the field's cautionary literature — bloat [26] and the "surprising creativity of digital evolution", where evolution games any measurable proxy [28] — warns that every metric will be exploited at its weakest point. PetriLab's most direct sibling is Miller's biosim4 [29], from which it borrows mechanics (an oscillator gene, a kinship sensor, per-generation deterministic logging) while explicitly refusing his fixed fitness target, because objective selection converges and stops [29].

## 3. System design

PetriLab is a bottom-up dish of cells. Each cell has a position, an energy budget, a **variable-length genome** (a list of `[w, a, b]` gene triples), and — for lineage tracking — a `lineage_id` (its root ancestor) and `parent_id` [petrilab.py]. Cells are born, wire up edges, spend energy on upkeep and connections, communicate through a diffusing signal field, divide with heredity, and die when their energy reaches zero. There is **no goal and no fitness target** — only the standing tension "be complex" versus "complexity costs" [petrilab.py].

### 3.1 The invariant: frozen rules, tunable ratios

The engine's rules are frozen; only *conditions* may be tuned, and every feature flag defaults OFF so the default state is always the control [RESEARCH.md]. This is a deliberate methodological choice, not a limitation: a finding is accepted only if turning one condition-knob moves a pre-declared primary metric past a pre-declared threshold against an identical control [RESEARCH.md]. It directly implements the "one mechanism at a time, A/B against control" discipline that the GA literature identifies as the difference between legible and un-interpretable results [24, 28]. The engine exposes a fixed set of tunable ratios — energy influx, edge cost, mutation and gene-mutation rates, seasons and season length, signalling, chemotaxis, structural heredity [petrilab.py].

### 3.2 Open genome and heredity

Heredity was the phase where thin representations failed and structure succeeded. Inheriting a single bias scalar from the mother cell had no effect — "a scalar is too thin to carry selection" — whereas inheriting the mother's **connection pattern** (a subgraph) with mutation did carry selection: information lives in the connections, not the cells [RESEARCH.md]. Accordingly a dividing cell passes on a mutated genome, keeps the mother's `lineage_id`, and — with probability `structural_heredity` — inherits topology by copying the mother's out-edges [petrilab.py]. The genome mutation operator supports point mutation, **duplication**, fresh insertion, and deletion of gene triples [petrilab.py]. This is the minimal move toward the "unlimited heredity" the major-transitions literature demands [8], and duplication is included precisely because that literature notes duplication only helps if duplicates can diverge [8]. Lineage tracking is what makes MODES-style measurement over *persistent lineages* possible at all [1, petrilab.py].

### 3.3 Breaking homeostasis: seasons, immigration, reheating

Three mechanisms keep the dish from settling, each mapped to a citation.

**Seasons.** Light influx is modulated by a sinusoidal seasonal term [petrilab.py]. This is the project's anti-convergence engine: a non-stationary environment keeps the selection landscape moving so the population cannot "solve" the world and stop, exactly the dynamic-pressure prescription from POET [27] and Sims' competitive co-evolution [25]. The project's own finding H0003 recorded a large innovation increase from cyclic seasons [RESEARCH.md]. But seasons are double-edged: too-frequent switching drives the system toward chaos (class 3), long cycles toward complexity — and the class-2 oscillation trap is precisely a season signal that the system merely tracks rather than builds upon [SYNTESE, wolfram report].

**Immigration.** When living lineages fall below a floor, the engine periodically injects fresh founder lines [petrilab.py]. This is pure raw-material injection that never touches selection — the direct antidote to Miller's finding that a colony without genetic diversity is stuck forever when the environment changes [29], and to premature convergence [23]. Diversity, not input volume, is the resource that runs out [SYNTESE].

**Reheating.** When a complexity proxy (mean genome length) flatlines — measured by a coefficient of variation over a sparsely-sampled window so the test scales with genome size — the engine temporarily raises mutation, then cools back to baseline [petrilab.py]. This is simulated annealing with restarts, imported wholesale: a temperature boost to break a frozen equilibrium loose, an explicit remedy for stagnation in long runs [simulated-annealing report]. It touches only variation (mutation rates), never rules or selection.

### 3.4 The Gardener: a level-B autonomous experimenter

The Gardener is an autonomous experimenter that runs PetriLab's own scientific method. It never touches rules or DNA — **level B: it only tunes ratios** [gardener.py]. Its loop watches novelty and complexity; when stagnating it proposes an experiment (nudge one tunable ratio, remember the baseline), waits an evaluation window, measures the effect, and keeps or reverts the change, logging every decision with a reason [gardener.py]. Two design details defend it against known failure modes:

- **A composite objective** `0.5·novelty + 0.3·complexity_norm + 0.2·ecology`, deliberately decoupled from novelty alone to avoid gaming a single axis [gardener.py] — a direct response to the "digital evolution games any proxy" literature [28].
- **Durable per-knob learning** via an EWMA of each knob's effect plus optimistic-init UCB selection, so knobs that genuinely helped stay favoured while exploration continues, and the memory survives restarts rather than collapsing all knobs to a floor [gardener.py].

Every 25 experiments the Gardener distils its trials into dated conclusions appended to a findings file, and — importantly — emits an explicit **`## ACTION NEEDED`** block when it concludes it has hit a wall that only a level-A (rules/genotype) change could break: e.g. a knob pinned at its bound while still showing positive effect, or tens of thousands of generations of non-success despite exploring nearly every knob [gardener.py]. This is the honest boundary of a level-B agent: it can find the wall and name it, but it may not cross it. Confining automated search to ratios while flagging when the *rules* need to change is the operational form of the distinction between tuning a system and changing its update rule [5, 9].

## 4. Measurement & falsification

PetriLab refuses to judge "life" by eye; the network view is secondary and **emergence is statistical, not visual** [RESEARCH.md]. The measurement module implements MODES-style axes over persistent lineages and a separate falsification contract [modes.py].

### 4.1 MODES axes over lineages

The `Modes` class computes, per sample: **novelty** (fraction of a sliding reference window whose coarse macrostate signature is unseen), **change** (L1 turnover of lineage composition), **ecology** (Shannon evenness of the lineage distribution), and **complexity** (mean genome length blended with connectivity) [modes.py]. Two anti-circularity choices are deliberate. Novelty uses a *sliding* reference window rather than an eternal set, so it reflects dynamics rather than library size — the explicit fix for the v1 metric that decayed to zero after ~500k generations [modes.py]. And the macrostate signature is discretised (binned) so that mere jitter is not counted as "new" — an operational persistence filter in the MODES spirit [1, modes.py].

### 4.2 The falsification contract

The falsification panel is decoupled from the novelty definition so it cannot measure its own success [modes.py]. It declares a run a *success* only if three independent conditions hold simultaneously:

1. **lineage_survival** — at least three lineages have persisted ≥20 generations (the system has not collapsed to a monoculture). This counts lineages, never "new patterns", so the survival outcome is independent of the novelty axis [modes.py].
2. **novelty_alive** — recent mean novelty exceeds a floor (the system is still minting new macrostates) [modes.py].
3. **not_periodic** — the novelty stream is *not* a clean oscillation, tested by autocorrelation: if the maximum autocorrelation at any lag exceeds 0.7, the stream is judged periodic [modes.py].

The third test is the direct operationalisation of "are we in class 2?" [wolfram report, SYNTESE]. A run that scores high novelty *only because* it oscillates seasonally will fail `not_periodic` and be denied a success verdict — this is the anti-class-2 guard built into the contract. **What would falsify the OEE claim:** if novelty dies (`novelty_alive` false) or the dish collapses to a monoculture (`lineage_survival` false), the verdict is an unambiguous *failure*; if novelty persists but is periodic, the verdict is *unresolved* rather than success [modes.py]. The claim is thus falsifiable by construction: three orthogonal ways to fail, all measured, none derivable from the definition of novelty.

### 4.3 Measurements the design calls for but has not yet built

The knowledge synthesis prescribes cheap edge-of-chaos diagnostics that PetriLab's contract points toward but does not yet fully implement [SYNTESE, wolfram report]: a **perturbation test** (flip one cell, measure whether the disturbance dies out, spreads, or explodes — a Lyapunov-style class-3 detector); a **power-law/SOC avalanche-size distribution** (power-law = critical/fertile, exponential = subcritical/frozen); and an **order-parameter collapse and susceptibility analysis** in the style of the branching-threshold study, to test whether a candidate "effective reproduction rate of innovations" is the true control axis [12, 30, SYNTESE]. The autocorrelation test is implemented [modes.py]; the avalanche and perturbation diagnostics remain future instrumentation (Section 7). We flag this openly rather than claim a completeness the code does not have. [citation needed for any specific power-law exponent — none has been measured yet, so none is reported.]

## 5. Results / observations

We report these as honest observations from development, not as validated grand claims. The project's evidence chain [RESEARCH.md] records a sequence of A/B findings against control:

- **H0001** — cheaper edges yielded a large complexity increase (+138%), confirming the engine is sensitive to conditions in a legible way [RESEARCH.md].
- **H0002** — a prune-threshold change came back inactive; edge cost already dominates pruning (a null) [RESEARCH.md].
- **H0006** — chemotactic receptors made connected cells physically cluster into tissue (+175% spatial): the first self-organisation, measured rather than eyeballed [RESEARCH.md].
- **H0003** ✅ seasons raised innovation; **H0004** ✅ endogenous selection modestly improved post-shock recovery; **H0005** ⚪ catastrophes *alone* did not raise lasting innovation — "shocks without memory aren't enough", a useful null [RESEARCH.md].
- **H0007** ⚪ inheriting a single bias scalar had no effect; **H0008** ✅ inheriting the mother's connection pattern (+27% complexity) did carry selection [RESEARCH.md].
- **H0009** ✅ adding emit/sensitivity genes and a wireless signalling layer produced a *restless* system: innovation rose sharply while complexity stayed flat — perpetual novelty without runaway complexity, the quality the project set out to find [RESEARCH.md].

Longer runs exposed the failure modes the anti-homeostasis mechanisms were built to answer. The v1 novelty metric decayed to zero after roughly 500k generations for a purely mechanical reason (an unbounded "seen" set), which is why v2 rebuilt it with a sliding window [modes.py]. In long v2 runs the dish tends to drift toward **monoculture** — living lineages fall away until the population is dominated by one line — which is why the immigration guard exists and fires when the lineage count drops below its floor [petrilab.py]. When the complexity proxy flatlines the reheating mechanism triggers, temporarily raising mutation before cooling back down [petrilab.py]; the Gardener counts these reheating events and reports them in its conclusions as evidence that anti-stagnation machinery is being exercised [gardener.py]. The overall picture is not "sustained open-endedness achieved" but "a system that repeatedly approaches homeostasis and has explicit, measured mechanisms that push it back off the fixed point — with the open question of whether that push produces class-4 accumulation or merely a higher-order class-2 cycle".

## 6. Limitations & threats to validity

This section is the point of the paper. Honest threats matter more than hidden holes.

**The expressivity ceiling.** The genome-to-phenotype map is `tanh(sum of gene contributions)`, which is a surjection into a *single* dimension in [−1, 1] [petrilab.py, RESEARCH-grundlag]. An open (variable-length) genome broke the *length* ceiling but not the *expressivity* ceiling: extra genes only move the point along the same 1-D line; they do not add phenotypic *dimensions* [RESEARCH-grundlag]. Notably, Miller's simulator has the identical `tanh(sum)` neuron but escapes the ceiling by using *many* neurons and sensors rather than one bias number [miller report]. Until PetriLab's map is made structure-expanding — a GRN, CPPN, L-system, or executable-genome representation, each of which lets a new gene open a new axis [16, 18, 19, 20, 9] — the substrate cannot satisfy Taylor's requirement that the reachable phenotype space expand as evolution proceeds [6, 7].

**The novelty metric cannot yet separate oscillation from true novelty.** Roughly half of an apparent seasonal "novelty" signal was found to be oscillation pumping the counter [RESEARCH-grundlag]. This is the class-2 trap named explicitly [SYNTESE, wolfram report]: the current metric measures output-value states, not *interaction patterns*, so a periodic breathing of the population can masquerade as accumulation. The `not_periodic` autocorrelation guard [modes.py] catches clean oscillation but is a blunt instrument; it does not positively certify class-4 accumulation, only the absence of one obvious class-2 signature. The recommended upgrades — kNN sparsity against an archive [3], a shadow/null model that subtracts randomised activity [2], and novelty measured over interaction patterns rather than output values [RESEARCH-grundlag] — are not yet in place.

**The "new types of entities" hallmark is unmet.** By the OEE II specification [10], PetriLab currently produces ongoing novelty and (episodically) complexity but no genuinely new *types* of entities — only more of the same cell type [RESEARCH-grundlag]. On the limited-vs-unlimited-heredity axis [8], the effective heritable repertoire is small; gene duplication is implemented [petrilab.py] but neofunctionalisation of duplicates has not been demonstrated.

**Freedom without gradient is drift.** Any expansion of the genome's expressive space risks producing dimensions no cell uses. The literature and the project's own analysis agree that a new degree of freedom pays off only under frequency-dependent selection — when *another* cell exploits it [RESEARCH-grundlag, 29]. Open-endedness is co-evolutionary pressure, not raw dimensionality.

**Metric gaming.** A composite Gardener objective reduces but does not eliminate the risk that automated search exploits a measurement weakness rather than producing real structure [28, gardener.py]; and in any physics/economy simulation an "exploit of a simulator bug" — a lineage that finds a numerical glitch and proliferates — is a live risk [28].

**Computational irreducibility and scale.** For genuinely class-4 systems there is no analytic shortcut: one must simulate and measure [wolfram report]. This is both a licence (we should not expect to predict novelty from parameters) and a cost (every question requires a run). PetriLab is single-machine, with hard caps (max nodes, memory) [petrilab.py]; the branching-threshold study's own caveat applies doubly here — its i.i.d. assumption is violated by interacting, *correlated* cells, so $bp=1$ is a guiding star, not an exact prediction for our dish [30].

**Reproducibility.** All stochasticity is seeded and logged, and state serialises so runs survive restarts [petrilab.py, gardener.py]. We aspire to, but have not yet built, the branching-study's data-to-text audit table mapping every reported number to the exact query that produced it [30].

## 7. Future work

Four directions follow directly from the sources and the limitations above.

1. **Expanding signal channels to break the expressivity ceiling.** Make `emit`/`sensitivity` lists indexed by channel ID so a new gene can open a new communication axis; when cell P emits on channel 7 and cell Q evolves a receptor for channel 7, a genuinely new degree of freedom appears in the relation [RESEARCH-grundlag]. Per the branching study, adding *independent* channels is "increasing b" — the dominant lever, strictly stronger than tuning existing channels [30]. This must ship as a feature flag defaulting OFF (control preserved), with three sharpened requirements: frequency-dependent payoff (Miller's kinship sensor as raw material) [29], novelty measured on *interaction patterns* not output values, and verification that measured phenotypic dimensionality actually grows (e.g. PCA on cell behaviour) [RESEARCH-grundlag, SYNTESE].
2. **Build the cheap edge-of-chaos diagnostics first.** Add the avalanche-size (power-law/SOC) distribution and the perturbation test *before* the next mechanism, so we can see whether the current engine even sits in the fertile regime [12, wolfram report, SYNTESE]. Show them live on the dashboard alongside an order-parameter reading, so the regime (class 2 / 4 / 3) is visible.
3. **Edge of chaos as the control target.** Rather than chasing novelty directly, steer the system toward the critical band where novelty arises on its own, using the annealing "temperature" framing already partly realised by reheating [simulated-annealing report, SYNTESE], and validate the chosen control parameter with an order-parameter collapse and susceptibility peak in the style of [30].
4. **Self-generating hypotheses.** Let the Gardener build each next hypothesis on the last finding rather than a hand-made queue — standing on its own shoulders [SYNTESE]. The durable per-knob memory [gardener.py] is the seed of this; coupling signalling output to a simple agent in a small world (sense → process → act) is the larger build the research design already anticipates [RESEARCH.md].

## 8. Conclusion

PetriLab is an honest attempt at open-ended evolution built on three defensible commitments: an open genome with heritable structure, a level-B autonomous experimenter that tunes only ratios against a frozen-rules control, and a falsification-first measurement contract that can declare its own failure three independent ways. Its design is anchored throughout in a four-field convergence on the edge of chaos — Wolfram's class 4 [13], Langton's critical λ [11], self-organised criticality [12], and a rigorous branching-threshold methodology [30] — and in the OEE measurement tradition of MODES [1], evolutionary-activity statistics [2], and novelty search [3, 4]. The project's central, unresolved problem is exactly the class-4-versus-class-2 distinction: telling genuine accumulating novelty from seasonal oscillation. Two walls remain standing — a `tanh(sum)` expressivity ceiling that collapses the phenotype to one dimension, and a novelty metric that cannot yet cleanly separate oscillation from innovation — and the "new types of entities" hallmark of open-endedness is not met. We regard naming these walls precisely, and building the instruments to detect them, as the actual contribution. A system that knows how it fails is the prerequisite for one that eventually does not.

---

## References

[1] Dolson, E., Lalejini, A., Fenton, J., & Ofria, C. (2019). *MODES: Metrics for Open-Ended and Dynamic Evolutionary Systems* (MODES toolbox). Artificial Life, 25(1). DOI: 10.1162/artl_a_00280.

[2] Bedau, M. A., Snyder, E., & Packard, N. H. (1998). *Evolutionary Activity Statistics* (A classification of long-term evolutionary dynamics).

[3] Lehman, J., & Stanley, K. O. (2011). *Abandoning Objectives: Evolution through the Search for Novelty Alone.* Evolutionary Computation, 19(2). DOI: 10.1162/EVCO_a_00025.

[4] Lehman, J., & Stanley, K. O. (2011). *Evolving a Diversity of Virtual Creatures through Novelty Search and Local Competition.* GECCO. DOI: 10.1145/2001576.2001606.

[5] Adams, A., Zenil, H., Davies, P. C. W., & Walker, S. I. (2016/2017). *Formal Definitions of Unbounded Evolution and Innovation Reveal Universal Mechanisms for Open-Ended Evolution in Dynamical Systems.* Scientific Reports 7:997. arXiv:1607.01750.

[6] Taylor, T. (2015). *Requirements for Open-Ended Evolution in Natural and Artificial Systems.* arXiv:1507.07403.

[7] Taylor, T. (2019). *Evolutionary Innovations and Where to Find Them: Routes to Open-Ended Evolution in Natural and Artificial Systems.* arXiv:1806.01883.

[8] Maynard Smith, J., & Szathmáry, E. (1995). *The Major Transitions in Evolution.* See also Szathmáry, E. (2015). *Toward major evolutionary transitions theory 2.0.* PNAS. DOI: 10.1073/pnas.1421398112.

[9] Hickinbotham, S., et al. (2022). *Self-Modifying Code in Open-Ended Evolution.* arXiv:2201.06858.

[10] Packard, N., Bedau, M. A., Channon, A., Ikegami, T., Rasmussen, S., Stanley, K. O., & Taylor, T. (2019). *Open-Ended Evolution and Open-Endedness: Editorial Introduction to the OEE II Special Issue.* arXiv:1909.04430.

[11] Langton, C. G. (1990). *Computation at the Edge of Chaos: Phase Transitions and Emergent Computation.* Physica D, 42. DOI: 10.1016/0167-2789(90)90064-V.

[12] Bak, P., Tang, C., & Wiesenfeld, K. (1987). *Self-Organized Criticality: An Explanation of 1/f Noise.* Physical Review Letters, 59. DOI: 10.1103/PhysRevLett.59.381.

[13] Wolfram, S. (2002). *A New Kind of Science.* Wolfram Media. (Elementary cellular automata; four complexity classes; Rule 30; computational irreducibility.)

[14] Cook, M. (work c. 1990s, published later). *Universality in Elementary Cellular Automata* (proof that Rule 110 is Turing-complete). Cited in the PetriLab Wolfram-CA knowledge report.

[15] Mouret, J.-B., & Clune, J. (2015). *Illuminating Search Spaces by Mapping Elites (MAP-Elites).*

[16] Banzhaf, W. (2003). *On the Dynamics of an Artificial Regulatory Network* (gene-regulatory-network encoding).

[17] Stanley, K. O., & Miikkulainen, R. (2002). *Evolving Neural Networks through Augmenting Topologies (NEAT).*

[18] Stanley, K. O., D'Ambrosio, D., & Gauci, J. (2009). *A Hypercube-Based Encoding for Evolving Large-Scale Neural Networks (HyperNEAT / CPPN).* See also Stanley, K. O. (2007), *Compositional Pattern Producing Networks.*

[19] Lindenmayer, A., & Prusinkiewicz, P. (1990). *The Algorithmic Beauty of Plants* (L-systems).

[20] Spector, L., & Robinson, A. (2002). *Genetic Programming and Autoconstructive Evolution with the Push Programming Language.*

[21] Risi, S., & Stanley, K. O. (2012). *An Enhanced Hypercube-Based Encoding for Evolving the Placement, Density, and Connectivity of Neurons.*

[22] Mordvintsev, A., Randazzo, E., Niklasson, E., & Levin, M. (2020). *Growing Neural Cellular Automata.*

[23] Holland, J. H. (1975). *Adaptation in Natural and Artificial Systems.*

[24] Goldberg, D. E. (1989). *Genetic Algorithms in Search, Optimization, and Machine Learning.*

[25] Sims, K. (1994). *Evolving Virtual Creatures* (SIGGRAPH); *Evolving 3D Morphology and Behavior by Competition* (Artificial Life IV).

[26] Koza, J. R. (1992). *Genetic Programming: On the Programming of Computers by Means of Natural Selection.*

[27] Wang, R., Lehman, J., Clune, J., & Stanley, K. O. (2019). *POET: Paired Open-Ended Trailblazer.*

[28] Lehman, J., et al. (2018/2020). *The Surprising Creativity of Digital Evolution.*

[29] Miller, D. R. *"I Programmed Some Creatures. They Evolved."* (biosim4 evolutionary simulator; YouTube). Summarised in the PetriLab Miller-creatures knowledge report.

[30] Almaghrabi, S. (2026). *Phase Transitions in Reasoning Search: Emergent Threshold Phenomena in Branching Reasoning Search Under Compute Constraints — A Simulation Study.* Independent Researcher, March 2026.

[31] Harris, T. E. (1963). *The Theory of Branching Processes.* Springer-Verlag. (Galton-Watson survival threshold at mean offspring = 1; theoretical antecedent of the $bp=1$ threshold in [30].)

---

*Primary system artifacts referenced by filename: `petrilab.py` (engine), `gardener.py` (autonomous experimenter), `modes.py` (measurement + falsification), and the project research design `docs/RESEARCH.md`. Knowledge reports grounding the citation base: `RESEARCH-grundlag.md`, `SYNTESE.md`, and the four domain reports on Wolfram CA, Miller's creatures, genetic algorithms, and simulated annealing.*
