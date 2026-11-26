# asmsdk evaluation

This folder holds a [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals)
suite for the `asmsdk` plugin and a build check that runs the real AsmSdk on what the agent
wrote. It also holds the controls that prove both judges, and the committed results.

## What is measured

| Suite | Cases | Question | Graders |
|---|---|---|---|
| `trigger/` | 10 should-trigger + 10 near misses | Does Claude load the skill when, and only when, a request is about AsmSdk? | `tool_used: Skill` (`min: 0, max: 0` for near misses) |
| `task/` | 5 tasks, run **with** and **without** the plugin | Does the plugin make Claude's answer correct? | free `regex` / `file_exists` graders over the files written, plus `build_check.py` |

**Should-trigger requests** mix explicit ones with implicit ones:

- **Explicit:** an `.asmproj`, ASM0001, an `ASM0102` after upgrading from 0.1.0.
- **Implicit:** "build my NASM with `dotnet build`", "C# calling NASM in one solution", a
  raw `ld.lld` relocation error.

**Near misses** share vocabulary but belong elsewhere:

- instruction semantics (PDEP);
- CMake, Makefile, MASM or AT&T syntax;
- C intrinsics;
- trusted publishing for a C# library;
- a `.csproj` pre-build script;
- a .NET `DllNotFoundException` for SQLite;
- an ABI register question.

**Task cases** name AsmFoundation.Sdk 0.4.0. They ask for files at fixed paths, so that free
graders can read them:

| Case | What it tests |
|---|---|
| `task-dotnet-interop` | A new `.slnx` with an asm shared library for linux-x64, win-x64 and osx-x64, and a .NET app that P/Invokes it. It checks: `global.json` msbuild-sdks, the `.slnx` type GUID, `AssemblyName`, `ProjectReference`, the per-OS argument registers, and the `LibraryImport` name `calc`. `libcalc` misses `calc.dll` on Windows. |
| `task-package-and-consume` | A static library packed as `Acme.Crc` 1.2.0, consumed by version from a folder feed, both for linux-x64. It checks: a public include file in `include/` (otherwise not packed), `PackageReference`, `nuget.config`. Its wrong control keeps `crc.inc` outside `include/`, so the tool fails to assemble (with 0.3.0 the control was a tool without `RuntimeIdentifiers`, which 0.4.0 builds for the build machine's RID). |
| `task-defines-keep-debug` | Adding `USE_AVX2=1` to a linux-x64 and win-x64 library without changing Debug and Release. It checks `DefineConstants`, after which the SDK appends `DEBUG`/`RELEASE`, the framework, OS and CPU symbols, and the kept `RuntimeIdentifiers`. 0.1.0's `AsmDefineConstants` dropped `DEBUG`, and is `ASM0102` since 0.2.0. |
| `task-port-to-every-os` | A Linux-only library whose `win-x64` and `osx-x64` builds fail with the NASM errors that 0.3.0 and 0.4.0 really print. Only `hash64` may be exported on each OS. It checks: `FUNCTION` (or `-export:`) for the DLL, `HIDDEN_FUNCTION` or `private_extern` for the internals, `hidden` before the size on Linux, and the argument register per OS. |
| `task-wasm-library` | A WebAssembly library `Sum` for `browser-wasm` and `wasi-wasm` with `sum_i32` and its PROTO line. It checks: both RIDs, a source qualified for wasm (`sum.wasm.s`; an unqualified `.s` is ARM64 code), the `FUNCTION` wasm signature, the `PROTO` line, and no assembler constant (llvm-mc's wasm writer crashes on one). |

`task-port-to-every-os` replaced 0.2.0's `task-fix-pic-link-errors` in plugin 0.3.0. Since
0.3.0 links Linux libraries `-Bsymbolic`, the two `R_X86_64_PC32 … recompile with -fPIC`
errors that the old case quoted no longer happen. The same sources link, and export their
internals.

### build_check.py

**`build_check.py`** copies each kept workspace and builds it with AsmFoundation.Sdk 0.4.0
and its bundled toolchain:

- **What it builds:** every RID the task names, on whatever OS it runs on. It never builds a
  project that defines its own MSBuild targets.
- **What it reads:** the exports of each RID's library (ELF, PE and Mach-O), with the
  plugin's `inspect_output.py`.
- **What it runs:** only Linux outputs, in a Linux container. Windows and macOS outputs are
  never run.

| Case | Build check |
|---|---|
| `task-dotnet-interop` | `libcalc.so`, `calc.dll` and `libcalc.dylib` all export `calc_sum`, and the .NET app runs on Linux and prints 10 |
| `task-package-and-consume` | `Crc` is packed into `packages/`, `Tool` restores it by version and builds, and the executable exits 0 |
| `task-defines-keep-debug` | a probe source fails the build unless Debug defines `DEBUG` and `USE_AVX2`, and Release defines `USE_AVX2` but not `DEBUG`, for both RIDs |
| `task-port-to-every-os` | the project from the prompt builds for its three RIDs, and `hash64` is the only export of `libHash.so`, `Hash.dll` and `libHash.dylib` |
| `task-wasm-library` | both RIDs' `Sum.wasm` export `sum_i32`, the browser module carries the PROTO record, and in Node, instantiated with no imports (so it can only compute), it sums `[1, 2, 3, 4, -20]` to -10, an empty range to 0 and the last three to 9 |

Where a task did not ask for them, the check adds only a `global.json` entry and the local
feed for the SDK. The feed holds the SDK version that the prompts name, which may not be on
nuget.org yet.

### The controls

`controls/<case>/` holds known answers. `pass-<n>` is right, and `fail-<n>` is wrong in a
way an agent might be:

| Control | What is wrong with it | Caught by |
|---|---|---|
| `task-dotnet-interop/fail-1` | `global calc_sum` with the System V registers, `DllImport("libcalc")` | two graders; `calc.dll` exports nothing |
| `task-package-and-consume/fail-1` | `Tool` has no `RuntimeIdentifiers` | the build check only (`ASM0010`) |
| `task-defines-keep-debug/fail-1` | 0.1.0's `AsmDefineConstants` | one grader; `ASM0102` |
| `task-port-to-every-os/fail-1` | the prompt's sources, verbatim | five graders; the build fails with the prompt's errors |
| `task-port-to-every-os/fail-2` | `hidden` on Linux only, plain globals elsewhere | four graders; `Hash.dll` exports `[]` and `libHash.dylib` exports `hash_seed` and `mix64` |
| `task-wasm-library/fail-1` | the right code in an unqualified `sum.s` | four graders; `ASM0023` |
| `task-wasm-library/fail-2` | a `.set ELEMENT_SIZE, 4` constant | one grader; llvm-mc's wasm writer crashes (`absolute addressing not supported!`) |

Two judges are checked against the controls:

- **The build check:** `build_check.py --controls` builds every control and exits 1 when one
  passes or fails against its folder name. Run it after changing the check, a task or the SDK
  version, before trusting a verdict.
- **Everything else:** `tests/test_evals.py`, in CI, checks four things:
  - every grader accepts every right answer;
  - each wrong answer fails exactly the graders that the table above counts;
  - the plugin's linter is clean on the right answers and flags each wrong one;
  - prompts, graders and the check name one SDK version.

The answers were also run on 2026-11-20:

- **`task-port-to-every-os/pass-1`:** `hash64` returns what the original sources compute,
  `mix64(x ^ hash_seed)`, at four inputs, from `Hash.dll` on Windows and from `libHash.so`
  on Linux.
- **`task-dotnet-interop/pass-1`:** the app prints 10 on both.
- **`task-dotnet-interop/fail-1`:** the app stops on Windows with
  `DllNotFoundException: Unable to load DLL 'libcalc'`.

## Running it

From `plugins/asmsdk`:

```sh
# Trigger suite: one arm (the Skill grader is the whole question).
claude plugin eval . --tag trigger --ablation none --runs 3 -j 4 --model claude-sonnet-5-5 --no-publish

# Task suite: with and without the plugin; keep the workspaces for the build check.
claude plugin eval . --tag task --runs 3 -j 4 --model claude-sonnet-5-5 \
  --allow-tools Write Edit --keep-temp --no-publish --json task.json

# The build check's own controls first, then the eval's workspaces.
python evals/build_check.py --controls evals/controls --feed <folder with AsmFoundation.*.nupkg> \
  --nuget-packages <empty folder> --work <scratch folder> --docker --out controls-check.json
python evals/build_check.py --result task.json --feed <folder with AsmFoundation.*.nupkg> \
  --nuget-packages <empty folder> --work <scratch folder> --docker --out build-check.json
```

- **The feed** holds `AsmFoundation.Sdk.0.4.0.nupkg` and the toolchain package of the
  machine that builds (`AsmFoundation.Toolchain.<rid>`). The toolchain package has its own
  version, 0.2.0 for SDK 0.3.0 and 0.4.0.
- **Every prompt, grader and `SDK_VERSION` name 0.4.0**, as they moved to 0.3.0 for plugin
  0.3.0. Measured 2026-11-26 with the 0.4.0 packages, on Windows x64 without Docker (so no
  Linux output ran): all 12 controls passed or failed as their names say. `task-wasm-library`
  `pass-1` exported `sum_i32` from both modules with its PROTO record, and Node printed its
  sums; `fail-1` stopped with ASM0023 and `fail-2` with llvm-mc's crash. The package task's
  `fail-1` stopped at the tool's `%include "crc.inc"`. Measured 2026-11-24 with a `main` build,
  before the release, the wasm controls gave the same verdicts.
- **Bash is not needed:** the cases grant only Read, Glob, Grep, Skill, Write and Edit.
  This lets the suite run on native Windows, where `claude plugin eval` refuses shell
  grants for lack of a sandbox backend.
- **Clean up afterwards:** `--keep-temp` leaves each run's folder in the temp directory.
  Delete those folders once the build check is done.

## Results

### 2026-11-17

These results come from plugin 0.1.0 against AsmFoundation.Sdk 0.1.0, with no judge model
anywhere. Plugin 0.2.0 moved the prompts, graders and build check to 0.2.0, plugin 0.3.0
moved them to 0.3.0 and replaced one case, and plugin 0.4.0 moved them to 0.4.0 and added the
WebAssembly case. These results were not measured again.

| Measure | Result |
|---|---|
| Should-trigger requests loaded the skill, Sonnet 5.5 (3 runs each) | **30 / 30** |
| Near misses stayed silent, Sonnet 5.5 | **30 / 30** |
| The same on Opus 5.5 (1 run each) | **10 / 10** and **10 / 10** |
| Task graders, with vs without the plugin (Sonnet 5.5, 3 runs per arm) | **1.00** vs 0.78 (mean over 4 cases) |
| Workspaces that built and passed the real-SDK check | **12 / 12** with the plugin, **4 / 12** without |
| Mean time and total cost per arm | 232 s, $8.27 with; 444 s, $11.04 without |

**Without the plugin, the runs failed in these ways:**

- the SDK not resolvable (no `msbuild-sdks`);
- an `.slnx` the CLI rejects (`MSB4025`);
- `liblibcalc.so` instead of `libcalc.so`;
- invented properties (`AsmDefines`) that never reach NASM;
- `DEBUG` lost;
- a package that ships no include file.

**The one task without a difference:** fixing `R_X86_64_PC32` with `hidden`. The base
model already knew that rule. That case is the one 0.3.0 replaced.

**Details:**

- [`benchmarks/2026-11-17-sonnet-5-5/SUMMARY.md`](benchmarks/2026-11-17-sonnet-5-5/SUMMARY.md):
  the full suite, including what every run wrote;
- [`benchmarks/2026-11-17-opus-5-5/SUMMARY.md`](benchmarks/2026-11-17-opus-5-5/SUMMARY.md):
  the trigger cross-check.
