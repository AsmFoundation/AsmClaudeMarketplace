# WebAssembly: browser-wasm and wasi-wasm

> **Since AsmFoundation.Sdk 0.4.0.** 0.3.0 stops a `browser-wasm` or `wasi-wasm` build with
> **ASM0011**: a project with a wasm RID needs 0.4.0 or later. The guide is
> <https://asmfoundation.github.io/AsmSdk/guide/webassembly.html>.

Every fact marked *verified* was measured with the bundled LLVM 23.1.5 (llvm-mc, wasm-ld,
llvm-ar), .NET 10.0.15, Node 22 and wasmtime 39.

## Contents

1. [The two RIDs and what they build](#the-two-rids-and-what-they-build)
2. [Sources](#sources)
3. [Writing it](#writing-it)
4. [PROTO on WebAssembly: the C# bindings](#proto-on-webassembly-the-c-bindings)
5. [Using the outputs](#using-the-outputs)
6. [Templates](#templates)
7. [Footguns (verified)](#footguns-verified)
8. [Diagnostics](#diagnostics)
9. [Verify the outputs](#verify-the-outputs)

## The two RIDs and what they build

| RID | Runs in | `Library` | `StaticLibrary` | `Exe` |
|---|---|---|---|---|
| `browser-wasm` | browsers, Node, any JavaScript host; .NET browser apps (Blazor) | `name.wasm` (a module exporting its functions and `memory`) + `name.a` (the archive .NET links) | `name.a` | none: **ASM0017** |
| `wasi-wasm` | wasmtime and other WASI hosts; .NET WASI apps | `name.wasm` + `name.a` | `name.a` | `name.wasm`, a WASI command entered at `_start` |

- No `lib` prefix: both files are named after `AssemblyName`.
- Outputs: `bin/<Configuration>/<tfm>/<rid>/` as for every RID (`freestanding` by default).
- The bundled wasm-ld links them on every build machine; nothing to install for the asm side.
- A `libc` `Library` or `Exe` is **ASM0016** (the bundled wasm-ld links no C library). A `libc`
  `StaticLibrary` is fine: the .NET app that links it brings Emscripten's or wasi-libc.

## Sources

| File | Builds |
|---|---|
| `name.wasm.s` | both wasm RIDs |
| `name.browser.s`, `name.browser-wasm.s` | `browser-wasm` |
| `name.wasi.s`, `name.wasi-wasm.s` | `wasi-wasm` |

- **No unqualified file builds WebAssembly.** An unqualified `.s` is ARM64 code and an `.asm` is
  x86-64 code. A wasm RID with no qualified source is **ASM0023**; `kernel.wasm.asm` (NASM named
  for wasm) is **ASM0021**.
- The closest qualifier wins, as for every RID: `io.wasm.s` serves both RIDs unless `io.wasi.s`
  replaces it for WASI. One project can hold `crc.asm` (x64), `crc.s` (ARM64) and `crc.wasm.s`.
- The syntax is LLVM's WebAssembly assembly (what clang emits for `wasm32`), read by llvm-mc.
  ImplicitUsings puts `asmsdk-wasm.inc` in front of every wasm source.

## Writing it

WebAssembly is a stack machine: instructions pop their operands and push their result.
Parameters are locals `0..n-1`; `.local i32, i64` right after `FUNCTION` adds more. Control flow
is structured (`block`, `loop`, `if`/`else`/`end_if`, `br <depth>`, `br_if`): there are no
labels to jump to. Every function has a type, so the macros take a signature.

| Macro | Writes | Use |
|---|---|---|
| `FUNCTION name, (i32, i32) -> (i32)` | its own `.section .text.name`, `.globl`, `.type`, label, `.functype` | an exported function (llvm-mc's wasm writer requires a section per function) |
| `LOCAL_FUNCTION name, sig` | the same, no `.globl` | this file only |
| `HIDDEN_FUNCTION name, sig` | the same, `.hidden` | the project's files and the archive's users; no module exports it |
| `ENDFUNCTION name` | `end_function` | closes the function; llvm-mc checks the stack holds just the results |
| `IMPORT_FUNCTION module, name, sig` | `.functype` + `.import_module` + `.import_name` | a host function: `env` (JavaScript's import object) or `wasi_snapshot_preview1` |
| `EXTERN_FUNCTION name, sig` | `.functype` | before calling a function of another file, an archive, or further down |
| `CALL name` / `TAILCALL name` | `call` / `call` + `return` | `TAILCALL` is not `return_call` (footgun below) |
| `RODATA`, `DATA`, `BSS` | `.section .rodata` / `.data` / `.bss` with `,"",@` | the bare directives do not exist in the wasm parser |
| `ENDDATA name` | `.size name, . - name` | after every data label's last byte |
| `ADDRESS label` | `i32.const label` | a data label's address (an offset into linear memory) |
| `PROTO <C prototype>` | an `asmapi` record | the C# bindings; before its `FUNCTION`, never inside one |

A library function and a WASI command (*verified*: both build and run):

```asm
PROTO int32_t sum_i32(const int32_t* values, int32_t count)
FUNCTION sum_i32, (i32, i32) -> (i32)
    .local i32                  // 2: the total
    block
    loop
        local.get 1
        i32.eqz
        br_if 1                 // count == 0: leave the block
        local.get 2
        local.get 0
        i32.load 0              // *values (any alignment loads; aligned is faster)
        i32.add
        local.set 2
        local.get 0
        i32.const 4
        i32.add
        local.set 0
        local.get 1
        i32.const 1
        i32.sub
        local.set 1
        br 0                    // next iteration
    end_loop
    end_block
    local.get 2
ENDFUNCTION sum_i32
```

```asm
IMPORT_FUNCTION wasi_snapshot_preview1, fd_write, (i32, i32, i32, i32) -> (i32)
IMPORT_FUNCTION wasi_snapshot_preview1, proc_exit, (i32) -> ()

FUNCTION _start, () -> ()
    i32.const 1                 // standard output
    ADDRESS iov
    i32.const 1                 // one iovec
    ADDRESS written
    CALL fd_write
    drop
    i32.const 0
    CALL proc_exit
ENDFUNCTION _start

    DATA
    .p2align 2                  // WASI refuses misaligned pointers
iov:
    .int message
    .int .Lmessage_end - message
ENDDATA iov
written:
    .int 0
ENDDATA written

    RODATA
message:
    .ascii "hello from WebAssembly\n"
.Lmessage_end:
ENDDATA message
```

- **Defines:** every wasm source sees `WASM`, `BROWSER` or `WASI`, `FREESTANDING` or `LIBC`,
  `DEBUG` or `RELEASE`, and `DefineConstants`; `.ifdef WASI` chooses WASI or JavaScript imports.
  They arrive as labels, not constants, so a define with a value (`LEVEL=3`) is **ASM0018**.
- **Features:** the SDK passes `-mattr=+simd128,+tail-call`; LLVM's default CPU adds bulk memory,
  multivalue, mutable globals, non-trapping float-to-int, reference types and sign extension.
  `<AsmLlvmMcFlags>-mattr=+relaxed-simd</AsmLlvmMcFlags>` adds one. No `target_features` section
  is written, so a module needs a feature only where its code uses it.
- **Float constants** (`f32.const`, `f64.const`, the lanes of `v128.const 0.5, 1.0, 1.5, 2.0`):
  llvm-mc reads each as a double and refuses any it cannot prove exact. A short exact decimal
  (`1.0`, `0.5`, `3.75`, `1e3`) or a hex float (`0x1.ae147ap-2`, which is 0.42 as an f32, the
  form llvm-mc prints) assembles; `1`, `0.42`, `0.1`, `inf` and `06.5` do not. An f32 constant
  with more precision than an f32 is rounded without a word (*verified* on 9,000 random
  literals; the rule is in the footguns). `check_asmproj.py` prints the exact replacement
  (**ASMWASM015**, **ASMWASM016**).

## PROTO on WebAssembly: the C# bindings

```asm
PROTO int32_t add_ints(int32_t a, int32_t b)
FUNCTION add_ints, (i32, i32) -> (i32)
    local.get 0
    local.get 1
    i32.add
ENDFUNCTION add_ints
```

- `PROTO` and every function macro write text records into the object's `asmapi` custom section;
  the SDK reads them per RID, as it reads `.asmapi` from native objects.
- **Exact check (ASM0132):** the PROTO's C types, lowered as clang does for `wasm32`, must equal
  the `FUNCTION` signature: pointers, function pointers, `bool`, `char`, integers of 32 bits or
  fewer, `size_t`, `intptr_t` -> `i32`; `int64_t`, `uint64_t` -> `i64`; `float` -> `f32`;
  `double` -> `f64`; a `void` return -> no result.
- **One API for every RID (ASM0133):** a library for `linux-x64` and `browser-wasm` declares the
  same `PROTO` lines in its `.asm` and its `.wasm.s`.
- **ASM0131:** a `PROTO` for no function the image offers (none of that name, a
  `LOCAL_FUNCTION`, or a `HIDDEN_FUNCTION` of a module).
- **Placement guard:** a `PROTO` or `FUNCTION` between `FUNCTION` and its `ENDFUNCTION` stops the
  build: `error: PROTO and the function macros go between functions: f has no ENDFUNCTION yet`,
  reported at `<instantiation>`; the next `note: while in macro instantiation` names the line.
  Why: llvm-mc's wasm parser has no `.pushsection`, and a record written inside a body took the
  rest of the body with it (*verified*: the module linked without the function's `end`).
- wasm-ld keeps `asmapi` in the module even with `--strip-all` (*verified*); JavaScript reads it
  with `WebAssembly.Module.customSections(module, "asmapi")` (records split on `\0`).
- `STRUCT` lines are not read from wasm sources yet (an error): their offsets would be assembler
  constants, which wasm objects cannot hold.

## Using the outputs

### A .NET WebAssembly app

```xml
<ItemGroup>
  <ProjectReference Include="../Calc/Calc.asmproj" />   <!-- or a PackageReference to its package -->
</ItemGroup>
```

```csharp
[LibraryImport("Calc")]   // the asm project's AssemblyName, as on every platform
internal static partial int add_ints(int a, int b);
// or, with PROTO lines, the generated bindings: Calc.Add.AddInts(40, 2)
```

- The asm project builds for the app's RID; its archive becomes a `NativeFileReference` that the
  app's native build links into `dotnet.native.wasm` (Emscripten) or the WASI app (wasi-sdk).
- An asm library reached through a .NET library (app -> `Crc32C.Net` -> `Crc32C.asmproj`) is
  linked the same way; nothing is copied, a wasm app deploys no native file.
- **The app needs .NET's native wasm build for its own .NET version:** `wasm-tools` (browser) or
  `wasi-experimental` + WASI SDK 25.0 in `WASI_SDK_PATH` (WASI, .NET 10), on the SDK of that
  .NET. On a later SDK it depends on how the app is made (*verified* with SDK 11.0.100 and
  `wasm-tools-net10`):
  - `Microsoft.NET.Sdk.WebAssembly` (`wasmbrowser`, Blazor WebAssembly): builds and runs with
    `dotnet workload install wasm-tools-net10`, asm code included;
  - `Microsoft.NET.Sdk` + `RuntimeIdentifier` `browser-wasm` (`wasmconsole`, `asmwasmapp`,
    `Crc32C.Browser`): .NET's own targets stopped every `net10.0` one, even with no asm code
    ("WasmAssembliesToBundle item is empty"), so it needs a .NET 10 SDK (`global.json`);
  - WASI: SDK 11's WASI build serves only `net11.0`, so a .NET 10 SDK.
  Without the workload .NET would build plain IL without the asm code, so the SDK stops with
  **ASM0054**, whose fix follows the app's shape. In CI, for the last two, install the .NET 10
  SDK into a folder of the runner's own (`DOTNET_INSTALL_DIR`): GitHub's Windows images default
  to SDK 11.0.100.
- `dotnet run` of a browser console app goes through `WasmAppHost`, which needs a
  `runtimeconfig.template.json`:
  `{ "wasmHostProperties": { "perHostConfig": [ { "name": "node", "js-path": "main.mjs", "host": "nodejs" } ] } }`
  (else "no perHostConfigs found").
- **Debug level (the SDK's default since 0.4.0):** .NET writes `debugLevel: -1` into every
  browser *build*, and in Chromium and Firefox its runtime then runs the debugger: the
  interpreter stays unoptimized and the jiterpreter compiles nothing (*verified*: C# 5-7 MB/s
  with 0 traces, 134 MB/s with `debugLevel: 0`, in headless Chrome; Node never enables the
  debugger and hides this). The SDK sets `WasmDebugLevel` for the build of a browser app that
  links asm code, by project reference or package: `0` in Release, `-1` in Debug; the app's own
  value wins, other configurations and every publish keep .NET's (*verified*: 128-158 MB/s with
  the default, 11.6-12.2 MB/s with `-p:WasmDebugLevel=-1`). So time a Release build or a
  publish, never a Debug build.
- AOT (`RunAOTCompilation=true`) happens at `dotnet publish` only; a build with it still
  interprets (*verified*: a byte-identical `dotnet.native.wasm`), and the SDK says so:
  **ASM0055** (warning). Time a publish; `<NoWarn>$(NoWarn);ASM0055</NoWarn>` when the property
  is there for the publishes (Blazor). Never suggest `RunAOTCompilationAfterBuild` to silence
  it: it compiled all 174 untrimmed assemblies (~5 min), then .NET's `llvm-size` failed (MSB3073).

### JavaScript, Node, WASI hosts

```js
const { instance } = await WebAssembly.instantiate(bytes, { env: { log_i32: console.log } });
instance.exports.add_ints(40, 2);   // 42; memory is instance.exports.memory
```

- Without an `ExportsFile` a module exports every `FUNCTION` (never `HIDDEN_`/`LOCAL_`); with one,
  exactly the names listed (patterns: **ASM0030**), plus `memory`.
- `LinkerArg` reaches wasm-ld: `--initial-memory=<bytes>`, `-z stack-size=<bytes>` (64 KiB
  default), `--import-memory`, `--allow-undefined`.
- A WASI program: `wasmtime run --dir . name.wasm args`; `dotnet run -r wasi-wasm -- args` does
  that when wasmtime is on `PATH` (`AsmRunIn=Wasi` forces it) and returns the `proc_exit` code.
  WASI opens files only under preopened folders (fd 3 is the first); wasmtime 39 answers
  EPERM (63) for a name outside them, and a directory opens and fails at `fd_read` (EBADF), so
  ask `fd_filestat_get` first.

### Another asm project, and packages

- An asm project links a wasm library's **archive**, never its module (no shared libraries in
  wasm). `AsmProduceStaticLibrary` defaults to `true` for a wasm `Library`; the archive holds the
  library's objects and the static libraries it linked.
- `dotnet pack`: `native/<rid>/<tfm>/name.a` (consumers link it; the package props give a .NET
  wasm app of that RID a `NativeFileReference`) and `native/<rid>/<tfm>/name.wasm`. Nothing under
  `runtimes/`.

## Templates

- `dotnet new asmwasm -n Calc`: a library for both wasm RIDs with `add.wasm.s` and `run.mjs`
  (`node Calc/run.mjs` prints `add_ints(40, 2) = 42`).
- `dotnet new asmwasmapp -n Calc`: `Calc.slnx` with `Calc.Native` (browser-wasm) and `Calc.App`
  (a .NET browser-wasm console app with `main.mjs` and the runtimeconfig above).

## Footguns (verified)

| Write | Not | Because |
|---|---|---|
| the number itself, or a macro that emits `i32.const 4096` | `.set N, 4096`, `.equ`, `N = 4096` (even `.L` names) | llvm-mc's wasm writer crashes: "absolute addressing not supported!" (**ASM0019**) |
| a label defined once, or `.purgem` + a new macro | `.set` redefinition | "LLVM ERROR: .set redefinition is not supported" |
| `ENDDATA name` after every data label | a data label without a size | "data symbols must have a size set with .size" (**ASM0019**) |
| `FUNCTION` (it switches sections) | a bare `.text` after `DATA` | `.text` does nothing in the wasm parser: the code stays in the data section |
| `.p2align 2` before 32-bit data | unaligned data passed to WASI | wasmtime: "Pointer not aligned to 4" (Node's WASI accepted it) |
| `.int 1, 2`, `.byte`, `.short`, `.quad` | `.int32 1, 2`, `.word` | `.int8`-`.int64` take one value ("Expected EOL"); `.word` does not exist |
| `BSS`, `RODATA` | `.bss`, `.rodata` | "unknown directive" |
| `if i32` ... `else` ... `end_if` | an untyped `select` | llvm-mc 23.1.5's type checker: "type mismatch, expected [i32] but got [i32, i32]" at `ENDFUNCTION` |
| `local.set` | a `local.tee` whose value nothing takes | the value left on the stack fails the block's type: "type mismatch, expected [] but got [v128]" at its `end_loop` or `end_block` |
| `f32.const 1.0`, `0.5`, `1e3`, or a hex float: `f32.const 0x1.ae147ap-2` for 0.42 | `f32.const 1`, `0.42`, `0.1`, even the exact `0.4199999868869781494140625` | llvm-mc reads a float operand as a double and refuses what it cannot prove exact: an integer is "invalid operand for instruction"; a decimal must be a double whose significant digits fit in 63 bits (APFloat's first pass), else "Cannot parse real"; a hex float must be a double (**ASMWASM015** prints the replacement) |
| `infinity`, `-infinity`, `nan`; `0.5`, `6.5` | `inf`; `00.5`, `06.5`, `0e0` | `inf` is no name the parser knows; a `0` that no point follows starts an octal integer for the lexer ("Expected ,, instead got: .5") |
| the f32 it stores (`16777216.0`, `0x1.ae147ap-2`), or `f64.const` | an f32 constant with more precision than an f32: `16777217.0`, `0x1.ae147ae147ae1p-2`, `0x1p200` | llvm-mc rounds the double to the nearest f32 without a word: 16777216.0, 0x1.ae147ap-2, infinity (**ASMWASM016**) |
| `TAILCALL` in code a .NET app links | `return_call` | .NET 10's wasm-opt validates without tail calls: "return_call* requires tail calls" |
| `EXTERN_FUNCTION f, sig` before the call | a call to a function llvm-mc has not seen | "symbol f: missing .functype" |
| `IMPORT_FUNCTION env, f, sig` | an undefined call | wasm-ld "undefined symbol: f" |
| `i32.const 0x82F63B78` is fine | worrying about signedness | llvm-mc wraps it to the same 32 bits as `-2097792136` |

## Diagnostics

| Code / text | Cause | Fix |
|---|---|---|
| ASM0011 | AsmFoundation.Sdk 0.3.0 and a wasm RID | AsmFoundation.Sdk 0.4.0 or later |
| ASM0016 | `libc` module or WASI program | `freestanding`, or a `StaticLibrary` for a .NET app |
| ASM0017 | `Exe` for `browser-wasm` | a `Library`, or the program for `wasi-wasm` |
| ASM0018 | a define with a value | define the name alone |
| ASM0019 | llvm-mc's wasm writer stopped ("LLVM ERROR: ...") | a constant, a data label without `ENDDATA`, a function outside `FUNCTION` |
| ASM0021 | `.asm` qualified for wasm | `.wasm.s` |
| ASM0023 | wasm RID, no qualified source | `name.wasm.s`, or drop the RID |
| ASM0030 | pattern in a module's `ExportsFile` | exact names |
| ASM0054 | .NET wasm app without the native build of its .NET | the workload it names: on the app's own SDK `wasm-tools`/`wasi-experimental`; on a later SDK `wasm-tools-net10` for a `Microsoft.NET.Sdk.WebAssembly` app, a .NET 10 SDK (`global.json`) for a `Microsoft.NET.Sdk` browser app or a WASI app |
| ASM0055 (warning) | a *build* of a browser app with `RunAOTCompilation=true`: it interprets | time a `dotnet publish`; `NoWarn` it when the property is for publishes |
| ASM0131 / ASM0132 / ASM0133 | PROTO for no exported function / wrong wasm type / RIDs disagree | see PROTO above |
| `error: PROTO and the function macros go between functions` | PROTO or FUNCTION inside a body | move it above the `FUNCTION`; close with `ENDFUNCTION` |
| `error: Cannot parse real: 0.42`, or `invalid operand for instruction` on `f32.const 1` | a float operand llvm-mc cannot prove exact, or an integer | a short exact decimal or a hex float (footguns above; **ASMWASM015** names it) |
| `error: type mismatch, expected [] but got [v128]` at `end_loop` / `end_block` | a value left on the stack, often an unused `local.tee` | `local.set` |
| `no perHostConfigs found` | `dotnet run` of a browser app without the runtimeconfig template | add it |
| `MONO_WASM: Error loading symbol file dotnet.native.js.symbols: {}` (Node) | harmless | none |

## Verify the outputs

- `python scripts/inspect_output.py bin/Release/freestanding/browser-wasm/Calc.wasm`: imports,
  exports, memory, custom sections and the `asmapi` records; `--expect-export add_ints` for CI.
- `node -e "WebAssembly.instantiate(require('fs').readFileSync(process.argv[1])).then(m => console.log(m.instance.exports.add_ints(40, 2)))" Calc.wasm`
- `wasmtime run --dir . hello.wasm` for a WASI command.
