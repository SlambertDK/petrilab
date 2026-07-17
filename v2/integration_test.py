import sys, time
sys.path.insert(0, "/home/henrik/petriskal/v2")
from petrilab import Petri
from modes import Modes
from gardener import Gardener

sim, modes, g = Petri(seed=7), Modes(), Gardener()
t0 = time.time()
for gen in range(6000):
    sim.step()
    if sim.generation % 10 == 0:
        rec, _ = modes.update(sim)
    if sim.generation % 50 == 0:
        f = modes.falsification(sim)
        g.observe(sim, rec, f)
dt = time.time() - t0
print(f"6000 gens in {dt:.1f}s")
print("FINAL MODES:", modes.history[-1])
print("FINAL FALSIFICATION:", modes.falsification(sim))
print("cells:", len(sim.cells), "lineages:", len(sim.lineage_census()))
print("gardener decisions:", len(g.log))
print("--- last 8 gardener actions ---")
for e in g.log[-8:]:
    print(f"  gen {e['gen']}: {e['action']}  [{e['reason']}]")
print("--- knob credit (what helped) ---")
print({k: round(v,2) for k,v in g.knob_credit.items()})
