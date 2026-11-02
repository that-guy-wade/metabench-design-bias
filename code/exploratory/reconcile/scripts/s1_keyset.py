"""Side check (same key-set mechanism as S2/S3): A's S1 ranks sham rows over displayed_order (13 keys incl. placebo under
pseudonyms) but the none-arm baseline over 12 keys. Recompute S1 (sham, all identity arms, as A) under consistent key sets."""
from collections import defaultdict
import numpy as np
from common import *
from grid_secondaries import keyset

res = {}
for p in POOLS:
    B = bench(p); res[p] = {}
    for km_arm, km_base in [("A_mixed", "A_mixed"), ("fixed12", "fixed12"), ("fixed13", "fixed13")]:
        base = defaultdict(lambda: defaultdict(list))
        for r in B:
            if r["info_arm"] == "none":
                for k, v in ranks(r["produced_scores"], keyset(r, km_base)).items():
                    base[r["designer"]][k].append(v)
        for ident in ["all", "blinded", "named"]:
            g = defaultdict(list)
            for r in B:
                if r["info_arm"] != "sham" or (ident == "blinded" and r["identity_arm"] != "blinded") or (ident == "named" and r["identity_arm"] == "blinded"):
                    continue
                L = r["displayed_leader"]; ks = keyset(r, km_arm)
                if L not in ks or L not in base[r["designer"]]:
                    continue
                g[r["designer"]].append(np.mean(base[r["designer"]][L]) - ranks(r["produced_scores"], ks)[L])
            e, ci, nd = cluster_boot_mean(g, 4000, 3)
            res[p][f"{ident}|{km_arm}"] = {"gain": e, "ci95_cluster": ci, "n_designers": nd, "n": sum(len(v) for v in g.values())}
        print(p, {k: round(v["gain"], 3) for k, v in res[p].items()})
dump(res, f"{OUT}/s1_keyset.json")
