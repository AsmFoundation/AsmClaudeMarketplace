# asmsdk: a Claude Code plugin for AsmSdk

[AsmSdk](https://github.com/AsmFoundation/AsmSdk) (`AsmFoundation.Sdk`; documentation at
<https://asmfoundation.github.io/AsmSdk/>) is the
AsmFoundation's project, dependency and build management for x86-64 assembly, on MSBuild
and NuGet. This plugin gives Claude the knowledge to build, reference, package, test and
release `.asmproj` projects without guessing.

```text
/plugin marketplace add AsmFoundation/AsmClaudeMarketplace
/plugin install asmsdk@asmfoundation
```

The skill loads by itself when a task involves an `.asmproj`, `AsmFoundation.Sdk`, NASM
built with `dotnet build`, asm NuGet packages, or a linker error from such a build. You can
also ask for it by name: `/asmsdk:asmsdk`.

## What it covers

It documents **AsmFoundation.Sdk 0.1.0**. Every behavior the skill marks *verified* was
measured by building with that release and its bundled NASM 3.02 and `ld.lld` 23.1.5, on
Windows and in Linux.

| Part | Content |
|---|---|
| `SKILL.md` | the model, recipes (new projects, .NET interop, asm references, packages, glibc, defines, shared include folders), the NASM rules that decide whether code links, diagnostics, verified footguns |
| `references/project-reference.md` | every property, item, metadata, target, generated file and error, with exact defaults and evaluation order |
| `references/runtimes-and-linking.md` | Freestanding and Libc, exact link lines, the libc stub, production link options (`-z defs`, `--exclude-libs`, `$ORIGIN`), debug information |
| `references/nasm-for-asmsdk.md` | position-independent code with the exact linker errors, symbols, sections, includes, the System V ABI, system calls, templates that were run from Python |
| `references/dependencies-and-packaging.md` | ProjectReference and PackageReference flows, pack layout, consumer props, Central Package Management, feeds, publishing |
| `references/interop.md` | .NET P/Invoke (`LibraryImport`), marshalling, tests, Python `ctypes`, C headers |
| `references/toolchain.md` | bundled vs. system tools, supported build machines, offline and air-gapped builds |
| `references/ci-and-release.md` | GitHub Actions, trusted publishing to nuget.org, reproducible outputs |
| `references/troubleshooting.md` | every error found: exact text, cause, fix |
| `references/internals.md` | the target graph, incremental rules, extension points (generated sources and includes, post-link steps) |

## Scripts

All three need only Python 3.8+.

| Script | Does |
|---|---|
| `scripts/new_asmproj.py` | scaffolds a project (library, static library, executable or objects; Freestanding or Libc; packable or not), its `global.json` entry and `.slnx` registration. It never overwrites a file |
| `scripts/check_asmproj.py` | lints projects and sources with 31 checks, such as missing `default rel`, a call without `wrt ..plt`, a `hidden` that NASM ignores, a dropped `DEBUG`, an untracked include folder, a package without include files or a wrong reference kind. It exits 1 on errors |
| `scripts/inspect_elf.py` | summarizes an ELF output or archive (type, SONAME, NEEDED, RUNPATH, interpreter, exports, imports, stack) using the toolchain's own `llvm-readobj`, and checks expectations for CI |

`tests/test_scripts.py` gives every linter check a fixture that must trigger it, plus clean
projects that must not trigger anything:

```sh
python -m unittest discover -s plugins/asmsdk/tests
```

## Evaluation

`evals/` holds the `claude plugin eval` suite and its committed results. There are two
kinds of case:

- **trigger cases:** prompts that should and should not load the skill;
- **task cases:** run with and without the plugin. What the agent wrote is graded, and then
  built with the real SDK.

**First results (2026-11-17):**

- **Triggering:** the skill loaded for 30 of 30 should-trigger runs and 0 of 30 near-miss
  runs on Sonnet 5.5, and 10 of 10 and 0 of 10 on Opus 5.5.
- **Tasks:** with the plugin, 12 of 12 agent-written workspaces built and passed their
  checks with the real SDK, against 4 of 12 without it. The runs also took half the time.

See [`evals/README.md`](evals/README.md) for how to run the suite, and the benchmark
summaries for every number.
