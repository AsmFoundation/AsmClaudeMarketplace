# Changelog

Changes to the marketplace and its plugins. Each plugin carries its own version in its
`plugin.json`. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased (branch `asmsdk-wasm`)

Merged when AsmFoundation.Sdk's next release ships WebAssembly (the owner's choice of
2026-11-24: "on a branch, merged with the SDK's release"); `main` is what users install.

### Added

- **`asmsdk`: WebAssembly**, the SDK's third target (`browser-wasm`, `wasi-wasm`):
  - **`references/webassembly.md`:** the RIDs and outputs, sources and their qualifiers, the
    `asmsdk-wasm.inc` macros, PROTO on wasm (the exact signature check, one API for every
    RID, the placement guard), .NET WebAssembly apps (workloads, ASM0054, the debugger trap
    when timing in a browser), modules for JavaScript, WASI programs, packages, templates,
    the measured footguns and diagnostics. Its two examples were built and run with a build
    of AsmSdk's `main` (a library summed in Node, a WASI command in wasmtime).
  - **`SKILL.md`:** a WebAssembly paragraph and recipe, three footgun rows, the reference in
    the table, WebAssembly words in the description.
  - **`check_asmproj.py`: 66 checks** (21 new). `ASMPRJ019`-`023`: a wasm RID with 0.3.0
    (info: a `main` build in a local feed is also 0.3.0), a browser program, a libc module, a
    define with a value, a pattern in a module's exports. `ASMWASM001`-`016`, for each `.s`
    source a wasm RID selects: an assembler constant, a data label without `ENDDATA`, a bare
    `.text`, `.int32` lists, `.bss`/`.rodata`, `PROTO` or a function macro inside a function,
    a function without `ENDFUNCTION`, an untyped `select`, `return_call` in code .NET links,
    `STRUCT`, a call to a function llvm-mc has not seen, unaligned WASI data, a `PROTO` that
    lowers to another wasm signature, a `PROTO` for a `LOCAL_FUNCTION` or for nothing, a
    float constant llvm-mc refuses or rounds to f32 unannounced. The source selection knows
    the wasm qualifiers (`ASMSRC014` for `x.wasm.asm`, `ASMSRC016` for a wasm RID with no
    qualified source). Checked against AsmSdk's own wasm test projects: every deliberately
    wrong one is flagged, every good one is clean.
  - **`new_asmproj.py`:** `--rids browser-wasm;wasi-wasm` writes a `.wasm.s` library (with
    `PROTO` lines when every RID is wasm), `--kind exe --rids wasi-wasm` a WASI command; a
    browser program, a libc module, and a WASI program beside native RIDs are refused.
    Built with a `main` build: all four kinds.
  - **`inspect_output.py`:** WebAssembly modules, WASI commands, objects and archives, read
    in Python without llvm-readobj: exports, imports, memory, custom sections and the
    `asmapi` records; `--expect-import`, `--expect-type module|command`.
  - **Evals:** `task-wasm-library` (a library with `sum_i32` and its PROTO line), its
    graders, a right answer and two wrong ones, and a build-check branch that runs the
    module in Node with no imports. The controls passed and failed as named, with a `main`
    build in the feed.
  - **Tests:** 31 (wasm fixtures for every new check, the wasm scaffolds lint clean, the
    inspector on a real WASI command and archive, the float rule on llvm-mc's measured
    answers).
  - **Follows AsmSdk's round of 2026-11-25** (the owner's choices for the problems found on the
    way): ASM0054's fix by the app's shape, since SDK 11.0.100's `wasm-tools-net10` built and
    ran a `Microsoft.NET.Sdk.WebAssembly` app with asm code and stopped only the
    `Microsoft.NET.Sdk` + `browser-wasm` shape (the earlier text said every `net10.0` browser
    app); the SDK's `WasmDebugLevel` default for browser builds (`0` in Release, `-1` in Debug);
    and `ASM0055`, the warning for a build that sets `RunAOTCompilation`. In
    `references/webassembly.md` and the `SKILL.md` footgun rows.
  - **Follows AsmSdk's Wasm Demos (2026-11-26)**, whose hand-written kernels ran into llvm-mc's
    float operands: `ASMWASM015` (error) for one it refuses and `ASMWASM016` (warning) for an
    f32 one it rounds without a word, each with the instruction rewritten in literals it reads
    exactly. The rule, measured on llvm-mc 23.1.5: a float operand is read as a double through
    APFloat, which refuses what it cannot prove exact, so a decimal passes only when it is a
    double whose significant digits fit in 63 bits (`2^-27` written out in full passes with
    63, `7 * 2^-26` fails with 64, `0.4199999868869781494140625` with 82), a hex float when it
    is a double; an integer is "invalid operand for instruction", `inf` an unknown name
    (`infinity` is known), and a `0` that no point follows (`06.5`) starts an octal integer
    for the lexer. On 9,000 random literals, as `f32.const` and `f64.const`, every acceptance
    and every stored bit matched the rule, and each of the 7,388 suggested replacements
    assembled to the nearest value. Also the `local.tee` leftover ("type mismatch, expected []
    but got [v128]" at `end_loop`). In `references/webassembly.md` (a float-constants note,
    footgun rows, diagnostics) and `SKILL.md` (a recipe line, a footgun row).

## 2026-11-21

### Changed

- **`asmsdk` 0.3.0, for AsmFoundation.Sdk 0.3.0:** seven runtime identifiers (x86-64 and
  ARM64 on Windows, Linux and macOS, plus musl on x64), NASM for x64 and GNU syntax for
  ARM64. It is released together with the SDK, and has no compatibility layer either:
  - **the skill** is rewritten for RIDs. It covers:
    - one source for every OS through `asmsdk.inc` and `asmsdk-gnu.inc`;
    - the per-OS NASM rules: what macho64 and win64 reject, measured directive by
      directive;
    - DLL exports;
    - each OS's C library;
    - .NET consumers by RID, with publishing (single file, NativeAOT);
    - `BinariesCopyPath` (where a .NET project keeps the asm libraries: presets or a folder
      with `{rid}`, on a reference, a `PackageReference` or as a property), the generated
      fallback loader for NativeAOT, and `PrivateAssets="all"` packing the binaries into a
      .NET library's package (and what an app that references such a library by project
      gets);
    - a static library linked into a packed library, which stays a package dependency
      (`NU1101` for every consumer) unless its reference is `PrivateAssets="all"`;
    - packages per RID;
    - the `ASM0010`-`ASM0082` errors;
    - 0.2.0's removed `AsmTargetRid` and `AsmFormat`.
  - **the references** were regenerated from the 0.3.0 documentation site, keeping the
    *verified* markers whose facts did not change. A new `platforms.md` covers the RIDs, the
    source selection and the helper includes. Data that no image may export gets a
    declaration per OS, measured with libraries for three RIDs;
  - **`check_asmproj.py`** has 45 checks and judges each source for the OSes it builds:
    - the project's RIDs, or its referencing projects' RIDs;
    - the file-name qualifier, chosen as the SDK chooses;
    - the `%ifdef WINDOWS`/`LINUX`/`MACOS` guards.
    New: `ASMPRJ015`-`018` (RIDs, target framework), `ASMSRC014`-`017` (source selection),
    `ASMSRC018`-`020` (what each format's NASM rejects), `ASMSRC021` (a plain `global` no DLL
    exports, unless the other OSes hide it), `ASMSRC022` (a symbol hidden on one OS and
    exported on another). The C library check reads each OS's list from the SDK package.
    `-Bsymbolic` retired the within-library PLT findings and `ASMREF002`;
  - **`new_asmproj.py`** writes `RuntimeIdentifiers` (every RID the kind can build, or
    `--rids`), and starter sources for both CPUs that assemble and link on every OS.
    Every kind and framework was built for all its RIDs;
  - **`inspect_elf.py` is now `inspect_output.py`:** ELF, PE and Mach-O images and static
    libraries;
  - **the evals** name 0.3.0, and `build_check.py` builds every RID a task names. It reads
    each library's exports (ELF, PE, Mach-O) and has a `--controls` self-test.
    `task-port-to-every-os` replaces `task-fix-pic-link-errors`, whose link errors 0.3.0's
    `-Bsymbolic` removed. New `evals/controls/` hold a right and wrong answers per task, and
    `tests/test_evals.py` checks graders, prompts and the linter against them in CI. The
    committed results are still plugin 0.1.0's against SDK 0.1.0.

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
