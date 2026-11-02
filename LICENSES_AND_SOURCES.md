# Licences and sources

This package redistributes third-party benchmark items only where the source licence permits it. Every item in every
pool carries its `source`, `source_id`, `source_url` and `licence` fields. Items marked **PI decision** below are
choices the principal investigator has to make before publication. They are not settled.

## 1. Item pools

### 1.1 Factual QA: OpenAI SimpleQA (item text included)

| field | value |
|---|---|
| Source | `simple_qa_test_set.csv` from github.com/openai/simple-evals (published 2024-10-30; 4,326 items) |
| Canonical file | https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv |
| Licence | MIT (github.com/openai/simple-evals LICENSE; copyright OpenAI) |
| Used | 2,000 items, ids F0001-F2000; `source_id` = 0-based row index in the canonical CSV |
| In this package | full item text and keys in `data/confirmatory/factual/pool/pool.jsonl`; item text also appears in sessions, transcripts and monitor files |
| Attribution | Wei et al., "Measuring short-form factuality in large language models", arXiv:2411.04368 (2024) |
| Build code | `code/run/pools/factual_qa/scripts/`, provenance in `data/confirmatory/factual/pool/PROVENANCE.md` |

Each item's `verification.evidence.snippet` holds about 200 characters of text from the cited web page that matched
the key. Most cited pages are Wikipedia (CC BY-SA 4.0); the rest are under their publishers' own terms. Full page text
is not included. **PI decision (low risk):** whether these short verification snippets are acceptable as quotation,
or should be cut down to `url` + `page_sha256` + `matched`.

The MIT licence requires its notice to travel with copies. The copyright line below was checked against the upstream
LICENSE file (github.com/openai/simple-evals, "Copyright (c) 2024 OpenAI", MIT) on 2026-10-31:

> Copyright (c) 2024 OpenAI. Permission is hereby granted, free of charge, to any person obtaining a copy of this
> software and associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following
> conditions: The above copyright notice and this permission notice shall be included in all copies or substantial
> portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

### 1.2 Code: DeepMind code_contests (item text included; PI decision flagged)

| field | value |
|---|---|
| Source | `deepmind/code_contests` on Hugging Face (revision `main`, lastModified 2023-06-11) |
| Licence | CC BY 4.0 for the dataset (dataset card, read 2026-10-25). The card also states: Codeforces materials are sourced from codeforces.com; Description2Code materials (CodeChef, Codeforces, HackerEarth) are MIT; CodeNet materials (AtCoder, Aizu) are Apache 2.0 |
| Used | 2,000 items, ids C0001-C2000; problem statement, stored tests and one human reference solution per item |
| In this package | `data/confirmatory/code/pool/pool.jsonl.gz`; item text also appears in sessions and transcripts |
| Attribution | Li et al., "Competition-level code generation with AlphaCode", Science 378 (2022), arXiv:2203.07814; dataset by DeepMind, CC BY 4.0 |
| Build code | `code/run/pools/code/scripts/`, provenance in `data/confirmatory/code/pool/PROVENANCE.md` |

**PI decision:** the build marked each item `"CC-BY-4.0 (code_contests); problem text © the originating judge"`.
Redistributing the dataset under CC BY 4.0 with attribution is what the dataset card allows. The underlying problem
statements are still copyrighted by Codeforces, CodeChef, HackerEarth, AtCoder, Aizu or Google Code Jam, and the
card does not show that every judge granted a licence. The usual practice, and the one used here, is to rely on
DeepMind's CC BY 4.0 grant. The alternative is ids only, which loses the transcripts. Two human reference solutions
contain their authors' personal email addresses in header comments. They are left unmodified, as in the public
dataset.

### 1.3 Math (item text WITHHELD from this package)

| source | items | licence (as stated by the host) | why withheld |
|---|---|---|---|
| MathArena on Hugging Face: `aime_2023_I/II`, `aime_2024_I/II`, `aime_2025`, `aime_2026`, `hmmt_feb_2023`-`2026`, `hmmt_nov_2025`, `brumo_2025`, `cmimc_2025`, `smt_2025`, `apex_2025` | 373 | CC BY-NC-SA 4.0 (dataset cards) | Redistribution is allowed only for non-commercial use, with attribution, and **ShareAlike**: any release containing this text would have to carry CC BY-NC-SA 4.0 for that part. The underlying problems are copyrighted by the MAA (AIME), HMMT, BRUMO, CMIMC and SMT organisers. |
| `gneubig/aime-1983-2024` on Hugging Face (AIME 1983-2022 here) | 832 | CC0-1.0 (dataset card) | The card says CC0, but AIME problems are copyrighted by the Mathematical Association of America. It is not clear the uploader could waive those rights. |
| Hendrycks MATH, test split, Level 5 (`qwedsacf/competition_math`, `EleutherAI/hendrycks_math`) | 795 | MIT (github.com/hendrycks/math) | The problems come from AoPS sources. AoPS filed a DMCA claim against Hugging Face copies of MATH in 2024, and the original HF repo is disabled. The pool's own provenance (`code/run/pools/math/PROVENANCE.md`, "Rehosting note") says MATH item text should be referenced, not rehosted. |

What the package contains for math:

- `data/confirmatory/math/pool/pool_index.jsonl`: every item's id, source, source_id, source_url, licence,
  source_date, category, key type, answer key, strata, verification record and `question_sha256`. A rebuilt pool can
  be checked against these. Answer keys are short numbers or expressions. They are kept because they are facts, not
  expressive text. **PI decision (low risk):** keep or drop the keys.
- The build scripts (`code/run/pools/math/scripts/`) that reproduce the pool from the public sources, and the
  provenance file. `hmmt_pdf_answers.json` and `other_pdf_answers.json` are build caches holding question text, and
  are left out.
- Math transcripts, actions, benchmark files, monitor outputs, panel answers and exploratory files are included with
  pool item text replaced by `[math item text withheld]`. SCRUB_REPORT.md section 3 gives the method and counts.
  Designer reasoning, tool calls, item ids, scores, keys and everything else are unchanged.

**PI decision:** the unredacted (but infrastructure-scrubbed) versions of every file the math redaction changed are
kept outside this package, in `../HOLD_math_item_text/`, with the same relative paths. Seth can add them back for
any subset whose licence he accepts. For example, the MathArena items under a CC BY-NC-SA 4.0 notice for that part,
if the release is non-commercial. The sessions archive in that folder mixes all three sources, so adding back only
some sources would mean a per-source redaction pass, which has not been done.

Attribution for the math sources:

- MathArena: Balunović et al., "MathArena: Evaluating LLMs on Uncontaminated Math Competitions" (2025),
  https://matharena.ai, datasets at https://huggingface.co/MathArena (CC BY-NC-SA 4.0).
- AIME problems: Mathematical Association of America; compiled at https://huggingface.co/datasets/gneubig/aime-1983-2024.
- MATH: Hendrycks et al., "Measuring Mathematical Problem Solving With the MATH Dataset", NeurIPS 2021, arXiv:2103.03874.

### 1.4 Held-out clinical-medicine pool (not used; not included)

MedQA (USMLE, 4-option; `GBaker/MedQA-USMLE-4-options`, CC BY 4.0 on the card; original release MIT, Jin et al. 2020).
It was built as a held-out replication domain and no confirmatory session used it. Only its build script and
provenance are included (`code/run/pools/heldout_clinical_medicine/`).

### 1.5 Pilot pool (not included)

The exploratory pilot used 1,300 MMLU-Pro items. Pilot data are not part of this release. Only their registration
hashes are included (`protocol/prereg/pilot_hashes.json`).

## 2. Model outputs

The transcripts, panel answers, monitor ratings and probe answers were generated by models from Anthropic, OpenAI,
Google and xAI, called on the project's own API accounts. The exploratory `exp_muse` experiment and the edit-audit
adjudicator also used Meta "Muse" models through an OpenAI-compatible inference provider. **PI decision:** confirm
that publishing these outputs is consistent with each vendor's terms in force for the accounts used. The usual
position is that outputs belong to the customer, but `exp_muse` used a "contributor" tier whose terms were not checked
here.

## 3. This package's own code and data

- **Code** (`code/`, the scripts at the top level): MIT. See `LICENSE`.
- **Data and reports** generated by this project (`data/`, `reports/`, `protocol/`): CC BY 4.0. See `LICENSE-DATA`.
- **Third-party item text** keeps its own licence: SimpleQA items MIT (Copyright (c) 2024 OpenAI), code_contests items
  CC BY 4.0 (DeepMind; the original problem statements remain copyright their contest platforms).
- **Maths item text** is withheld; the maths pool is distributed as ids, sources, keys and hashes.
- **Model outputs** (designer transcripts, panel answers, monitor and judge outputs) are included as research data.
