"""Side check: A's instructed-arm (C1) target rank gain ranks instructed rows over displayed_order (13 keys incl. placebo)
but the none baseline over 12 keys. Recompute under consistent key sets. EXPLORATORY."""
from collections import defaultdict
import numpy as np
from common import *
from grid_secondaries import keyset
res = {}
for p in POOLS:
    B = bench(p); res[p] = {}
    for km in ["A_mixed", "fixed12", "fixed13"]:
        base = defaultdict(lambda: defaultdict(list))
        for r in B:
            if r["info_arm"] == "none":
                for k, v in ranks(r["produced_scores"], keyset(r, km)).items():
                    base[r["designer"]][k].append(v)
        g = defaultdict(list)
        for r in B:
            if r["info_arm"] != "instructed":
                continue
            T = r["target_model"]; ks = keyset(r, km)
            if T in ks and T in base[r["designer"]]:
                g[r["designer"]].append(np.mean(base[r["designer"]][T]) - ranks(r["produced_scores"], ks)[T])
        e, ci, nd = cluster_boot_mean(g, 4000, 3)
        res[p][km] = {"gain": e, "ci95_cluster": ci, "n_designers": nd, "n": sum(len(v) for v in g.values())}
    print(p, {k: "%.3f [%.3f,%.3f] n=%d" % (v["gain"], *v["ci95_cluster"], v["n"]) for k, v in res[p].items()})
dump(res, f"{OUT}/c1_keyset.json")
