# asmsdk: a Claude Code plugin for AsmSdk

[AsmSdk](https://github.com/AsmFoundation/AsmSdk) (`AsmFoundation.Sdk`; documentation at
<https://asmfoundation.github.io/AsmSdk/>) is the
AsmFoundation's project, dependency and build management for assembly, on MSBuild and NuGet.
This plugin gives Claude the knowledge to build, reference, package, test and release
`.asmproj` projects without guessing.

```text
/plugin marketplace add AsmFoundation/AsmClaudeMarketplace
/plugin install asmsdk@asmfoundation
```

The skill loads by itself when a task involves an `.asmproj`, `AsmFoundation.Sdk`, NASM
built with `dotnet build`, asm NuGet packages, or a linker error from such a build. You can
also ask for it by name: `/asmsdk:asmsdk`.

## What it covers

It documents **AsmFoundation.Sdk 0.3.0**. A project lists its runtime identifiers (seven:
x86-64 and ARM64 on Windows, Linux and macOS, plus musl on x64), and one `dotnet build`
builds each:

- NASM for the x64 RIDs, GNU syntax through llvm-mc for ARM64;
- the C library of every OS;
- .NET consumers by RID.

It also documents **WebAssembly**, the SDK's third target, in the release after 0.3.0 (on
AsmSdk's `main` branch until then): `browser-wasm` and `wasi-wasm` from `.wasm.s` sources in
LLVM's WebAssembly assembly, as modules for JavaScript, WASI programs and the archives .NET
WebAssembly apps link. This branch of the plugin is merged when that SDK release ships.

What the skill marks *verified* was measured. Each behavior was built with an AsmSdk release
and its bundled tools, or is covered by AsmSdk's end-to-end tests on five build machines.
What each output format's NASM accepts was measured directive by directive. For a 0.1.0 or
0.2.0 project, the skill and the linter name each removed setting's replacement.

| Part | Content |
|---|---|
| `SKILL.md` | the model, recipes (one source for every OS, .NET by RID and publishing, asm references, packages per RID, the C library per OS, defines, shared include folders), the per-OS NASM rules that decide whether code assembles and links, diagnostics, verified footguns |
| `references/project-reference.md` | every property, item, metadata, target, generated file and error, with exact defaults and evaluation order |
| `references/platforms.md` | the seven RIDs, the RID outer build, source selection by file name, `asmsdk.inc` and `asmsdk-gnu.inc`, what each OS's linker and loader require |
| `references/runtimes-and-linking.md` | the `freestanding` and `libc` target frameworks, exact link lines per OS, the C library stand-ins, production link options (`-z defs`, `--exclude-libs`, `$ORIGIN`, `ExportsFile`), debug information |
| `references/nasm-for-asmsdk.md` | position-independent code with the exact linker errors, symbols per format (export, hide, size), sections, includes, the calling conventions, system calls |
| `references/dependencies-and-packaging.md` | ProjectReference and PackageReference flows, pack layout per RID, consumer props, Central Package Management, feeds, publishing |
| `references/interop.md` | .NET P/Invoke (`LibraryImport`) by RID, publishing (single file, NativeAOT), marshalling, tests, Python `ctypes`, C headers |
| `references/toolchain.md` | bundled vs. system tools, supported build machines, offline and air-gapped builds |
| `references/ci-and-release.md` | GitHub Actions on the three OSes, trusted publishing to nuget.org, reproducible outputs |
| `references/troubleshooting.md` | every error found: exact text, cause, fix |
| `references/internals.md` | the target graph, incremental rules, extension points (generated sources and includes, post-link steps) |
| `references/webassembly.md` | WebAssembly, the SDK release after 0.3.0: `browser-wasm` and `wasi-wasm`, `.wasm.s` sources and `asmsdk-wasm.inc`, PROTO on wasm, .NET WebAssembly apps, modules for JavaScript, WASI programs, packages, the measured traps |

## Scripts

All three need only Python 3.8+.

| Script | Does |
|---|---|
| `scripts/new_asmproj.py` | scaffolds a project for every RID its kind can build, or the ones `--rids` names: library, static library, executable or objects, `freestanding` or `libc`, packable or not. Starter sources come for both CPUs, written to assemble and link on every OS, and for WebAssembly when `--rids` names `browser-wasm` or `wasi-wasm` (a `.wasm.s` library, or a WASI command). It also adds the `global.json` entry and the `.slnx` registration. It never overwrites a file |
| `scripts/check_asmproj.py` | lints projects and sources with 64 checks. It judges each source for the OSes it builds for: its RIDs, its file-name qualifier, its `%ifdef WINDOWS`/`LINUX`/`MACOS` guards. Examples: a directive that macOS's or Windows' NASM rejects, a call to another library without `PLT`, a plain `global` no DLL exports, a symbol hidden on one OS and exported on another, a `hidden` that NASM ignores, a C function outside the OS's C library, a removed setting, two projects NuGet cannot tell apart, the source-selection errors. For WebAssembly (the SDK release after 0.3.0), 19 more: the project rules (a browser program, a libc module, a define with a value, an export pattern) and llvm-mc's measured traps in `.wasm.s` sources (an assembler constant, a data label without `ENDDATA`, `PROTO` inside a function, an untyped `select`, `return_call` where .NET links the code, a call to a function llvm-mc has not seen, a `PROTO` whose C types lower to another wasm type). It exits 1 on errors |
| `scripts/inspect_output.py` | summarizes an output or static library using the toolchain's own `llvm-readobj`, and checks expectations for CI. ELF: type, SONAME, NEEDED, RUNPATH, interpreter, exports, imports, stack. PE: DLL or program, exports, imported DLLs and functions, ASLR and DEP. Mach-O: install name, needed libraries, exports and imports by C name. WebAssembly, read in Python: module, WASI command, object or archive; exports, imports, memory, custom sections and the `asmapi` records (`--expect-import`) |

Two test modules, standard library only:

- **`tests/test_scripts.py`** gives every linter check a fixture that must trigger it, plus
  clean projects that must not trigger anything. It tests the inspector on canned
  `llvm-readobj` output.
- **`tests/test_evals.py`** checks the evaluation suite's graders, prompts and linter against
  its known right and wrong answers.

```sh
python -m unittest discover -s plugins/asmsdk/tests
```

## Evaluation

`evals/` holds the `claude plugin eval` suite and its committed results. There are two
kinds of case:

- **trigger cases:** prompts that should and should not load the skill;
- **task cases:** run with and without the plugin. What the agent wrote is graded, and then
  built with the real SDK for every RID the task names. The check reads each library's
  exports, and runs the Linux outputs.

`evals/controls/` holds a right answer and wrong ones for every task, which prove both
judges.

**First results (2026-11-17, plugin 0.1.0 with AsmSdk 0.1.0; not re-measured since):**

- **Triggering:** the skill loaded for 30 of 30 should-trigger runs and 0 of 30 near-miss
  runs on Sonnet 5.5, and 10 of 10 and 0 of 10 on Opus 5.5.
- **Tasks:** with the plugin, 12 of 12 agent-written workspaces built and passed their
  checks with the real SDK, against 4 of 12 without it. The runs also took half the time.

See [`evals/README.md`](evals/README.md) for how to run the suite, and the benchmark
summaries for every number.
