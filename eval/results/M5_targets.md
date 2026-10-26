# M5 — results against the §14 targets

Test set: the 25-invoice **synthetic-only** held-out set (20 originals + 5 seeded duplicates, 3 unknown vendors). The ~15 public-dataset invoices and ~10 phone photos are not in it yet, so these numbers say nothing about real-world documents.
Model `gemini-3.5-flash-lite`, confidence threshold 0.85.

| Metric (spec §14) | Target | Baseline (M3) — `20261026T184928Z` | After M5 — `20261026T195148Z` | Met? |
|---|---|---|---|---|
| Field-level extraction accuracy | ≥ 90% | 99.84% (header 100%) | **100%** (header 100%) | ✅ |
| Auto-approved with no human edits | ≥ 70% | 60% | **64%** | ❌ see note 1 |
| Wrong fields among auto-approved | ≤ 1% | 0.26% (1 field) | **0%** | ✅ |
| Seeded duplicates caught | 5 / 5 | 5 / 5, 0 false flags | **5 / 5**, 0 false flags | ✅ |
| Handling time, auto-approved invoice | < 1 min | 8.0 s | **4.4 s** | ✅ (machine time; no human step) |
| Handling time, reviewed invoice | < 2 min | — | **not measured** | ⏳ see note 2 |
| Extraction cost per invoice | report | $0.0016 → $3.20 / month at 2,000 | **$0.00164 → $3.28 / month at 2,000** | reported |

**Note 1 — why auto-approval misses 70%.** 8 of the 25 test invoices *must* go to review by design: 5 are seeded duplicates and 3 more come from vendors deliberately left out of the vendor list (one overlaps). So the highest possible auto-approval rate on this test set is 17/25 = **68%**, below the target. Of the 17 invoices that were allowed to auto-approve, **16 did (94%)**; the remaining one was held for low confidence. The target should be re-checked once the real-world samples are added and the share of "must review" documents is realistic.

**Note 2.** The < 2 minute review time has to be timed by a person using the Review invoice screen (M4 check, still open).

## What changed between the two runs (all tuned on `data/dev` only)

| Change | Why (dev evidence) |
|---|---|
| Prompt `extract_v2`: images are the source of truth, OCR is only a hint; check O/0, I/1, S/5 | v1 auto-approved a wrong invoice number (`INVO6061` for `INV06061`) because the model copied an OCR error that also "grounded" perfectly |
| Grounding compares dates and amounts with their printed forms | A garbled date was fuzzy-matched to an invoice number (score 0.61) |
| Currency `Rs,` (OCR comma) grounds as INR | One scan lost confidence only because of this |
| Blur threshold 100 → 40 (D6) | At 100 it flagged 4 scans that were read perfectly; real OCR failures were already caught by low confidence |
| Gemini retries 429 / 5xx using the suggested wait | The free tier allows 15 requests/min; one dev run lost an invoice to a rate limit |

Dev set (60 invoices, half scanned, ~10% unknown vendors): v1 → v2 field accuracy 99.94% → 100%, auto-approval 75% → 83%, wrong fields in auto-approved 0.09% → 0%.

## Threshold sweep (test set, after M5)

| Threshold | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 | 0.90 | 0.95 |
|---|---|---|---|---|---|---|---|---|
| Auto-approved | 64% | 64% | 64% | 64% | 64% | 64% | 60% | 56% |
| Wrong-field rate in auto-approved | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0% |

0.85 stays the default: lower thresholds approve nothing extra on these sets, higher ones only send more invoices to people. The sweep re-routes stored results without new LLM calls (duplicate links are taken as they happened).
