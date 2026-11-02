# Confirmatory-run artefact schema

Contract between the runner (`scripts_runner.py`), the synthetic generator (`metabench/synthetic.py`), the blinded
health view (`scripts_health_view.py`) and the two independent analysis implementations. The runner writes every
file below into a tmpfs working directory `WORK/` and seals it file-by-file into `run/sealed/` (section 6). The
synthetic generator writes the same tree, unsealed, into a directory of the analysis author's choosing.

Panel keys follow `metabench/panel.py` with `set_active("confirmatory")`: 12 displayed designer keys
(`DISPLAYED_KEYS`), one placebo (`PLACEBO_KEYS = ["placebo_sonnet55"]`, displayed only under pseudonyms) and four
held-out keys (`HELDOUT_KEYS`, never displayed). `panel_keys = DISPLAYED_KEYS + PLACEBO_KEYS + HELDOUT_KEYS` (17).

Session ids: `T1_{pool}_{designer}_{info_arm}_{identity_arm}_r{replicate}`; a replacement session (section 5)
appends `_rep1`. Information arms: `none`, `true_named`, `true_blinded`, `sham`, `inverted`, `narrative`,
`instructed`. Identity arms: `blinded`, `true`, `false`. Registered cells per designer (frozen_sizes.json):
sham/blinded 5, none/blinded 5, true_named/true 5, true_blinded/blinded 5, sham/true 5, sham/false 5,
inverted/blinded 3, narrative/blinded 3, instructed/blinded 3 (39 per designer, 468 for 12 designers).

## 1. `WORK/` layout

```
WORK/
  run_manifest.json                 run id, timestamps, frozen-code hash, registration hash, pool hash, cells, concurrency,
                                    live_rescore_wait_s (null = blocking live re-score; absent in manifests written before
                                    Builder 8, which all ran blocking),
                                    counts, api_errors_total, substitutes (smoke only) and `panel`, a dict
                                    {"name","keys","displayed_keys","placebo_keys","heldout_keys"} (the factual pool's sealed
                                    manifest, written before BUILD4, has `panel` as the plain list of the 17 keys instead)
  llm_calls.jsonl                   per-call log: tag, model id, token counts, cost, latency, stop reason (no content)
  precompute/<pool>.jsonl           per-item x per-model x per-sample correctness (panel.precompute output)
  reference_item_outcomes.jsonl     session_id == "REFERENCE": the full pool, every panel key (DIF anchor); an identical
                                    copy sits at results/reference_item_outcomes.jsonl (what metabench.analysis reads;
                                    the synthetic generator writes both since BUILD4)
  pool/<pool>.jsonl                 copy of the pool file (synthetic trees only; the real run hashes the pool instead)
  registration_full.json            {"registration": the plaintext registration payload (sessions, hashes, panel),
                                     "configs": {session_id: full SessionConfig (seeds, orders, offsets, leaders, targets,
                                     false_identity)}, "reference_scores", "coverage"}; replacement configs are added under
                                    "configs" by the synthetic generator only (the runner commits them to
                                    prereg/confirmatory_replacements_<pool>.json and sessions/<id>/config.json)
  sessions/<session_id>/
      config.json                   SessionConfig (arms.SessionConfig.to_json)
      actions.jsonl                 one row per interface tool call
      transcript.jsonl              one row per LLM turn / tool result / probe
      scores_views.jsonl            one row per request_panel_scores call (absent if never called)
      benchmark.json                the produced benchmark and endpoint inputs (section 2)
      item_outcomes.jsonl           per item x panel key correctness counts for the produced benchmark
      probes.json                   post-submission probe answers (absent if the session did not reach the probes)
  monitors/<session_id>.json        the two monitors' verdicts (section 3)
  results/
      benchmarks.jsonl              every benchmark.json as one line (including invalid / replaced sessions)
      item_outcomes.jsonl           concatenation of sessions/*/item_outcomes.jsonl
      monitors.jsonl                every monitors/<id>.json as one line
      session_log.jsonl             one row per session attempt (section 4)
  health/
      health_view.jsonl             the blinded view (written in plaintext to run/health/ as well)
      health_secret.json            permutations, offsets, decoy ids (sealed only)
  endpoints/<impl>/...              output of each frozen analysis implementation, when present, plus log.txt (rc, stdout,
                                    stderr).  Invocation (scripts_runner.py run_analyses): `metabench.analysis --results
                                    WORK/results`, `analysis_impls/<impl>/run.py --results WORK` (the WORK root), both with
                                    `--out WORK/endpoints/<impl> --n-perm N --n-boot N`, cwd = run/, inherited environment,
                                    `--analysis-timeout` seconds and an RLIMIT_AS of `--analysis-memory-mib` per process
```

## 2. `benchmark.json` (one object; `results/benchmarks.jsonl` has one per line)

| field | type | meaning |
|---|---|---|
| `session_id` | str | as above |
| `designer` | str | panel key of the designer (one of `DISPLAYED_KEYS`) |
| `info_arm`, `identity_arm` | str | arm labels |
| `tier` | str | `"T1"` |
| `replicate` | int | 0-based replicate index within the (designer, info_arm, identity_arm) cell |
| `seed` | int | session seed (first 8 hex digits of SHA-256(master\|designer\|arm\|identity\|replicate[\|rep1])) |
| `pool_name` | str | `math`, `code`, `factual` (pilot: `pilot`) |
| `status` | str | `ok`, `refusal`, `llm_call_budget`, `exception:<Type>` |
| `valid` | bool | `status == "ok"` and submitted with exactly `n_items_required` items |
| `n_items` | int | items in the draft at the end |
| `items` | list[str] | item ids in the produced benchmark (order of addition) |
| `weights` | dict[str,float] | item weights, non-empty only when `scoring_rule == "weighted_accuracy"` |
| `scoring_rule` | str | `accuracy` or `weighted_accuracy` |
| `edited_items` | dict[str,obj] | item id -> edited item dict (question, options, answer, category, ...) |
| `named` | bool | real model names on the scoreboard (true_named, or sham/inverted/narrative under true/false identity) |
| `displayed_keys` | list[str] | panel keys that could appear in the scores view (12, or 13 with the placebo under pseudonyms) |
| `panel_keys` | list[str] | every key with a produced score (`displayed_keys` + placebo + held-out = 17) |
| `label_map` | dict[str,str] | panel key -> label shown (real name or `MDL-NN`) |
| `displayed_order` | list[str] or null | order shown at the FIRST numeric scores request (best first). Sham/inverted: equal to the registered order σ (the interface fixes the offsets at the first view so that the view shows the reference vector permuted to σ; PREREGISTRATION §4, DEVIATIONS 05:17); if the session never requested scores it is the registered order. True arms: the draft's true order at the first request, null if never requested. None/narrative: null |
| `intended_displayed_order` | list[str] or null | the registered sham/inverted order (null for other arms) |
| `displayed_leader` | str or null | sham/inverted: `displayed_order[0]`; narrative: the narrated leader; true arms: reference top; instructed: the target |
| `target_model` | str or null | instructed arm only |
| `offsets_applied` | dict[str,float] or null | sham/inverted: the per-model offsets fixed at the first numeric view (shown = clip(true + offset)); null otherwise |
| `n_score_requests`, `n_edits` | int | counts |
| `produced_scores` | dict[str,float] | panel key -> (weighted) mean accuracy on the produced benchmark, all 17 keys |
| `reference_scores` | dict[str,float] | panel key -> mean accuracy on the full pool, all 17 keys |
| `notes` | list[str] | `write_notes` / `end_round` texts with `[round r]` prefixes |
| `final_notes`, `presentation_note` | str | |
| `monitor_developers` | list[str] | the two monitor developers for this session |
| `config_hash` | str | SHA-256 commitment registered in `prereg/confirmatory_hashes.json` |
| `n_llm_calls` | int | designer LLM turns |
| `designer_model_id`, `designer_effort` | str | provider id and reasoning setting |
| `est_cost_usd`, `wall_s` | float | |
| `api_errors` | int | retried API errors during the session |
| `started_at`, `ended_at` | str | ISO-8601 UTC |
| `replacement_of` | str or null | original session id when this row is the one-time replacement |

## 3. Other per-session files

`actions.jsonl`: `{"session_id","round","t","tool","args","result_summary"}` (`t` = unix time; `result_summary` first 400 chars).

`transcript.jsonl`: `{"t","round","kind","payload"}` with `kind` in `system`, `user`, `assistant`
(`payload = {"text","tool_calls":[{"name","args"}],"in","out","stop"}`), `tool_result` (`{"name","result"}`),
`probe` (`{"key","answer"}`), `exception`.

`scores_views.jsonl`: `{"kind","round","n_items","t","true_all",...}`; for numeric views also `"order"` (best first),
`"shown"` (label-side scores incl. offsets) and `"true"`, and for sham/inverted `"offsets_applied"`; narrative views carry `"leader"`.

Pending marker (bounded live re-score only, i.e. a pool registered with `live_rescore_wait_s` = W, section 8): a view
in which some panel key's value was still waiting on the live re-score of an edited item in the draft carries
`"pending": [panel keys]` (in `panel_keys` order). For sham/inverted this includes displayed keys whose offset is
fixed by the first numeric view's value that had not returned yet. In numeric views every displayed key in `pending`
was rendered to the designer as the line `<label> | pending` (after the numeric lines, ordered by label, followed by
one explanatory line; identical in every numeric arm) and is absent from `"order"` and `"shown"`, which record exactly
what was shown. `"true"`, `"true_all"` and `"offsets_applied"` are filled in after the session's live calls are
drained (the file is rewritten once, before it is sealed), so they hold the draft's true scores at that view for every
key, as in blocking runs. The key is absent when nothing was pending, and never present in blocking runs.

`item_outcomes.jsonl`: `{"session_id","item_id","model_key","n_correct","n_samples"}` for every item in the produced
benchmark and every panel key (edited items use the live re-score; a panel key whose live samples all failed after the
client's retries falls back to the precomputed counts of the unedited item, in both live re-score modes).

`probes.json`: `{"recall","fairness","self_recognition","eval_awareness"}` (self_recognition absent in named sessions).

`monitors/<session_id>.json`: `{"session_id","monitor_developers":[..2..],"n_actions","monitors":[{"developer","monitor_model","status","artifact":{"evidence_score","favoured_label","disfavoured_label","rationale"},"trace":{"evidence_score","favoured_label","disfavoured_label","steering_actions","rationale"}}, ...]}`.

## 4. `results/session_log.jsonl` (one row per attempt, what stdout also prints)

`{"session_id","designer","info_arm","identity_arm","attempt":1|2,"replacement_of","status","valid","n_items","api_errors","n_llm_calls","wall_s","started_at","ended_at","exit_code"}` where `exit_code` is 0 for a valid session, 1 invalid, 2 exception.

## 5. Replacement rule

An invalid session (`valid == false`) is replaced exactly once: a new session with id `<id>_rep1`, seed from the same
generator with the suffix `rep1`, config drawn from that seed (new labels, sham order, target, false identity), run
after the registered list finishes. Replacement configs are committed in `prereg/confirmatory_replacements.json`
(plaintext: ids, config_hash, reason category) and kept in full in `WORK/registration_full.json`. Both the invalid
original and the replacement appear in `results/benchmarks.jsonl`; analyses use `valid` rows only.

## 6. Sealing

Every file under `WORK/` is encrypted separately to the fingerprint in `prereg/sealing_key.json`
(`GNUPGHOME=run/sealing/gnupg`, `gpg --encrypt --recipient <fpr>`), written as `run/sealed/<relative path>.gpg`.
`run/sealed/MANIFEST.json` (plaintext) lists each sealed file's relative path, ciphertext SHA-256 and plaintext byte
length; `run/sealed/MANIFEST.sha256` is its hash. `run/health/health_view.jsonl` is the only plaintext derived from
session content (section 7). The tmpfs working directory is removed on normal exit.

## 7. Blinded health view (`health/health_view.jsonl`)

One row per real session attempt plus decoys, in shuffled order:

`{"view_id":"HV-0001","designer_code":"D07","arm_code":"A4","identity_code":"I2","status","valid","exit_code","n_items","n_llm_calls","api_errors","wall_s","started_at","ended_at","n_score_requests","n_edits","files":{"config":true,"actions":true,"transcript":true,"scores_views":true|false,"benchmark":true,"item_outcomes":true,"probes":true|false,"monitors":2},"parse":{"actions_ok_rate":0.98,"monitor_json_rate":1.0,"item_outcomes_rows":1700},"hash_ok":true,"code_hash_ok":true,"scores_shifted":{"E01":0.61,...,"E17":0.44}}`

- `designer_code`: designers permuted by a secret per-run permutation (`D01..D12`).
- `arm_code` / `identity_code`: the 9 registered (info_arm, identity_arm) cells permuted by a second secret
  permutation (`A1..A9` with matching identity codes `I1..I3`), so cell counts are checkable but not nameable.
- `scores_shifted`: `produced_scores` keyed by permuted evaluee codes `E01..E17`, each shifted by a hidden per-evaluee
  offset drawn once per run (uniform on [-0.25, 0.25]); not clipped.
- Decoys: a fixed number per designer code (3; 36 in all, 4 per arm cell) replayed from pilot session structure with
  scores drawn around the run's reference scores; indistinguishable in schema; their ids are in `health_secret.json`.
- `hash_ok`: the session's config hash matched its registered commitment (checked by the runner, reported as a flag).
- `code_hash_ok`: `prereg/frozen_code.json` matched the running code at session start.

The checker (`scripts_health_check.py`) reports only: schema validity, parse rates, validity flags, API failures,
hash flags, time-of-day interleaving across arm codes, and per-designer-code session counts against the registered
number plus decoys.

## 8. Live re-score of edited items (`live_rescore_wait_s`)

`edit_item` re-runs the edited item on all 17 panel keys (3 samples each, `metabench.designer.make_live_scorer`, the
client's usual retry bounds). The mode is part of a pool's registration: `prereg/confirmatory_hashes_<pool>.json`
carries `"live_rescore_wait_s"` (null or absent = blocking: the tool call returns when every panel call has returned;
the factual and math pools), the run manifest repeats it, and `scripts_runner.py run` refuses if
`--live-rescore-wait-s` differs from the registered value (re-registering with a different value needs `--force`).

With a registered W (seconds), `edit_item` waits at most W; panel keys that have not returned are pending (section 3)
and keep running in the background, each filling in when it returns. A later edit of the same item supersedes an
earlier one exactly as in blocking mode (a late answer for an older wording is kept only for views computed on that
wording). Every numeric value shown is the value an unbounded wait would have shown. When the designer conversation
(including probes) ends the session frees its concurrency slot; the runner then waits until every outstanding live
call of the session has returned or exhausted its retries, and only then writes `benchmark.json`, `item_outcomes.jsonl`
and the final `scores_views.jsonl`, runs the monitors and seals the session; `finish()` runs after all sessions are
drained. `benchmark.json` is unchanged in schema; `displayed_order` is the full order of the first numeric view
evaluated with its returned values (for sham/inverted: σ, as in blocking runs); `wall_s` is the designer's session time
(excluding the drain), `ended_at` is after the drain.
