# Benchmark results — 2026-10-10, gpt-4o

- **Model under test:** `gpt-4o` · **judge:** `gpt-4o-mini`
- **Commit:** `421622f` (branch `1.0`) — per module: reasoning `d00f477`, querying `d00f477`, extraction `421622f` · **Python** 3.10.12 · **openai** 3.28.0
- **Cases:** 31 (22 reasoning, 5 querying, 4 extraction), one sample each
- **Cassettes:** recorded locally, not committed (about 29 MB; see `lib/README.md` and #150). Re-run with the commands in `run.json`.
- **Baseline:** [`../../baseline.json`](../../baseline.json) was built from this run.

One sample per case: treat a single case moving as noise, and a whole group moving as a signal. How these map to the product claims in #131, and what is not measured yet, is at the end.

## Quality-metric decisions

Each case declares whether the metric should pass its threshold (`expect_pass`); the score is the metric's own reading.

| Metric | Case | Score | Decision | Expected | Right |
|---|---|---:|---|---|:---:|
| completeness | `completeness_empty` | 0.00 | fail | fail | ✓ |
| completeness | `completeness_rich_profile` | 0.80 | pass | pass | ✓ |
| completeness | `completeness_sparse_profile` | 0.20 | fail | fail | ✓ |
| freshness | `freshness_empty` | 0.00 | fail | fail | ✓ |
| freshness | `freshness_mixed_nodes` | 1.00 | pass | — | — |
| freshness | `freshness_moderate` | 0.75 | pass | pass | ✓ |
| freshness | `freshness_recent` | 1.00 | pass | pass | ✓ |
| freshness | `freshness_stale` | 0.11 | fail | fail | ✓ |
| privacy | `privacy_minimal_consent_detailed` | 0.20 | fail | fail | ✓ |
| privacy | `privacy_no_restrictions` | 0.90 | pass | pass | ✓ |
| privacy | `privacy_public_sharing` | 1.00 | pass | pass | ✓ |
| privacy | `privacy_sensitive_exposure` | 0.00 | fail | fail | ✓ |
| privacy | `privacy_sensitive_safe_results` | 1.00 | pass | pass | ✓ |

- **completeness:** 3/3 decisions right
- **freshness:** 4/4 decisions right
- **privacy:** 5/5 decisions right

## Query rewriting, expansion and question phrasing

Scored 0–1 by the judge model.

| Type | Case | Score | Coverage | Judge's reasoning |
|---|---|---:|---:|---|
| appropriateness | `appropriateness_email` | 0.90 | — | The question is appropriate for an email channel as it maintains a professional tone, is polite, and clearly s… |
| appropriateness | `appropriateness_stdio` | 0.50 | — | The length of the question is somewhat lengthy for a standard input/output (stdio) channel, where responses ar… |
| appropriateness | `appropriateness_webhook` | 0.90 | — | The question is appropriate for a webhook delivery channel as it is self-contained and invites user engagement… |
| contextualization | `ctx_career_query` | 0.90 | — | The rewritten query 'jobs for benchmark-user' is more specific than the original 'jobs for me'. It indicates a… |
| contextualization | `ctx_location_query` | 0.90 | — | The rewritten query specifies 'benchmark-user's location,' which makes it more precise by directly referencing… |
| contextualization | `ctx_skills_query` | 0.80 | — | The rewritten query retains the core focus on 'skills' while adding context by specifying 'benchmark-user'. Th… |
| expansion | `exp_job_query` | 1.00 | 1.00 | All sub-questions are directly relevant to evaluating what kind of job would suit the user. They provide essen… |
| expansion | `exp_learning_query` | 0.80 | 0.75 | The sub-questions are generally relevant as they help to understand the user's background, skills, interests, … |
| expansion | `exp_relocation_query` | 0.40 | 0.20 | The sub-questions vary in relevance; while knowing the current residence location and nationality might provid… |

## Querying (addressing styles)

The same kind of question asked by name, in the second person, and as "the user"; hit rate = share of expected facts retrieved.

| Case | Style | Hit rate | Missed |
|---|---|---:|---|
| `career_by_user_pronoun` | third_person_user | 0.00 | Google, Stripe, staff engineer |
| `preferences_second_person` | second_person | 0.00 | remote, asynchronous |
| `skills_by_name` | by_name | 1.00 | — |
| `skills_second_person` | second_person | 0.00 | Python, TypeScript, SQL |
| `skills_third_person_user` | third_person_user | 1.00 | — |

## Extraction

Profile text stored with `store_data`, then asked about. Hit rate = share of expected values found across all checks (a question listing alternatives, e.g. "Alice Johnson" / "Alice", counts each one); a question counts as answered when at least one of its values is found.

| Case | Hit rate | Values found | Questions answered | Unanswered |
|---|---:|---:|---:|---|
| `basic_profile` | 0.86 | 6/7 | 4/4 | — |
| `contact_info` | 0.33 | 2/6 | 1/4 | What is the user's email address?; What is the user's LinkedIn profile?; How does the user prefer to be contacted for professional matters? |
| `multi_domain` | 0.60 | 6/10 | 3/6 | Where does the user live?; Where did the user work before their current job?; What is the user's current employer? |
| `skills_and_preferences` | 0.00 | 0/6 | 0/4 | What programming languages does the user know?; What is the user's area of expertise?; Does the user prefer remote work?; How does the user prefer to communicate? |

## Notes on this run

- 421622f differs from d00f477 only in the benchmark judge (an unparseable judge reply is retried instead of aborting the run); the extraction run at d00f477 died on that, so extraction was re-run at 421622f.
- Querying and extraction vary from run to run at the KB retrieval step. Every query was rewritten to the user's name correctly, but the KB query agent sometimes loops until it gives up and returns nothing: in querying, the three cases that scored 0.0 took 61-121 agent calls against 14-20 for the two that succeeded; in extraction, skills_and_preferences (0.0, all 4 answers empty) took 306 and multi_domain 269. skills_second_person scored 1.0 in a probe run of the same code minutes earlier, and the two runs also differed in how many extraction calls stored the seed text (16 vs 12). The query agent and the extractor are in blue-data-kb-source: megagon-internal/blue-data-kb-source#133.
- One sample per case. exp_relocation_query scored 1.0 in an earlier probe and 0.40 here.

## Against the product claims in #131

| Claim | Measured here as |
|---|---|
| Unauthorized disclosure rate | Privacy decisions above (proxy, 5 cases) |
| Stale-fact error rate | Freshness decisions above (proxy, 4 judged cases) |
| Task accuracy | Querying and extraction hit rates (proxy) |
| Channel appropriateness | Question phrasing per channel (3 cases); channel *selection* not measured |
| Clarification precision / recall, unnecessary interruption rate | Not measured yet — needs end-to-end cases (#150) |

