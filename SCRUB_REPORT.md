# Scrub report

Every change made to the source files on the way into this package is listed here. Apart from these rules, no data
value (scores, item ids, keys, model outputs, designer text) was altered. The original files stay with the PI.

## 1. Files left out

| left out | reason |
|---|---|
| Coordinator log, role/thread ledgers and prompts, `RUN_*`, `BUILD*_PROGRESS`/`BUILD*_REPORT`, `ops_*.sh`, `health/`, `logs/`, `*.log` | operational records |
| `sealed/` (encrypted artefacts), `sealing/` keyring | encrypted copies of the data shipped here in plaintext. Only the public-key fingerprint is published, in `protocol/prereg/sealing_key.json`. No private key exists. |
| `.env*`, `*.local*`, `.venv`, `__pycache__`, `pools/_work/` (download caches, fetched web pages) | secrets, environments, caches |
| pilot sessions/results, smoke runs, bot sessions, rebuild sessions, `human_audit/`, `power/` working files | outside the confirmatory and listed exploratory analyses |
| `analysis/blog_review/`, `docs/BLOG_DRAFT_*` | review of an unpublished draft |
| `analysis/CONTEXT.md` | brief for the analysis agents (operational). The data-layout content is in `data/ARTEFACT_SCHEMA.md` |
| `exp_muse/sessions_smoke/`, `rows_smoke.jsonl`, `rows_interim_121.jsonl` | smoke and interim snapshots, superseded by `rows.jsonl` |
| math `pool.jsonl`, `hmmt_pdf_answers.json`, `other_pdf_answers.json` | licence (LICENSES_AND_SOURCES.md 1.3); kept in `../HOLD_math_item_text/` |
| held-out MedQA `pool.jsonl` | never used by any session |
| duplicate `WORK_<pool>/reference_item_outcomes.jsonl` | byte-identical to `results/reference_item_outcomes.jsonl`. `restore_layout.py` recreates it |

## 2. Infrastructure scrub rules

Regex replacements on every text file, applied in this order before compression. Counts are replacements made.

| rule | what | replacement | count |
|---|---|---|---|
| R01 | path of the API-key env file (the file itself was never read or copied) | `/path/to/model-keys.env` | 8 |
| R02 | run virtualenv path (mostly in Python tracebacks inside code-pool grading errors) | `/path/to/venv` | 364 |
| R03 | project root path on the run machine | `/path/to/metabench` | 1,074 |
| R04, R05 | any other path under the run machine's home directory | `/path/to/...` | 0 |
| R06 | tmpfs scratch paths (under the Linux shared-memory mount) in docs and data | `/path/to/scratch` | 3 |
| R07 | paths under a top-level `project` mount | `/path/to/project-dir` | 0 |
| R08 | base URL of the OpenAI-compatible inference provider used for the Meta Muse models | `https://<openai-compatible-provider>/v1` | 4 |
| R09, R10 | that provider's host name and company name | `<openai-compatible-provider>` | 5 |
| R11 | Google Cloud project id (Vertex AI) | `<gcp-project-id>` | 3 |
| R12, R13 | links to and the name of the internal development platform | `<internal link removed>` / `<dev platform>` | 1 |
| R14 | internal CLI tool names | `<internal tool>` | 0 |
| R15, R16 | the dev platform's product word for a cloud dev machine (lower- and upper-case) | `machine` | 4 |
| R17 | process ids in prose (6-8 digit numbers within 45 characters after PID/wrapper/chunk/runner/timeout/python wording; `.md`/`.txt` only) | `<pid>` | 7 |
| R18 | PI laptop path of the unblinded output directory (endpoint logs and JSON, confirmatory report) | `/path/to/unblinded` | 27 |
| R19 | PI laptop path of the run virtualenv | `/path/to/venv` | 8 |
| R20 | PI laptop path of the run directory | `/path/to/metabench/run` | 3 |
| R21 | PI laptop home directory | `/path/to/home` | 0 |

1,435 files changed in total (1,415 in the first pass, 20 for R18-R20). All rule counts are summed over the whole
package. R18-R21 were added after the first full leak scan found the laptop paths.

Effect on the frozen code. One file covered by `protocol/prereg/frozen_code.json` changed:
`code/run/metabench/llm.py`, in three lines. These are a docstring path (R01), the default `path` argument of
`load_keys_from_env_file` (R01) and the `VERTEX_PROJECT` constant (R11). Its SHA-256 therefore no longer matches the
frozen hash, so `scripts_freeze.py verify` reports a mismatch for that file. Every other frozen file matches, including
`pools/code/pool.jsonl`, `pools/factual_qa/pool.jsonl` and the `prereg/` files once `restore_layout.py` has put them
in place. The math and held-out pool files are not shipped.

Placeholders in code. Scripts refer to `/path/to/metabench/...`. `restore_layout.py --root DIR` rewrites that
placeholder to `DIR` in the restored copies. Two functional defaults are left unchanged: the Linux shared-memory mount
as the runner's scratch directory, and a `w` scratch directory under the system temp dir inside the code sandbox. Both
are generic Linux paths.

Kept on purpose:

- Model names, vendor names and public dataset names.
- The PI's first name ("Seth"), in protocol documents and reports, 29 lines.
- The organisation name "ORO", in 3 lines saying which organisation's API keys were used.
- The words "box"/"run box" for the machine.
- Vertex AI / `aiplatform.googleapis.com` and the `api.x.ai` and `generativelanguage.googleapis.com` endpoints in code. These are public vendor endpoints.

## 3. Licence redaction of math item text

Math item text is withheld (LICENSES_AND_SOURCES.md 1.3). In every file under `data/` that concerns the math pool
(path contains `math`, or an exploratory file that mixes pools), pool question text is replaced by
`[math item text withheld]`. JSON files are parsed and only string values are edited. Keys, ids and structure are
untouched. Methods, in order:

| method | what it matches | count |
|---|---|---|
| M1 | `list_items` result lines (`M0018 \| HMMT \| integer \| <preview>`): the preview after the third bar | 148,946 lines |
| M2 | `view_items` result blocks: text between `[Mxxxx] ...\nQ: ` and `\nAnswer key:` | 52,679 blocks |
| M3 | any run of 10 or more consecutive whitespace tokens that matches a math pool question (lower-cased, edge punctuation stripped; shingles with fewer than 5 alphabetic tokens ignored). This catches edited items, designer quotes, monitor rationales and rater sheets | 11,402 spans |
| M4 | any 40-character verbatim substring of a math pool question with 15 or more letters. Applied to the 149 files that still failed the residual check after M1-M3 (LaTeX-dense text has few whitespace tokens) | 4,983 spans |

1,174 files were changed by M1-M3 and 149 by M4. The unredacted, infrastructure-scrubbed version of each is in
`../HOLD_math_item_text/` at the same relative path.

Where the redaction landed: confirmatory math (1,024 files), `exp_muse` (93), `exp_covert` (50), `edit_audit` (6
files, 7,421 M3 spans: its rater sheets show before/after item text, so the math rows there are mostly placeholders
now) and `controls` (1).

Checks:

- False positives. The M3 rule was run in dry mode over all confirmatory factual and code files (7,931 files). It
  matched 8 spans in total, all generic phrases such as "the absolute value of the difference between the". An
  8-token version matched 213 spans and was rejected.
- Residual check. A rule that can fail: the build ran ripgrep over the whole package with every 50-character window
  (stride 25) of every math pool question, in raw and JSON-escaped forms (20,379 patterns). It found 151 files before
  M4 and **0 after**.
- Not covered. A designer's paraphrase, or a heavy rewrite of an item through `edit_item`, that shares fewer than 10
  consecutive words and no 40-character run with the original stays in the files. Answer keys are not redacted.

## 4. Leak scan

`scan_release.py` scans every file and every member of every `.tar.gz`/`.gz` as raw bytes. It looks for:

- API-key shapes: OpenAI/Anthropic, xAI, Google API keys, AWS access-key ids, GitHub and Slack tokens, Bearer tokens, PEM/PGP private-key blocks, AWS secret-key assignments.
- Paths: Linux and macOS home directories, the root home, the shared-memory mount, a top-level `project` mount, and the system temp dir.
- AWS identifiers: ARNs, S3 URIs, S3 bucket host names, 12-digit numbers near "account" or an ECR registry host.
- Email addresses, GCP-style project ids and IPv4 addresses.

`--extra-patterns` adds organisation-specific names (the inference provider, the dev platform and its CLI tools, the
GCP project prefix, the platform's word for a dev machine, the PI's surname). That list is kept outside the package, so the published scanner
does not itself disclose them. The scanner exits 1 on any hit not covered by `scan_allowlist.json`. Allowlist entries
store a SHA-256 of the excused string, a path regex and a reason, so the allowlist contains none of the strings it
excuses.

Final result on this package: 28,231 files and archive members, 1,282 MB uncompressed. **0 unresolved hits.**
1,738 allowlisted hits from 203 entries, all reviewed:

| pattern | hits | what they are |
|---|---|---|
| ipv4 | 1,068 (161 distinct) | dotted quads inside code_contests problems and their test data (IP-address problems), version numbers in SimpleQA cited URLs (a game wiki's four-part version pages), model outputs about those items, and Cloudflare's public resolver address in sandbox network-block tests |
| s3_bucket_host | 595 | public buckets cited by public sources: the HMMT archive bucket (official HMMT solution PDFs in the math provenance and key-verification evidence) and two buckets in SimpleQA cited URLs |
| gcp_project_id | 46 (24 distinct) | URL slugs in SimpleQA cited URLs (news-article slugs ending in a 6-digit article number) that have the word-word-6-digit shape |
| email | 8 | a placeholder User-Agent contact at a `.invalid` domain, an `example.com` test fixture, a Python `atexit.register` decorator, and two personal addresses in header comments of public code_contests reference solutions (dataset content, unmodified; see LICENSES_AND_SOURCES.md 1.2) |
| aws_access_key | 3 | one AWS temporary access-key ID inside a presigned S3 URL that the public SimpleQA CSV cites for one item (`X-Amz-Expires=300`, signed 2024-06-30). Third-party and long expired, carried unmodified from the dataset into the factual pool row, one benchmark row and one session file. **Flag:** public secret scanners such as GitHub's may still alert on it. To avoid that, strip the query string from that one cited URL (a data change to a citation, not to the item) |
| home_path | 3 | home-directory-shaped paths inside public dataset content: a path in one code_contests reference solution and two SimpleQA cited URLs |
| tmp_path | 13 | the sandbox-internal scratch dir (code pool sandbox and its provenance), test scratch files, an example cache path in a README |
| dev_shm_path | 2 | the two functional runner defaults noted above |

Positive control: a scratch directory with a synthetic OpenAI-style key, a home path and an S3 URI in a text file,
the provider host inside a `.tar.gz` member, and an address inside a `.gz` file. The scanner reported all 5 and
exited 1. Context snippets mask credential-shaped strings even when they sit next to another hit.

Reproduce: `python scan_release.py .` (generic patterns plus allowlist). The PI can add the private name list with
`--extra-patterns FILE`.


## Late changes (2026-10-31, after PI review)

- **Presigned URL query strings removed.** One SimpleQA item cites an expired, presigned S3 URL whose query string
  contains a temporary AWS access-key id. The query string was stripped, keeping the base URL, in 3 places:
  `data/confirmatory/factual/pool/pool.jsonl`, `data/confirmatory/factual/results/benchmarks.jsonl`, and one
  `benchmark.json` inside `data/confirmatory/factual/sessions.tar.gz`. The matching allowlist entry was removed.
- **Write-up dropped.** `reports/WRITEUP_2026-10-31.md` (an internal document) is no longer included. The analysis notes
  and the confirmatory report remain.
- **Licences set.** Code MIT (`LICENSE`); generated data and reports CC BY 4.0 (`LICENSE-DATA`).
