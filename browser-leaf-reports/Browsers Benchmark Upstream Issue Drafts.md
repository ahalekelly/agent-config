---
created: 2026-07-31 00:24 PDT
verified: 2026-07-31
---

# Browsers Benchmark Upstream Issue Drafts

Target: [techinz/browsers-benchmark][repo]

## Issue 1

### Avoid false-positive bypasses by requiring positive success evidence

## Problem

The [runner][runner] ignores navigation success, while several checkers pass when one challenge selector is absent ([Cloudflare][cloudflare], [PerimeterX][perimeterx]). Failed, blank, or changed challenge pages can therefore pass.

The committed `patchright_headless` [results][results] mark Cloudflare and Priceline successful, but their screenshots show [“Verify you are human”][cf-shot] and [“Press & Hold”][px-shot] challenges.

## Proposed fix

Replace `BypassTestResult.bypass` and `.error` with one required verdict:

```python
Outcome = Literal["passed", "blocked", "inconclusive", "error"]

@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    evidence: str
```

Change `navigate()` to either return after a document loads or raise the original browser or transport error. Remove its inconsistent `success` flag. A loaded HTTP 4xx/5xx page still reaches the checker.

The runner maps a navigation exception to `error`. Otherwise the checker tests block markers, then positive application markers, then returns `inconclusive`. Block evidence wins.

Derive markers from saved success and challenge HTML fixtures. Store the matched selector or error as evidence. Reports count all outcomes and score `passed / attempted`.

## Acceptance criteria

- Blank, failed, or unfamiliar pages never pass.
- Navigation implementations raise failures; loaded HTTP error pages reach the checker.
- Every checker requires positive application evidence.
- Fixtures test success, challenge, unknown, and overlapping evidence.
- JSON and reports retain outcome and evidence.
- The [README example][readme-example] no longer teaches “captcha selector absent means success.”
- Example results are regenerated.

## Issue 2

### Report unavailable CreepJS scores as missing data instead of zero

## Problem

The [CreepJS extractor][creepjs] hard-codes trust and bot scores to `0` while scoring is unavailable. Reports then present missing data as measurements.

## Proposed fix

Return `null` for unavailable scores, keep WebRTC IP independent, and omit unavailable numeric series from tables and charts.

## Acceptance criteria

- JSON uses `null`, not a fabricated number.
- Reports show “unavailable” and do not draw zero-valued bars.
- Tests distinguish a real zero from missing data.

## Issue 3

### Remove proxy-IP confounding from browser engine comparisons

## Problem

IP reputation affects bypasses, but the benchmark assigns [a different proxy to each engine][proxy-method]. Results therefore mix engine behavior with proxy reputation. HTTP, SOCKS5-only, and unproxied engines are also ranked together.

## Proposed fix

Compare engines only within cohorts sharing the same route set. Run every engine across every route in its cohort, randomize order, aggregate across routes, and report incompatible cohorts separately.

Record an opaque route ID, verified exit IP, protocol, timestamp, engine/browser versions, OS, and benchmark commit. Never store proxy credentials or URLs.

## Acceptance criteria

- Cross-engine comparisons use identical route IDs.
- Results retain each engine × route observation and report variation.
- Incomparable cohorts are not placed in one ranking.
- The manifest records reproducibility metadata without credentials.

[repo]: https://github.com/techinz/browsers-benchmark
[runner]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/main.py#L43-L57
[cloudflare]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/cloudflare_protected.py#L4-L16
[perimeterx]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/perimeterx_protected.py#L6-L17
[results]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/benchmark_results.json#L1587-L1660
[cf-shot]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/media/screenshots/patchright_headless/cloudflare_protected.png
[px-shot]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/media/screenshots/patchright_headless/perimeterx_protected.png
[readme-example]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/README.md#L352-L381
[creepjs]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/browser_data/creepjs.py#L10-L58
[proxy-method]: https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/README.md#L48-L64
