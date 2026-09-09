# Claude and Codex usage tracking — 2026-09-09 05:48 PDT

**Most of the data already exists on your desktop, including historical limit percentages. We can start a retrospective analysis now. For tracking changes over months, I recommend retaining quota snapshots and token records in a small durable store. Existing projects cover collection; the token-to-percentage analysis would still need some custom work.**

I inspected local files on `akelly-desktop`, T3’s source, and current project documentation. I did not install anything or change your configuration. Counts below describe the files available during the scan, not unique API requests.

| Source | Token history | Historical subscription limits |
|---|---|---|
| Codex | `~/.codex/sessions/**/*.jsonl`: input, cached input, cache writes, output, reasoning, timestamps and model context | **Yes.** About 43,000 `token_count` events with `rate_limits`, spanning August 25–September 9 |
| Claude Code | `~/.claude/projects/**/*.jsonl`: input, output, cache reads/writes, model and timestamps; work profile also lives under `~/.claude-work` | No quota events found in the default profile’s transcripts. Your status-line script displays 5-hour usage but does not save it |
| T3 | Its usage service reads the providers’ transcripts and caches parsed records in `~/.t3/userdata/usage-scan-cache.json` | **Yes, in provider logs.** `~/.t3/userdata/logs/provider/events.*.log*` contains Codex and Claude limit updates |

T3’s retained logs contained **551 Claude limit events from September 6–9**, covering both personal and work profiles. Of those, **468 contain `unifiedWindows` quota data**. One example reports 99% of the five-hour window and 19% of the weekly window, each with its reset time. Some events lack measurements and must not be treated as zero usage.

T3 also retained roughly 12,200 Codex limit notifications, each represented in both native and normalized form. Those are duplicate views of the same events. Codex’s own transcript history reaches further back, making it the better starting source for that provider.

**T3’s logs are temporary evidence, not a long-term archive.** Its source defaults to a 14-day maximum age and 512 MiB total provider-log storage. The directory currently holds about 508 MiB, and the retained quota events reach back only to September 6. The usage scan cache is also rebuildable and pruned; it is not a quota-history database.

The local source evidence is in `apps/server/src/usage/UsageService.ts`, `apps/server/src/provider/Layers/{CodexAdapter,ClaudeAdapter,EventNdjsonLogger}.ts`, and `~/.agents/claude/statusline.py`.

For future collection, both providers expose useful structured data. Claude’s documented status-line payload includes five-hour and seven-day percentages and reset timestamps. Codex’s app-server exposes `account/rateLimits/read`, limit-update notifications, and thread token updates; it also documents `account/usage/read` for account token summaries and optional daily buckets. Those daily buckets can help cross-check totals, but do not replace timestamped quota samples. [Claude status-line documentation](https://code.claude.com/docs/en/statusline), [Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)

**There are existing projects worth using or borrowing from:**

| Project | Fit for your question |
|---|---|
| [ccusage](https://ccusage.com/guide/codex/) | Token and API-equivalent cost reports from local logs. Useful for aggregation and handling duplicated inherited Codex history; not by itself a durable account-quota recorder |
| [token-burn](https://github.com/durandom/token-burn) | Closest fit for the missing collector: polls real Claude/Codex quota, stores observations in SQLite, provides history and Linux systemd support. It deliberately does not collect transcript tokens, so those need joining separately. Early software using unofficial provider endpoints |
| [LLM Usage Dashboard](https://github.com/kollinger/llm-usage-dashboard) | Closest combined dashboard: Claude/Codex transcript tokens, Claude status-line quota capture, and persistent change-only quota history. Supports server-style deployment. I verified its documented features, not its counting accuracy |
| [CodexBar](https://github.com/steipete/CodexBar) | Convenient Mac menu-bar monitoring for both providers, local cost scans, and a Linux/macOS CLI. Useful visibility; its documented charts do not establish a ready-made analysis of changing tokens per quota point |

None of the projects I checked clearly delivers the complete analysis you want: estimating how the same workload’s quota consumption changes over time, after accounting for model and cache differences.

**The measurement should be “tokens per percentage point,” separated by model and token type.** For example, if a window moves from 20% to 30%, divide the tokens consumed during that interval by 10. Compare that rate across similar intervals and weeks. Raw total tokens alone can mislead: a change in cache hits or model mix can look like a changed allowance. API-equivalent dollars are another useful comparison, but their pricing weights are not a verified subscription-quota formula.

The analysis needs a few controls:

- Keep accounts, plan labels and quota buckets separate. Your Codex records include both `prolite` and `pro`; that difference needs explaining before comparing allowance rates.
- Use reported window lengths. Your recent Codex records put a **10,080-minute weekly window in `primary`**, so assuming “primary means five hours” would give wrong results.
- Deduplicate Claude message records and Codex inherited/subagent history. Difference cumulative counters; do not sum cumulative snapshots or add cached/reasoning subsets twice.
- Combine token records from every machine and client using the same account. Account-wide quota changes cannot be explained fully by desktop-only tokens. This inspection did not audit your Mac, Windows machine, or browser usage.
- Exclude resets and plan transitions, and use intervals spanning several percentage points to reduce rounding and reporting-lag noise. Reset timestamps can vary slightly between snapshots, so exact timestamp equality is too strict for grouping windows.

**My recommendation:** backfill the existing Codex transcripts and retained T3 Claude quota events first. For ongoing collection, evaluate `token-burn` alongside the existing token parsers, or the combined LLM Usage Dashboard. If you prefer this inside T3, its adapters already receive the necessary limit events; the addition would be durable usage storage and analysis, rather than new model-request instrumentation. Claude sessions outside T3 would still need status-line capture or account polling.
