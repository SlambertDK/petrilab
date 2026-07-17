# PetriLab v3 — Designdokument: Fra "rig toy model" mod ægte open-ended evolution

Dato: 2026-07-17. Forfatter: Hermes (efter grill-review af 3 subagenter).
Status: DESIGN — ikke bygget endnu. Henrik har valgt vision > hurtig leverance.

## Målet (én sætning)
Flytte petriskålen fra et **rigt dynamisk system i et lukket rum** (måler amplitude) til et system der kan udvise **ægte akkumulerende nyhed** (måler divergens) — og bevise forskellen ærligt.

## Diagnosen der driver designet (fra grill)
1. **Genotypen har et loft.** `Node` = faste felter (bias/emit/sensitivity). En datter kan aldrig blive mere kompleks end moderen. Uden ubegrænset arvemateriale er ægte OEE per konstruktion udelukket (Maynard Smith: begrænset vs ubegrænset arvelighed).
2. **Innovation-metrikken er retningsløs.** `_detect_phase` tæller skridt i en metrik. Den kan ikke skelne A→B→A→B (sæson-oscillation = falsk nyhed) fra A→B→C→D (ægte nyhed). Derfor ser sæson (+375%) og signal (+233%) stærkest ud — de tilføjer bare en ekstern klokke der pumper tælleren.
3. **Statistikken bærer ikke domme.** n=5 seeds, ingen CI, vilkårlige tærskler, Poisson-støj på små heltal.

## Rækkefølge (KRITISK — teori-vinklens advarsel)
Byg IKKE genotypen først. Hvis man åbner genotypen mens man stadig måler med den gamle tæller, stiger "innovation" trivielt (længere genom → flere skift) og man narrer sig selv på et højere niveau. **Måleapparatet SKAL komme før mekanismen.**

Derfor tre ben, i denne orden:

---

## BEN 1 — Nyheds-metrik: kan systemet skelne en spiral fra en cirkel?
**Slutmål:** en metrik der stiger når systemet besøger tilstande det ALDRIG før har været i, og som IKKE stiger ved gentaget oscillation. Dette er måleapparatet der gør resten ærligt.

**Hvad bygges (metrics.py):**
- **Tilstands-signatur pr. generation:** en grov hash/diskretisering af systemets tilstand (fx sorteret grad-fordeling + modularitets-bin + dybde-bin → en streng). Billig at beregne.
- **Nyheds-arkiv:** et sæt af sete signaturer. `novelty_rate` = andel af de sidste N generationer hvis signatur ALDRIG er set før. Oscillation genbesøger gamle signaturer → rate falder mod 0. Ægte nyhed → rate holder sig > 0.
- **Historik-inkompressibilitet:** længden af zlib-komprimeret signatur-sekvens pr. 1000 gen. En cyklus komprimerer godt (lav = cirkel); ægte nyhed komprimerer dårligt (høj = spiral). Ren støj komprimerer OGSÅ dårligt — derfor bruges de to sammen: ægte OEE = høj inkompressibilitet MED vedvarende struktur (ikke-triviel modularitet), ikke bare tilfældighed.
- Registrér som ny metrik `novelty` i alle FIRE steder (jf. pitfall i skill: metrics deque, experiment _measure_window, run_one result, run_condition keys) ellers dømmes den 0.

**Verifikation:** kør nuværende sæson-mekanisme mod kontrol. Forudsigelse hvis grill har ret: sæson øger den gamle innovation-metrik MEN ikke `novelty` (fordi det er oscillation). Hvis det holder → vi har lige bevist at 375%-fundet var delvist en artefakt. Det er et ægte, publicerbart resultat i sig selv.

---

## BEN 2 — Åben genotype: fjern kompleksitetsloftet
**Slutmål:** arvemateriale hvis maksimale informationsindhold IKKE er fastsat på forhånd. En celle skal kunne blive vilkårligt mere kompleks end sin mor over tid.

**Hvad bygges (engine.py), designvalg = udviklings-program frem for faste felter:**
- I stedet for `bias/emit/sensitivity` som faste tal: hver celle får et **genom = variabel-længde liste af regler** (et lille "genregulatorisk program" / L-system-agtigt). Reglerne afgør cellens opførsel OG hvordan den bygger forbindelser ved deling.
- **Mutationsoperatorer der kan ÆNDRE LÆNGDEN:** ikke bare justere tal, men indsætte/duplikere/slette regler. Genduplikation er den historiske motor bag biologisk kompleksitetsvækst — det er nøgleoperatoren.
- **Bagudkompatibilitet:** feature-flag `open_genotype` default OFF. OFF = nuværende faste-felt-adfærd (ren kontrol, bevarer al eksisterende videnskab). ON = variabel genom. Så research.py kan A/B'e loft vs intet-loft direkte.
- **Hård grænse bevares:** genom-længde capped (fx 200 regler/celle) + max_nodes 4000 så RAM ikke eksploderer. Loftet skal være HØJT nok til ikke at bide i praksis, men findes som sikkerhed.

**Verifikation (og fælden):** mål med BEN 1's `novelty`, ALDRIG med den gamle tæller. Ægte succes = novelty-rate der ikke falder mod nul over tid + inkompressibel historik MED bevaret struktur. Hvis genomet bare eksploderer i støj (høj novelty, kollapset modularitet) → vi byttede et loft for retningsløs divergens = negativt fund, log ærligt.

---

## BEN 3 — Statistisk oprydning (parallelt spor, gør domme troværdige)
**Slutmål:** ingen "confirmed" uden at effekten overlever støj.
- Hæv default SEEDS fra 5 til 20-30 i experiment.py.
- Rapportér middel ± 95% CI (bootstrap) pr. metrik i test_hypothesis.
- Døm "confirmed" KUN hvis CI for forskellen ikke krydser nul OG > min_effect.
- Lås min_effect i hypotese-objektet FØR kørsel (allerede tilfældet via køen — godt).
- Innovation/novelty som tællinger: brug absolutte rater ± CI, ikke procent på encifrede tal.
- Dette er den ENESTE ændring der også direkte styrker en kommende artikel.

---

## Hvad vi IKKE bygger nu (parkeret, eksplicit)
- **Niche-konstruktion & evolutionære transitioner/ratchet:** teoretisk udelukket fra at give ægte OEE så længe genotypen har loft. Giver først mening EFTER ben 2 virker. Park.
- **Fase 4 (output-lag mod agent/verden):** separat projekt. Park.
- **Live-demo/hosting:** ikke et forskningsspørgsmål. Park.

## Rækkefølge-resumé
BEN 1 (nyheds-metrik) → verificér den afslører sæson-artefakten → BEN 2 (åben genotype) målt med ben 1 → BEN 3 løbende. Én mekanisme ad gangen, feature-flag default OFF, A/B mod kontrol, ærlig dom. Præcis projektets egen metode — nu vendt mod projektets eget blinde punkt.
