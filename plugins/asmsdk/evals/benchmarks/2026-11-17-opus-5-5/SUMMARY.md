# asmsdk trigger cross-check, 2026-11-17, Claude Opus 5.5

**Why:** the full suite ran on Sonnet 5.5. This pass checks that the skill's description also
works for the model AsmFoundation developers use day to day.

**Setup:** the same 20 trigger cases and plugin commit as the Sonnet run, with **one run per
case** and agent model `claude-opus-5-5`. 20 runs, $8.40 at list price, 18 min.

| | Runs | Skill loaded |
|---|---|---|
| 10 should-trigger requests | 10 | **10 / 10** |
| 10 near misses | 10 | **0 / 10** |

**Runs that ended early:**

- **Turn cap:** 4 should-trigger runs stopped at the 5-turn cap (t01, t02, t09, t10), after
  the skill had loaded.
- **Timeouts:** 3 near-miss runs timed out at 300 s while Opus searched the empty sandbox
  with Glob, looking for CMake modules, `nasm.exe` or project files, before writing an
  answer (n02, n08, n10). None of them loaded the skill.
- **n08:** its first run recorded no model turn at all. It was re-run once
  (`trigger-n08-rerun/`): Opus again began by searching for project files, and did not load
  the skill. Both runs count as silent, but neither got as far as an answer.

**Files:**

- `trigger/aggregate-result.json` and `trigger/report.html`;
- `trigger-n08-rerun/`.

Local paths are replaced by `<temp>` and `<repo>`.
