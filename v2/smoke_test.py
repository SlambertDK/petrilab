import sys, time
sys.path.insert(0, "/home/henrik/petriskal/v2")
from petrilab import Petri

p = Petri(seed=42)
t0 = time.time()
snaps = []
for g in range(3000):
    p.step()
    if g % 300 == 0 or g == 2999:
        cen = p.lineage_census()
        gsz = [len(c.genome) for c in p.cells.values()]
        snaps.append((p.generation, len(p.cells), len(p.edges), len(cen),
                      max(gsz) if gsz else 0,
                      round(sum(gsz)/len(gsz), 1) if gsz else 0))
dt = time.time() - t0
print(f"ran 3000 gens in {dt:.1f}s ({3000/dt:.0f} gen/s)")
print("gen    cells edges lineages maxGenome avgGenome")
for s in snaps:
    print(f"{s[0]:<6} {s[1]:<5} {s[2]:<5} {s[3]:<8} {s[4]:<9} {s[5]}")
