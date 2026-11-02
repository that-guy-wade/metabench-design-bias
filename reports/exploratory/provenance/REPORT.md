MetaBench T1: provenance classifier (PREREG section 12) and kept-vs-viewed decomposition (PREREG section 10)
EXPLORATORY, post-unblinding, 2026-10-30. No LLM calls. Nothing outside analysis/provenance/ was written.
Data: unblinded/WORK_{factual,math,code}, valid sessions only (factual 468, math 418, code 467; 12 designers; math
lost Google sessions: gemini4argon 24, gemini31pro 22, gemini38flash 21 of 39).

BOTTOM LINE
1. Designers leave strong signatures in what they select. A TF-IDF + logistic classifier identifies which of the 12
   designers built a benchmark from its 100 selected items with 88.5% accuracy pooled (chance 8.3%). On sham/blinded
   benchmarks alone it reaches 77.3%. It identifies the developer (4 classes) with 91.8% accuracy (chance 25%).
   - The signature goes well beyond difficulty. Accuracy is +0.42 above a difficulty+category baseline and +0.29 above
     a full difficulty-distribution baseline.
   - A classifier trained only on none-arm benchmarks still identifies the designers of sham/blinded benchmarks well
     above chance (0.47 to 0.82 by pool), so the signature carries across arms.
   - The signature is which items were chosen (habits of browsing, quotas and difficulty), not wording. Pool text is
     fixed, and a bag of item ids does as well as TF-IDF.
   - In the prereg's words: designer signatures exist in the artefact even when identities are blinded. This says
     nothing about self-favouring: Psi and S2 are unchanged.
2. Kept vs viewed. Sham designers look at a median of about 410 to 470 items and keep 100.
   - The kept set tracks the sham display no better than random draws from the items the designer looked at
     (selection -0.004 [-0.016, +0.009]).
   - The items looked at track the display no better than random pool draws (exposure -0.006 [-0.013, +0.001]).
   - So the steering null holds at both stages, not only in the end product.
   - The +3.9-point hardening with score access is a selection effect, not an exposure effect. Against the none arm:
     selection -3.93 points [-5.18, -2.63]; exposure -0.27 [-0.58, +0.02].
   - In the true_blinded arm, the kept set tracks the shown true order above random-from-viewed (+0.060). This is a
     mechanical overlap artefact: the order was computed on an early draft that the kept set largely retains. The
     none arm shows the same lift toward its own unshown round-1 draft (+0.092).

======================================================================================================================
PART 1. PROVENANCE CLASSIFIER
======================================================================================================================
Method (classify.py)
- Unit: one valid session (benchmark). Target: designer (12 classes); also developer (4 classes), both by collapsing
  the 12-class predictions and with a direct 4-class model.
- Feature sets, all built from the 100 submitted item ids:
  - tfidf: TF-IDF (sublinear, unigrams, min_df 2, max_df 0.95) over the concatenated pool `question` text of the
    100 items. The vectorizer is fit without labels on the subset's documents. Edited wording is ignored.
  - items: binary bag of the 2,000 item ids.
  - mix: category and source proportions.
  - difficulty (the prereg-requested baseline): mean reference accuracy of the items (n_correct/n_samples on the full
    pool, averaged over the 12 designer keys) plus category proportions.
  - diffprof (extra): mean, sd and 10-bin histogram of item reference accuracy, plus category proportions.
  - listpos (extra, content-free): mean, sd and 10-bin histogram of each item's position in the list_items order
    (sorted ids). This captures how deep a designer pages.
- Model: multinomial L2 logistic regression with fixed, prespecified C (10 for sparse sets; 1 for dense sets after
  standardising). C was not tuned.
- CV: StratifiedGroupKFold(5), stratified by target, groups = session_id, repeated with seeds 0-4. Each session is
  one row, so no session is ever in both train and test.
- Accuracy: mean per-session share of correct out-of-fold predictions.
- 95% CI: 2,000 bootstrap resamples of sessions stratified by designer. This covers test-sample uncertainty only;
  designer is the label, so a designer-cluster bootstrap is not meaningful here.
- p-value: permutation test with 100 full CV refits on shuffled labels. The floor is p = 1/101 = 0.010, and every p
  below is at that floor unless stated.
- Pooled: all sessions of the three pools, bootstrap stratified by pool x designer, null = n-weighted mean of the
  pool nulls.

Table 1a. 12-class designer accuracy (chance 0.083; permutation-null means 0.074 to 0.093 in every cell)
                    all sessions                  none/blinded                 sham/blinded
pool     n       tfidf   [95% CI]            n   tfidf   [95% CI]           n   tfidf   [95% CI]
factual  468/12  0.938 [0.917, 0.957]        60  0.850 [0.777, 0.920]       60  0.820 [0.740, 0.897]
math     418/12  0.852 [0.822, 0.880]        56  0.657 [0.564, 0.746]       55  0.789 [0.713, 0.855]
code     467/12  0.862 [0.836, 0.888]        60  0.787 [0.697, 0.873]       60  0.710 [0.633, 0.783]
pooled  1353/12  0.885 [0.870, 0.899]       176  0.767 [0.714, 0.816]      175  0.773 [0.728, 0.814]

Table 1b. 4-class developer accuracy (chance 0.25; majority-class rate 0.25 in factual and code, 0.28 in math)
                    all: direct / collapsed            none/blinded: direct / collapsed   sham/blinded: direct / collapsed
factual  0.954 [0.936,0.970] / 0.960 [0.944,0.974]   0.903 / 0.937                      0.827 / 0.850
math     0.901 [0.876,0.925] / 0.898 [0.871,0.922]   0.750 / 0.761                      0.807 / 0.829
code     0.896 [0.872,0.919] / 0.904 [0.879,0.925]   0.833 / 0.850                      0.750 / 0.793
pooled   0.918 [0.905,0.931] / 0.921 [0.909,0.933]   0.831 [0.791,0.869] / 0.851        0.794 [0.752,0.835] / 0.824 [0.783,0.865]

Table 1c. Feature sets, pooled 12-class accuracy [95% CI] (per-pool values are in classifier_tables.txt)
feature set        all (n=1353)           none/blinded (176)     sham/blinded (175)
tfidf              0.885 [0.870, 0.899]   0.767 [0.714, 0.816]   0.773 [0.728, 0.814]
items (id bag)     0.910 [0.897, 0.923]   0.851 [0.810, 0.890]   0.818 [0.775, 0.859]
mix (cat+source)   0.445 [0.423, 0.465]   0.385 [0.334, 0.436]   0.409 [0.363, 0.457]
difficulty         0.468 [0.447, 0.490]   0.418 [0.366, 0.468]   0.459 [0.410, 0.512]
diffprof           0.594 [0.573, 0.617]   0.488 [0.436, 0.539]   0.482 [0.431, 0.535]
listpos            0.427 [0.406, 0.450]   0.339 [0.291, 0.389]   0.264 [0.218, 0.312]
Every cell is above its permutation null (p = 0.010), except some per-pool developer cells in code:
- difficulty, none/blinded: p = 0.069;
- mix, sham/blinded: p = 0.139;
- difficulty, sham/blinded: p = 0.208.

Table 1d. Beyond difficulty: paired per-session accuracy difference, same sessions [95% CI]
contrast                    all (n=1353)          none/blinded (176)    sham/blinded (175)
tfidf - difficulty          +0.417 [+0.393,+0.440] +0.349 [+0.281,+0.417] +0.313 [+0.251,+0.376]
tfidf - diffprof            +0.291 [+0.267,+0.314] +0.280 [+0.217,+0.343] +0.290 [+0.226,+0.354]
tfidf - listpos             +0.458 [+0.436,+0.481] +0.428 [+0.361,+0.494] +0.509 [+0.453,+0.565]
By pool, the tfidf - difficulty excess is positive in every pool and subset (smallest: math none +0.179
[+0.046, +0.314]).

Table 1e. Cross-arm transfer (transfer.py): train on one set, test on the 60 (math 55) sham/blinded sessions.
Exact binomial p vs 1/12.
                         tfidf                 items                 difficulty            listpos
none -> sham  factual    0.817 [0.733,0.900]   0.867                 0.550                 0.350
              math       0.564 [0.473,0.655]   0.691                 0.218                 0.218
              code       0.467 [0.383,0.550]   0.533                 0.167 (p=0.026)       0.133 (p=0.12)
rest -> sham  factual    0.917                 0.933                 0.667                 0.367
              math       0.873                 0.927                 0.618                 0.509
              code       0.900                 0.917                 0.333                 0.367
("rest" = every valid session except sham/blinded, including sham/true and sham/false.) Except where shown, the
tfidf and items p-values are below 1e-14.

Confusion (all sessions, tfidf, counts summed over 5 CV repeats; full matrices in results.json and
classifier_tables.txt)
- Per-designer recall: factual 0.89 to 1.00; math 0.65 (grok47) to 0.95; code 0.68 (grok43) to 0.98.
- Errors mostly fall within a developer: Anthropic with Anthropic, xAI with xAI. The one large cross-developer
  confusion is gemini31pro with grok43, in all pools:
  - factual: 16 and 15;
  - math: 16 and 30;
  - code: 33 and 42.
  These two designers choose the hardest benchmarks in factual (mean reference accuracy 0.50 and 0.52, against
  0.59 to 0.65 for the others).

Interpretation (limited to the data)
- Designer signatures exist in the produced artefact under blinded identities (sham/blinded 77%; none-arm-trained
  transfer 47 to 82%).
- They are much richer than difficulty or category quotas. They are about as well captured by which item ids were
  chosen as by their text. Because the text is fixed pool text, the classifier is identifying selection habits, not
  writing style. How deep a designer pages through the list explains part of it (listpos 26 to 43%), but not most.
- Benchmarks by the same designer are strongly correlated across sessions and arms. This supports treating the
  designer as the cluster unit, as the prereg does.
- This does not show that signatures favour the designer. Provenance is a property of the artefact, not of the
  panel ranking.
- Section 12 also ties provenance to the "pseudonymised" re-labelling rule. That rule is triggered by
  self-recognition, which is at chance (controls report), not by provenance.

======================================================================================================================
PART 2. KEPT vs VIEWED (Kaushik et al.)
======================================================================================================================
Exposure rule (exposure.py)
- Only two tools return item ids:
  - list_items: id, category, format and the first 150 characters of the question;
  - view_items: full question and key, for the first 8 requested ids that exist in the pool.
  pool_overview, draft_status, request_panel_scores, add/remove/edit/set_* and notes return no item ids.
- actions.jsonl truncates results to 400 characters and transcript.jsonl to 2,000, so every list_items page is
  recomputed from the call's arguments with the interface's exact logic:
  - ids in sorted order;
  - case-insensitive category filter;
  - case-insensitive substring query on the current question text, applying earlier successful edit_item edits;
  - offset clamped to at least 0, limit clamped to 1 to 30 (default 25).
- Check, which can fail: the logged prefix of every page must match the reconstruction and the logged total must
  match. It passed for all 35,958 non-error list_items calls (factual 14,904; math 10,062; code 10,992) and all
  23,404 view_items calls. Two list calls returned ERROR and exposed nothing.
- Definitions: exposed set V = listed ∪ viewed in full. Kept set = the 100 submitted ids. Replaying add_items and
  remove_items reproduces every final item list exactly (872/872 sessions in the analysed cells).
- Kept items are almost always in V. Kept items not in V totalled:
  - 0 to 2 per cell in most cells;
  - 24 in one factual true_blinded session;
  - 41 across 2 math none sessions;
  - 10 across 2 code none sessions.
  These designers added items by id without listing them.
- V is large: median 330 to 505 items per cell. Only 2 sessions had |V| <= 100 (whole set used). Items read in full
  (view_items) number a median of 90 to 172.

Metrics (kept_vs_viewed.py)
- For each benchmark: the kept set, 200 random 100-item draws from V, and 200 random 100-item draws from the whole
  pool.
- All sets are scored the same way: unweighted mean of reference per-(item, key) accuracy, i.e. unedited items
  without weights. Over sham/blinded benchmarks, the correlation of kept tau_disp with tau on the actual
  produced_scores is r = 0.99.
- Fixed 13-key set: 12 designer keys plus the placebo.
  - tau_disp: tau-b to the displayed order (sham: the registered order shown at the first view; true_blinded: the
    draft's true order at the first request).
  - tau_ref: tau-b to the full-pool reference.
  - difficulty: mean item reference accuracy over the 12 designer keys, in points.
  - tau_r1 (added overlap control): tau-b to the true order of the designer's own draft at the end of round 1,
    defined identically in every arm.
- Contrasts:
  - selection = kept - mean(random from V);
  - exposure = mean(random from V) - mean(random from pool);
  - total = selection + exposure.
- Aggregation: designer-averaged mean, with a 95% designer-cluster bootstrap (designers, then benchmarks within
  designer; 5,000 reps). Pooled = mean of the pool estimates, with a shared designer draw across pools.
- Arm-minus-none: per-designer mean difference, then the same bootstrap.

Table 2a. Display tracking (tau_disp), pooled [95% designer-cluster CI]
arm (n bench/designers)       kept                   selection              exposure               total
sham/blinded (175/12)         -0.002 [-0.035,+0.032] -0.004 [-0.016,+0.009] -0.006 [-0.013,+0.001] -0.010 [-0.024,+0.005]
true_blinded (173/12)         +0.835 [+0.799,+0.872] +0.060 [+0.040,+0.082] +0.048 [+0.034,+0.065] +0.108 [+0.083,+0.133]
none (176/12)                 n/a (no display)
Sham selection by pool: factual -0.002 [-0.024,+0.023] (60/12); math +0.001 [-0.018,+0.018] (55/12); code -0.011
[-0.034,+0.012] (60/12).
- Kept sets sit at the 48th percentile of the random-from-V draws (0.484 [0.428, 0.542]).
- Largest per-designer sham selection: gemini4argon factual, +0.086 (n = 5). This is the designer whose factual lead
  failed replication. All other designer x pool cells lie between -0.051 and +0.043.

Table 2b. Overlap control (tau_r1: tau to the designer's own round-1 draft order, which in none and sham was never
shown as a true order), pooled
arm                selection              exposure
none               +0.092 [+0.068,+0.115] +0.060 [+0.042,+0.081]
sham/blinded       +0.073 [+0.050,+0.096] +0.051 [+0.039,+0.064]
true_blinded       +0.071 [+0.052,+0.092] +0.047 [+0.033,+0.063]
true_blinded-none  -0.021 [-0.039,-0.005]
sham-none          -0.017 [-0.033,+0.002]
- The true_blinded +0.060 in Table 2a is no larger than what the none arm shows toward its own unshown round-1 draft
  (+0.092).
- So it is the shared-items artefact: the kept set overlaps the draft whose order was displayed. It is not evidence
  of steering toward the shown true order.
- Score-arm designers keep fewer of their round-1 items: median overlap with the round-1 draft is 53 (true_blinded)
  and 54 (sham), against 77.5 (none).

Table 2c. Reference tracking (tau_ref), pooled
arm             selection              exposure
sham/blinded    +0.006 [-0.009,+0.018] +0.022 [+0.017,+0.026]
true_blinded    +0.008 [-0.003,+0.018] +0.017 [+0.012,+0.022]
none            -0.011 [-0.030,+0.006] +0.021 [+0.016,+0.026]
sham-none       +0.017 [+0.003,+0.032]  (code +0.040 [+0.009,+0.076]; factual +0.007; math +0.004)
true_bl.-none   +0.019 [+0.005,+0.033]  (code +0.040 [+0.012,+0.071]; factual +0.005; math +0.011)

Table 2d. Difficulty (mean reference accuracy, points; negative = harder), [95% designer-cluster CI]
arm             pool      selection               exposure               total
sham/blinded    factual   +8.41 [+5.33,+11.07]    +0.24 [-0.26,+0.76]    +8.65
                math      -6.67 [-9.88,-3.67]     -6.89 [-8.18,-5.78]    -13.57
                code      -3.72 [-6.38,-1.46]     -2.71 [-3.37,-2.10]    -6.43
                pooled    -0.66 [-2.42,+0.95]     -3.12 [-3.63,-2.63]    -3.78 [-5.66,-1.86]
none            factual   +10.70 [+7.45,+13.59]   -0.19 [-0.60,+0.27]    +10.51
                math      -0.57 [-3.16,+1.80]     -6.04 [-7.20,-4.95]    -6.61
                code      -0.33 [-2.05,+1.63]     -2.33 [-2.74,-1.95]    -2.65
                pooled    +3.27 [+1.86,+4.79]     -2.85 [-3.30,-2.43]    +0.41 [-1.14,+2.04]
true_blinded    pooled    -0.66 [-2.89,+1.39]     -2.93 [-3.45,-2.45]    -3.59 [-6.04,-1.39]
sham-none       pooled    -3.93 [-5.18,-2.63]     -0.27 [-0.58,+0.02]    (factual -2.28, math -6.10, code -3.39 selection)
true_bl.-none   pooled    -3.93 [-5.64,-2.44]     -0.07 [-0.39,+0.22]    (factual -2.62, math -6.18, code -2.98 selection)

Interpretation (Part 2)
- Sham displays steer neither stage. The items a sham designer looks at are no closer to the display than random
  pool items, and among those items it keeps a set no closer than random. This repeats the primary null (Psi ≈ 0)
  at the process level, with tight CIs (about ±0.013 tau).
- Score access hardens benchmarks by about 3.9 points through what designers keep, not through where they look. The
  hardening is the same for sham and true scores, which matches the confirmatory "3.8 points harder".
- In every arm, designers browse harder parts of the math and code pools than the pool average (exposure -6 and
  -2.5 points). Which listing choices produce this was not analysed.
- In factual, designers in every arm keep items about 8 to 11 points easier than those they looked at.
  - Plausibly they drop obscure or ambiguous questions. That is unverified: notes were not coded.
- The small gain in reference tracking with score access (+0.02 tau, carried by code) is also a selection effect.
  This matches the confirmatory S4 code finding.

Caveats
- Kept vs random-from-viewed is descriptive, not causal: designers chose what to view.
- V is large (hundreds of items), so random-from-V and random-from-pool differ little on rank metrics.
- The list_items view shows only 150 characters. A stricter exposure set (items read in full via view_items) gives
  the same sham result: selection +0.005 [-0.012, +0.022], n = 155/12. But that set excludes 17 to 48 kept items per
  benchmark on average, so the comparison is not clean. It is stored in results.json as *selection_fullview.
- Classifier CIs cover test-sample uncertainty only. The permutation p is floored at 0.0099 by using 100
  permutations.
- Run note: the code-pool classifier was split into 4 processes (classify.py code 0-3, then merged), which briefly
  exceeded the 3-process guideline by 1. The parts use different RNG seeds than a single run would: seed 3+100*(part+1).

REPRODUCE (cwd = this directory; PYTHONPATH=/path/to/metabench/run;
python = /path/to/venv/bin/python; OPENBLAS_NUM_THREADS=1)
1. python exposure.py            -> exposure.jsonl, exposure_check.json                       (~1 min)
2. python kept_vs_viewed.py      -> kept_vs_viewed_sessions.jsonl, kept_vs_viewed_results.json (~3 min)
3. python classify.py factual ; python classify.py math                                        (~15 min each)
   python classify.py code 0 all tfidf ; ... code 1 all items ; ... code 2 '*' mix,difficulty,diffprof,listpos ;
   ... code 3 none_blinded,sham_blinded tfidf,items ; python classify.py code merge 4             (~12 min parallel)
4. python transfer.py            -> transfer_results.json
5. python assemble.py            -> results.json, classifier_tables.txt
