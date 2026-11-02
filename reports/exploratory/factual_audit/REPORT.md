# Factual pool (SimpleQA subset) quality audit (EXPLORATORY, 2026-10-30)

Script: audit.py. Judgements: judgements.jsonl. Two independent LLM judges, gpt-5.5 (OpenAI) and claude-opus-5-5
(Anthropic), applied the same rubric. 1,384 judgements in total; 17 parse errors (12 of them in Anthropic's part-B
labels).

## Pool
- 2,000 items sampled from OpenAI SimpleQA (2024): 4,326 short factual questions, each written and checked by two human
  trainers.
- Every key used here was re-verified against a cited source page (86% of SimpleQA passed that check). This confirms the
  key matches its source; it does not check ambiguity or how the grader behaves.
- Grader: deterministic. A normalised key must appear inside the answer, with date and number variants allowed. There is
  no LLM judge, unlike SimpleQA's official grader.

## A. Grader audit
| graded as | n | both judges say actually correct | both say incorrect | judges agree |
|---|---|---|---|---|
| mismatch (marked wrong) | 300 (25 per model) | 62 (21%) | 231 | 293/300 |
| correct | 100 | 100 | 0 | 100/100 |

**False positives:** none found.

**False negatives:** about 1 in 5 answers marked wrong are right. Typical misses:
- name variants: "Frank Spedding" for "Frank Harold Spedding"; "Richard Oram" for "Dick Oram";
- titles dropped: "Joe Tate" for "Rep. Joe Tate";
- accents and transliterations: "Mélanie", "Alexander";
- formats: 5/9/2005; "1984–1986"; "Third inning".

**The misses are uneven across models** (judged correct out of 25 sampled mismatches):

| model | judged correct |
|---|---|
| grok47 | 11 |
| gemini31pro | 9 |
| gpt61sol, gemini4argon, gemini38flash | 6 each |
| opus5, fable51, gpt55 | 5 each |
| grok43 | 4 |
| sonnet55, gpt6luna | 2 each |
| grok45 | 1 |

So the strict grader both understates accuracy (by roughly 10 points overall) and reorders models. Per-model
corrections from n = 25 are rough.

## B. Item audit (2-judge consensus)
| item set | n | SOUND (hard but fair) | GRADER_MISS (a model was actually right) | AMBIGUOUS | KEY_DOUBTFUL | judges disagree |
|---|---|---|---|---|---|---|
| missed by all 12 models | 192 | 74 | 77 | 5 | 5 | 31 |
| discriminating (random 100) | 100 | 45 | 35 | 1 | 3 | 16 |

- Genuine ambiguity or doubtful keys are rare: about 5% of the hardest items and about 4% of the others.
- **Hard but fair** examples:
  - the title of a specific sitcom episode;
  - a 2007 snow-globe world record holder;
  - an Indian politician's declared assets;
  - the previous location of a church organ.
- **Ambiguous** examples:
  - "NASA budget request in 2018": does that mean the FY2018 request, or the request made in 2018?
  - Canon EOS R50 "launch": the February announcement or the April release?
- **Doubtful key** examples:
  - Black Star Square: the event is usually dated 23 March, not the 24th given.
  - River Monsters: the key "40" comes from the episode's run time.
  - "Divorce" year: the source gives the separation year.

## Implications
- The factual pool is genuinely unsaturated: long-tail facts most models do not know, with few ambiguous or wrong keys.
  It is SimpleQA, an existing public benchmark, so this is not a new set.
- Its hardness is overstated by the strict grader. Model ranking in factual depends partly on answer style (full names,
  titles, formats), not only knowledge.
- **MetaBench conclusions are unaffected:** every arm and the displayed scores used the same grader, so Ψ compares like
  with like.
- **Fix for any reuse:** re-grade with an LLM judge (SimpleQA's official grader, or the two-judge rubric used here, which
  agreed 98%) and report the corrected per-model accuracies.
