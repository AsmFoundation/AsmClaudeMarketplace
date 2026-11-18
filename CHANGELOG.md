# Changelog

Changes to the marketplace and its plugins. Each plugin carries its own version in its
`plugin.json`. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## 2026-11-18

### Changed

- **`asmsdk` 0.2.0, for AsmFoundation.Sdk 0.2.0,** which renamed every setting to .NET's
  own and has no compatibility layer:
  - **the skill and its references** use the 0.2.0 names (`AssemblyName`, `TargetFramework`
    `freestanding`/`libc`, `DefineConstants`, `DebugSymbols`, `StartupObject`, `LinkerArg`
    and `ExportsFile`, `OutputType`) and outputs in `bin/<Configuration>/<tfm>/`. The
    references were moved by merging the 0.2.0 documentation site's changes, keeping the
    *verified* markers;
  - **new facts:** NuGet's `NU1201`/`NU1202` between `freestanding` and `libc`, the
    per-framework package layout, the `PackageId` that follows `AssemblyName` ("Ambiguous
    project name"), and IDE integration (0.1.0 projects look empty in Rider and Visual Studio);
  - **0.1.0's `DEBUG` footgun is gone:** 0.2.0 appends `DEBUG`/`RELEASE` and
    `FREESTANDING`/`LIBC` after the project body;
  - **`check_asmproj.py`** now has 33 checks: `ASMPRJ013` reports each removed 0.1.0
    setting with its replacement (the SDK's `ASM0100`-`ASM0108`), `ASMPRJ014` two projects
    of one restore graph with the same `PackageId`, and `ASMREF003` a freestanding project
    that references libc-only code. `ASMPRJ001` (0.1.0's dropped `DEBUG`) is retired;
  - **`new_asmproj.py`** writes 0.2.0 projects; its flags take .NET's names too:
    `--framework freestanding|libc` and `--assembly-name`;
  - **the evals** (prompts, graders, `build_check.py`) use 0.2.0. The committed results are
    plugin 0.1.0's against SDK 0.1.0, and were not re-measured.

- **`asmsdk` 0.1.2** extends the jump-table rule beyond shared libraries. A `dq label` in
  `.rodata` also fails to link in a Libc executable, which is a PIE. A Freestanding
  executable, linked `-static`, accepts it in any section, because its addresses are fixed
  at link time. Both facts were verified with the bundled NASM 3.02 and ld.lld 23.1.5.
  AsmSdk's guide and its build-targets comment now say the same.
- **`asmsdk` 0.1.1** points at the AsmSdk documentation site,
  <https://asmfoundation.github.io/AsmSdk/>: the skill names it as the page to check for
  newer SDK versions and to link users to, and the plugin and marketplace READMEs link it.
  The site's guides are written from the same verified facts as the skill.

## 2026-11-17

### Added

- **The `asmfoundation` marketplace,** with one plugin per topic.
- **`asmsdk` 0.1.0, for AsmFoundation.Sdk 0.1.0:**
  - a skill covering the whole SDK: the model, recipes, the NASM linking rules, diagnostics
    and verified footguns;
  - nine reference files;
  - three tested scripts: `new_asmproj.py` scaffolds, `check_asmproj.py` lints with 31
    checks, and `inspect_elf.py` inspects ELF outputs;
  - a `claude plugin eval` suite: 20 trigger cases and 4 task cases, plus a build check that
    builds and runs what each arm wrote. Results are committed in
    `plugins/asmsdk/evals/benchmarks/`:
    - triggering was 30/30 and 0/30 on Sonnet 5.5, and 10/10 and 0/10 on Opus 5.5;
    - task graders scored 1.00 with the plugin and 0.78 without;
    - 12 of 12 workspaces built with the real SDK, against 4 of 12.
- **ROADMAP.md,** the proposed next plugins.
