# asmsdk evaluation, 2026-11-17, Claude Sonnet 5.5

**Setup:**

- **Tools:** Claude Code 2.1.322, `claude plugin eval`; agent model `claude-sonnet-5-5`;
  only free graders (no judge model).
- **Plugin:** `asmsdk` 0.1.0 at commit 6d544b7, plus the grader fix noted below.
- **Machine:** Windows 11. Each run had an isolated home and configuration, so the user's
  settings, hooks, CLAUDE.md, MCP servers and other plugins were absent.
- **Build check:** AsmFoundation.Sdk 0.1.0 and AsmFoundation.Toolchain.win-x64 0.1.0 from a
  local feed, .NET SDK 11.0.100. Outputs ran in `mcr.microsoft.com/dotnet/runtime:10.0`
  (glibc 2.39).

## Trigger suite: does the skill load when, and only when, it should?

20 cases, 3 runs each, one arm (`--ablation none`): 60 runs, $11.94 at list price, 29 min.

| | Runs | Skill loaded |
|---|---|---|
| 10 should-trigger requests | 30 | **30 / 30** |
| 10 near misses | 30 | **0 / 30** |

**Every case scored 1.00** (`trigger/report.html`, `trigger/aggregate-result.json`).

**Runs that ended early:**

- **Turn cap:** 7 runs stopped at the 5-turn cap (t01 ×2, t08, t09 ×3, t10). The skill had
  already loaded in each, and was then reading references or writing a long answer.
- **Timeout:** 5 near-miss runs timed out at 300 s while writing long answers (n02 CMake ×3,
  n10 Makefile ×2). None had loaded the skill.

**What this does not show:** each run had only this plugin's skill to choose from. In a
session with many skills, near misses compete with other skills. The suite measures the
description, not that competition.

## Task suite: does the plugin make the answer correct?

4 cases, 3 runs per arm, with and without the plugin: 24 runs, $19.31, 37 min.

### Graders on the files written

| Case | With | Without | Δ | What the runs without the plugin got wrong (3 of 3 runs unless noted) |
|---|---|---|---|---|
| `task-dotnet-interop` | **1.00** | 0.57 | +0.43 | no `msbuild-sdks` entry in `global.json`; no type GUID for the `.asmproj` in the `.slnx`; wrong library name (`AssemblyName` `libcalc`, giving `liblibcalc.so`) |
| `task-defines-keep-debug` | **1.00** | 0.67 | +0.33 | `DEBUG` lost: they invented properties such as `<AsmDefines>$(AsmDefines);USE_AVX2=1</AsmDefines>` |
| `task-package-and-consume` | **1.00**\* | 0.88\* | +0.13 | `crc.inc` outside `include/`, so it is not packed |
| `task-fix-pic-link-errors` | **1.00** | 1.00 | 0 | nothing: the base model knows `hidden` and the PIC rules |

\* **The grader fix:**

- **Reported scores:** the run reported 0.96 and 0.83 for the package case.
- **The cause:** the `no-project-reference` grader failed one run in each arm because the
  word "ProjectReference" appeared in a comment ("not through a ProjectReference"). No
  `Tool.asmproj` in either arm contains a `<ProjectReference>` element; all six are in
  `task/workspaces/`.
- **The fix:** the grader now matches the element. The table shows the corrected scores,
  and Δ is unchanged.

The skill fired in all 12 runs with the plugin.

### Build check: built with the real SDK, then run

`build_check.py` built a copy of every workspace, adding only the local SDK feed (and a
`global.json` where the task did not ask for one).

| Case | With the plugin | Without |
|---|---|---|
| `task-dotnet-interop` | **3 / 3** build; the app prints `10` on Linux | 0 / 3: `MSB4025 … ProjectType '' not found` (`.slnx`) |
| `task-defines-keep-debug` | **3 / 3**: Debug defines `DEBUG` and `USE_AVX2`, Release only `USE_AVX2` | 0 / 3: `USE_AVX2 missing` (the invented property never reaches NASM) |
| `task-package-and-consume` | **3 / 3** pack, restore by version, build; the program exits 0 | 1 / 3; two runs: `unable to open include file 'crc.inc'` |
| `task-fix-pic-link-errors` | **3 / 3** link; `hash64` is the only export | 3 / 3 |
| **Total** | **12 / 12** | **4 / 12** |

### Cost and time

| | Runs | Cost | Mean time per run |
|---|---|---|---|
| With the plugin | 12 | $8.27 | 232 s |
| Without | 12 | $11.04 | 444 s |

With the plugin, the agent was right more often, and it finished in about half the time
for three quarters of the cost.

**Without the plugin, agents spent their turns searching:**

- for the SDK in the empty workspace and outside it (denied by the sandbox);
- for property names, which they then guessed.

**With it, they read the skill and wrote the answer.**

## Files

| Path | Content |
|---|---|
| `trigger/aggregate-result.json`, `trigger/report.html` | the trigger suite's raw result and report |
| `task/aggregate-result.json`, `task/report.html` | the task suite's raw result and report (grader scores as run, before the grader fix) |
| `task/build-check.json` | per-run build and run outcomes, with errors |
| `task/workspaces/<case>/<arm>-<run>/` | exactly what each run wrote |

Local paths are replaced by `<temp>`, `<home>` and `<repo>`.
