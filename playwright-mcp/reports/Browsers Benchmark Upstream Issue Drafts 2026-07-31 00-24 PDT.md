# Browsers Benchmark Upstream Issue Drafts — 2026-07-31 00:24 PDT

Target repository: [techinz/browsers-benchmark](https://github.com/techinz/browsers-benchmark)

These drafts are independent so each can be reviewed, discussed, and implemented without coupling it to the others.

## Issue 1

### Title

Avoid false-positive bypasses by requiring positive success evidence

### Body

## Problem

A bypass test can currently pass when navigation failed, the page is blank, or a protection system changed its challenge markup.

`test_bypass_target()` records navigation time but does not use `navigation_result["success"]` before invoking the target checker:

- [`main.py`](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/main.py#L43-L57)

Several target checkers then define success as the absence of one known challenge selector:

- [Cloudflare](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/cloudflare_protected.py#L4-L16)
- [PerimeterX / HUMAN](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/perimeterx_protected.py#L6-L17)
- [Amazon](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/amazon.py#L4-L13)
- [Ticketmaster](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/ticketmaster.py#L4-L13)
- [Reddit](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/check_bypass/reddit.py#L4-L15)

The committed example demonstrates the resulting false positives. `patchright_headless` records both Cloudflare and Priceline as successful bypasses:

- [Recorded results](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/benchmark_results.json#L1587-L1660)

The screenshots from the same run visibly show challenges:

- [Cloudflare “Verify you are human”](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/media/screenshots/patchright_headless/cloudflare_protected.png)
- [Priceline “Press & Hold”](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/results/example/media/screenshots/patchright_headless/perimeterx_protected.png)

The extension example in the README also recommends the unsafe pattern `return not element_found`, which propagates this behavior to new targets:

- [Adding new targets](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/README.md#L352-L381)

## Proposed design

Represent a target result as exactly one of four outcomes:

- `passed`: positive evidence proves that the intended target application rendered
- `blocked`: known challenge or denial evidence is present
- `inconclusive`: a document rendered, but it matches neither the success evidence nor the known block evidence
- `error`: navigation or browser operation failed

Each target checker should inspect both positive application evidence and known block evidence. Classification order should be:

1. Browser or navigation failure → `error`
2. Known block evidence → `blocked`
3. Positive application evidence → `passed`
4. Neither → `inconclusive`

Block evidence takes precedence because a site shell can remain in the DOM underneath a challenge overlay. Blank and unfamiliar pages can never pass.

Store the evidence used for the verdict in the result, such as the matched selector or the navigation failure reason. This makes individual classifications auditable without relying only on screenshots.

The report should show the four outcome counts and calculate the headline conservatively as `passed / attempted`. It must not merge `inconclusive` or `error` into `passed`.

## Acceptance criteria

- Navigation failures cannot produce `passed`.
- Every target requires positive application evidence before returning `passed`.
- Every target has fixture-backed tests for a successful page, a known challenge page, and an empty or unfamiliar page.
- A page containing both application and challenge evidence returns `blocked`.
- JSON results retain the outcome and its evidence.
- Markdown and image reports distinguish all four outcomes.
- The README’s target-extension example demonstrates positive and negative evidence rather than “captcha selector absent means success.”
- The committed example benchmark is regenerated after the classifiers are corrected.

## Issue 2

### Title

Report unavailable CreepJS scores as missing data instead of zero

### Body

## Problem

CreepJS currently does not expose trust and bot scores. The extractor acknowledges this but returns `0` for both values:

- [`utils/targets/browser_data/creepjs.py`](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/utils/targets/browser_data/creepjs.py#L10-L58)

Zero is a valid score, so the generated JSON, table, and chart present unavailable data as measured results. The report can consequently imply both zero trust and zero bot likelihood for every engine even though neither value was observed.

## Proposed design

Represent unavailable CreepJS scores as missing data:

- `creepjs_trust_score: null`
- `creepjs_bot_score: null`

Continue reporting independently available CreepJS fields such as the WebRTC IP. Report generation should omit unavailable numeric series and state that scoring is unavailable rather than drawing zero-valued bars.

## Acceptance criteria

- The extractor never substitutes a numeric score for unavailable CreepJS data.
- JSON serializes unavailable trust and bot scores as `null`.
- The Markdown report labels the scores unavailable.
- The CreepJS chart is omitted, or renders an explicit unavailable state, when no real scores exist.
- WebRTC IP extraction continues to work independently.
- Tests distinguish a real numeric zero from unavailable data.

## Issue 3

### Title

Remove proxy-IP confounding from browser engine comparisons

### Body

## Problem

The benchmark identifies IP reputation and rate limiting as important influences on bypass results, but assigns a different proxy to each engine. The sample report explicitly notes that every engine used a different proxy IP:

- [Proxy requirements and sample methodology](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/README.md#L48-L64)
- [Per-engine proxy assignment](https://github.com/techinz/browsers-benchmark/blob/8b7d10bc898e63093043832d9dc29da72e52789b/main.py#L260-L294)

A single result then combines two independent variables: browser engine and proxy reputation. A difference between engines cannot be attributed to the engine when their network routes differ.

The comparison is also asymmetric: HTTP-capable engines, SOCKS5-only engines, and unproxied Selenium runs are ranked together despite using incomparable network conditions.

## Proposed design

Treat the network route as an explicit benchmark factor:

- Group engines into cohorts that can use the same proxy routes.
- Run every engine in a cohort across the same set of routes.
- Randomize engine order within each route to reduce time and rate-limit bias.
- Aggregate results across routes instead of publishing a single engine/proxy observation.
- Report engines from incompatible network cohorts separately rather than placing them in one ranking.

Record an opaque route identifier, verified exit IP, protocol, timestamp, engine version, browser version, operating system, and benchmark commit in each result. Proxy credentials and complete proxy URLs must not be stored.

If a proxy provider exposes the same exit through HTTP and SOCKS5 endpoints, those endpoints can share a route identifier. Otherwise their results belong to separate cohorts.

## Acceptance criteria

- Every cross-engine comparison uses the same route identifiers for every engine in its cohort.
- Results retain individual engine × route observations rather than only a pre-aggregated score.
- Reports show sample count and variation across routes.
- Engines without comparable routes are reported separately and are not included in the same ranking.
- The result manifest records enough environment and version metadata to reproduce the run without exposing proxy credentials.
- Documentation no longer claims that one different proxy per engine isolates engine capability.
