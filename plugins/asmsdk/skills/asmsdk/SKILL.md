---
name: asmsdk
description: Build, reference, package and release assembly with AsmSdk (the AsmFoundation.Sdk MSBuild SDK) - .asmproj projects that turn NASM (x64), GNU-syntax (ARM64) and LLVM WebAssembly sources into shared libraries, static libraries, programs and .wasm modules for ten runtime identifiers (win-x64, win-arm64, linux-x64, linux-arm64, linux-musl-x64, linux-musl-arm64, osx-x64, osx-arm64, browser-wasm, wasi-wasm) with dotnet build, run and publish them, share them as versioned NuGet packages, and call them from .csproj projects through C# bindings the SDK writes from PROTO and STRUCT lines (and C through a generated header). Use it whenever an .asmproj, AsmFoundation.Sdk, AsmFoundation.Toolchain, AsmFoundation.Templates (dotnet new asmlib, asmexe, asmstatic, asmnet, asmwasm, asmwasmapp) or an msbuild-sdks entry for assembly is involved, or the user wants to build, link, version, package, test, run or ship assembly with MSBuild, dotnet build, run, pack or publish, NuGet, a .sln or .slnx, or CI - including link errors such as "recompile with -fPIC", "undefined symbol", "unrecognised symbol type", "attempted static link of dynamic object", ASM0xxx errors (ASM0013, ASM0023, ASM0080, ASM0109 to ASM0112 after upgrading from 0.3.0, ASM0130 to ASM0149 for PROTO, STRUCT and the bindings), RuntimeIdentifiers and per-RID source files, ImplicitUsings, asmsdk.inc or asmsdk-gnu.inc, TargetFramework libc and the C library stand-ins, Windows DLL exports, Mach-O, single-file or NativeAOT publishing of an app that uses asm, PackAsTool, calling assembly from C# ([AsmLibrary], AsmBindings items) or Python, and WebAssembly - browser-wasm and wasi-wasm from .wasm.s sources (asmsdk-wasm.inc), .wasm modules for JavaScript, WASI programs in wasmtime, .NET WebAssembly apps (Blazor) that link asm, wasm-ld and ASM0054 - even when AsmSdk is not named. Not for MASM, CMake or Makefile builds, inline assembly in C, or questions about what an instruction does.
---

# AsmSdk: assembly projects on MSBuild and NuGet

AsmSdk is the AsmFoundation's project, dependency and build management for assembly. An
`.asmproj` is to assembly what a `.csproj` is to C#:

- `dotnet build` assembles and links it, once per runtime identifier (RID);
- `ProjectReference` and `PackageReference` share code between projects;
- `dotnet pack` turns it into a versioned NuGet package with every RID's binary;
- `dotnet run` starts a program, and `dotnet publish` writes it with the libraries it links;
- a `.csproj` that references it gets the binary of the platform it builds or runs for, and
  calls it through C# bindings the SDK writes from the library's `PROTO` and `STRUCT` lines.

One project builds **ten RIDs** from any build machine: the eight native ones, `win-x64`,
`win-arm64`, `linux-x64`, `linux-arm64`, `linux-musl-x64`, `linux-musl-arm64`, `osx-x64`,
`osx-arm64`, and WebAssembly's `browser-wasm` and `wasi-wasm`. x64 code is NASM (`.asm`); ARM64
code is GNU syntax (`.s`) for `llvm-mc`; WebAssembly code is LLVM's WebAssembly assembly in `.s`
files qualified for it (`name.wasm.s`). Restore downloads a bundled toolchain as a NuGet package
(NASM 3.02, plus LLVM 23.1.5's `llvm-mc`, `lld` as `ld.lld`, `lld-link`, `ld64.lld` and
`wasm-ld`, `llvm-ar` and `llvm-readobj`) for five build machines, so nothing needs to be
installed beyond the .NET SDK.

This skill documents **AsmFoundation.Sdk 0.4.0** (toolchain 0.2.0). Each behavior marked
*verified* was measured by building with an AsmSdk release and its bundled tools; the
references are the documentation site's 0.4.0 pages, whose statements are covered by AsmSdk's
end-to-end tests on five native build machines (Windows x64 and Arm, Linux x64 and ARM64, Apple
silicon). If `global.json` pins another version, check the SDK's site,
<https://asmfoundation.github.io/AsmSdk/> (or that release's `docs/asmproj.md`). The site has the
same facts written for people, so it is the page to link a user to.

**0.4.0 broke 0.3.0 projects on purpose, with no compatibility layer.** Each old name stops the
build with an error that shows the new line (`check_asmproj.py` reports them before a build):

| 0.3.0 | 0.4.0 |
|---|---|
| `<AsmSource Include/Remove="…" />` | `<Compile Include/Remove="…" />` (`ASM0110`) |
| `<AsmInclude Include="…/*.inc" />` | `<None Include="…/*.inc" />`; other files a source reads: `CustomAdditionalCompileInputs` (`ASM0111`) |
| `EnableDefaultAsmItems` | `EnableDefaultCompileItems` (`ASM0112`) |
| `<AsmLinkLibrary Include="…" />` | `<NativeLibrary Include="…" />` (`ASM0109`); a package packed with 0.3.0 must be packed again |
| no `RuntimeIdentifiers`: `ASM0010` | the build machine's RID; `ASM0013` warns a pack or portable publish that ships that RID alone |
| `default rel`, `%include "asmsdk.inc"`, Linux's `.note.GNU-stack` in every source | `ImplicitUsings` (on) writes them; sources that write them still build; a source that relied on NASM's implicit `default abs` writes `default abs` |
| `<AsmFlags>-w-label-orphan</AsmFlags>` | `<NoWarn>label-orphan</NoWarn>` |
| `x.wasm.s`, `x.browser.s`, `x.wasi.s`: ARM64 sources | WebAssembly sources |
| a shared library's reference to a static library: a package dependency | private by default (`PrivateAssets="all"`); `PrivateAssets="none"` keeps it |
| `FUNCTION` after `[section .foo]` stays in `.foo` | it goes back to the last `section` line's section (`__SECT__`) |

0.3.0 made `RuntimeIdentifiers` the platform list and put outputs in
`bin/<Configuration>/<tfm>/<rid>/`; 0.2.0 renamed every 0.1.0 setting to .NET's own
(`ASM0100`-`ASM0108`). The [changelog](https://github.com/AsmFoundation/AsmSdk/blob/main/CHANGELOG.md)
has all three migration tables.

`<this-skill>` below stands for the skill's base directory, which is shown when the skill
loads. The scripts live in its `scripts/` folder, and the references in `references/`.

## Orient yourself first

1. **Find the pieces:**
   - `*.asmproj` (and its `RuntimeIdentifiers`, if any);
   - `global.json` (`"msbuild-sdks": { "AsmFoundation.Sdk": "<version>" }`), or a version on
     the project's first line (`<Project Sdk="AsmFoundation.Sdk/0.4.0">`);
   - `*.slnx` / `*.sln`;
   - `nuget.config`;
   - `Directory.Build.props` and `Directory.Packages.props`.
2. **Lint before you reason:** `python <this-skill>/scripts/check_asmproj.py <repo-or-project>`
   reports the footguns below, with the file, line and fix, judged for the platforms each
   source is built for. It reads files only.
3. **Build:** `dotnet build`. Each RID's inner build prints `<Project> -> <output>`. A NASM
   or `llvm-mc` error is reported at its file and line; an `lld` error names the object.
4. **Inspect the outputs:** `python <this-skill>/scripts/inspect_output.py <file>` (ELF, PE,
   Mach-O or WebAssembly) rather than reasoning about them (see
   [Verify the outputs](#verify-the-outputs)).

## The model in one screen

```text
global.json            { "msbuild-sdks": { "AsmFoundation.Sdk": "0.4.0" } }
nuget.config           only when the SDK or your packages come from a private or local feed
App.slnx               <Project Path="Crc/Crc.asmproj" Type="13B669BE-BB05-4DDF-9536-439F39A36129" />
Crc/Crc.asmproj        <Project Sdk="AsmFoundation.Sdk"> ... <RuntimeIdentifiers>...</RuntimeIdentifiers>
Crc/include/*.inc      public include files: referencing projects and package consumers get them
Crc/**/*.asm           NASM sources (Compile items): the x64 RIDs
Crc/**/*.s             GNU-syntax sources (llvm-mc): the ARM64 RIDs
Crc/x.wasm.s           LLVM WebAssembly sources: browser-wasm and wasi-wasm
Crc/x.linux.asm        a file-name qualifier narrows a source to some RIDs (most specific wins)
```

| `OutputType` | Windows | Linux | macOS | WebAssembly | Notes |
|---|---|---|---|---|---|
| `Library` (default) | `name.dll` (+ `name.dll.lib`) | `libname.so` | `libname.dylib` | `name.wasm` + `name.a` | position-independent code required |
| `StaticLibrary` | `name.lib` | `libname.a` | `libname.a` | `name.a` | |
| `Exe` | `name.exe` | `name` | `name` (`libc` only) | `name.wasm` (`wasi-wasm` only) | `_start` (`freestanding`) or `main` (`libc`) |
| `Objects` | objects in `obj/` | | | | linked by a referencing asm project |

- Every output lands in `bin/<Configuration>/<tfm>/<rid>/`, `<tfm>` being `freestanding` or
  `libc`. `dotnet build -o <folder>` gives each RID `<folder>/<rid>/`.
- `<name>` is `AssemblyName`. It defaults to the project name, as in .NET. **`PackageId`
  defaults to it too**, so two projects that share an `AssemblyName` (a static and a shared
  build of one library) need a `PackageId` each, or restore fails with "Ambiguous project name".
- `AsmProduceStaticLibrary=true` also writes the static library next to a shared one (the
  default for a WebAssembly `Library`, whose archive is what .NET apps link).
- A library with `PROTO` or `STRUCT` lines also gets `name.api.json` and `name.h` (the C header)
  beside each RID's binary and in `bin/<Configuration>/<tfm>/`.

**Choosing RIDs**, the first that gives any: `-r <rid>`; the RIDs a referencing project asks
for (`<ProjectReference ... RuntimeIdentifiers="linux-x64;win-x64" />`, a .NET app's RID); the
project's own `<RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>` (or one
`<RuntimeIdentifier>`); otherwise the build machine's own RID. A `dotnet pack` that would carry
that default RID alone, or a portable publish or pack of a .NET app that references it, warns
`ASM0013` with the line to add (*verified*). `ASM0010` stops only a build machine that is none
of the eight. A RID outside the ten: `ASM0011`; one the project does not list: `ASM0012`.

**Sources per RID:** the sources are `Compile` items (every `**/*.asm` and `**/*.s`); every other
file is a `None` item, and each `None` item ending in `.inc` is a dependency of every source.
The extension is the language (`.asm` NASM, x64 only; `.s` GNU syntax for llvm-mc). A qualifier
before the extension narrows a file: a RID (`x.win-x64.asm`), an OS family (`win`, `linux`,
`linux-musl`, `osx`), `unix`, a CPU (`x64`, `arm64`), or WebAssembly (`wasm`, `browser`, `wasi`;
no unqualified file builds wasm). Among the files of one name, the most specific wins per RID
(RID 50, `linux-musl` 40, OS 30, `unix` 20, CPU 10, none 1). Errors: `ASM0020` (a tie),
`ASM0021` (a NASM file for ARM64 or WebAssembly only), `ASM0023` (a listed RID no source builds:
typically NASM only, with an ARM64 RID listed), `ASM0024` (a source listed twice), `ASM0025` (a
`Compile` item that is not `.asm` or `.s`).

**`ImplicitUsings`** (on by default) puts the platform layer in front of every source: NASM gets
a pre-include with `%include "asmsdk.inc"`, `default rel`, Linux's empty `.note.GNU-stack`
section and `section .text`; a GNU-syntax source is assembled through a wrapper in `obj/` that
includes `asmsdk-gnu.inc` first (`asmsdk-wasm.inc` for WebAssembly), with a line marker so
messages and DWARF name your file. A source is just code. `<ImplicitUsings>disable</ImplicitUsings>`
gives raw NASM back; the [NASM rules](#nasm-rules-that-decide-whether-code-links) then apply
to every file again.

**Runtimes are target frameworks, on every OS.** `freestanding` (the default) links no C
library: Linux code makes system calls, Windows code calls kernel32 (linked into every Windows
output), and macOS has no freestanding programs (`ASM0015`; libraries are fine). `libc` links
the platform's C library through SDK-written stand-ins, so no sysroot or platform SDK is
needed: glibc 2.34+ or musl (Linux), libSystem (macOS), the Universal C Runtime `ucrtbase.dll`
(Windows). A `libc` program enters `main`. WebAssembly is `freestanding` only (`ASM0016`).

- `<TargetFrameworks>freestanding;libc</TargetFrameworks>` builds both, like a multi-targeted
  `.csproj`.
- NuGet enforces what links: a `libc` project may reference `freestanding` code, but a
  `freestanding` project that references `libc`-only code fails at restore (`NU1201` for a
  project, `NU1202` for a package). A .NET project gets the `libc` build of a project that
  targets both (*verified*).

**Configurations and symbols, as in C#:**

- `Debug` defines `DEBUG` and writes debug information (DWARF; CodeView and a `.pdb` on
  Windows). `Release` defines `RELEASE` and writes none (`<DebugSymbols>true</DebugSymbols>`
  adds it). Release builds are byte-identical in any checkout folder (*verified*).
- Every build also defines `FREESTANDING` or `LIBC` (*verified*), the OS (`WINDOWS`, `LINUX`,
  `MACOS`, plus `MUSL`; WebAssembly `BROWSER` or `WASI`, and `WASM`) and the CPU (`X64`,
  `ARM64`); a program defines `ASMSDK_EXECUTABLE`, and a project with an `ExportsFile`
  `ASMSDK_EXPORTS_FILE`. NASM tests them with `%ifdef`, llvm-mc with `.ifdef`.
- `NoWarn`, `WarningsAsErrors` and `WarningsNotAsErrors` take NASM's warning names
  (`label-orphan`), as a `.csproj`'s take compiler codes; `TreatWarningsAsErrors` adds
  `-w+error`.

**Toolchain:** `AsmToolchain=Bundled` (the default) downloads `AsmFoundation.Toolchain.<host>`
during restore, for build machines `win-x64`, `win-arm64`, `linux-x64`, `linux-arm64` and
`osx-arm64`; any of them builds all ten RIDs. Intel Macs and musl hosts have no package
(`ASM0006`): `AsmToolchain=System` uses `nasm`, `llvm-mc`, a linker and `ar` from PATH, and
needs `AsmLinkerCommand` set to `lld-link`, `ld64.lld` or `ld.lld` for RIDs its GNU `ld` cannot
link (`ASM0005`).

## Recipes

### Start a project or a solution

The templates (the `AsmFoundation.Templates` package, released with the SDK under the same
version) create what `dotnet build`, `run` and `test` take as it is (*verified* by AsmSdk's
plug-and-play scenarios):

```sh
dotnet new install AsmFoundation.Templates
dotnet new asmnet -n Demo          # Demo.slnx: a C# app, the asm library it calls, xunit tests
cd Demo && dotnet run --project Demo.App && dotnet test
```

| Short name | Creates |
|---|---|
| `asmlib` | a shared library: `add.asm` (x64) and `add.s` (ARM64), with a `PROTO` line |
| `asmexe` | a `libc` program that `dotnet run` builds and runs |
| `asmstatic` | a static library with a public `include/` folder |
| `asmnet` | a `.slnx`: a C# app calling the library through its generated bindings, the library, xunit v3 tests (`--test-runner mtp-v2` default, or `vstest`) |
| `asmwasm` | a WebAssembly library (`add.wasm.s`) and a `run.mjs` that calls it from Node |
| `asmwasmapp` | a `.slnx`: a .NET `browser-wasm` app and the WebAssembly library it calls (needs the `wasm-tools` workload) |

- The projects name the SDK on their first line (`<Project Sdk="AsmFoundation.Sdk/0.4.0">`),
  so they need no `global.json`; `--sdk-version` picks another. MSBuild takes an exact version
  only: `*`, ranges and `latest` all fail.
- They list no `RuntimeIdentifiers`: they build for this machine until you list the platforms
  to ship. A name with a hyphen keeps it in files (`my-app.Native.asmproj`) and becomes
  `my_app` in the C# namespace, which the template names in an `AsmBindings` item.

Without the templates, `scripts/new_asmproj.py` scaffolds one project of any kind:

```sh
python <this-skill>/scripts/new_asmproj.py Hello --kind library --assembly-name hello --sln App.slnx
```

It writes `global.json` (when missing), the `.asmproj`, an `include/` file and starter sources
for every RID it builds, adds the project to the `.slnx` with the type GUID, and never
overwrites a file. Kinds are `library`, `static`, `exe` and `objects`; `--framework libc`
targets the C library; `--rids` picks the RIDs (default: every native RID the kind can build;
`--rids "browser-wasm;wasi-wasm"` writes a WebAssembly library); `--package-id`/`--version`
make the project packable.

By hand, the minimum is the project file and one source per CPU you target:

```xml
<Project Sdk="AsmFoundation.Sdk/0.4.0">
  <PropertyGroup>
    <AssemblyName>hello</AssemblyName>      <!-- hello.dll, libhello.so, libhello.dylib -->
    <RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>
  </PropertyGroup>
</Project>
```

- **`dotnet sln add` takes an `.asmproj`** and writes its type itself (the SDK sets
  `DefaultProjectTypeGuid`). In a `.slnx` written by hand, an `.asmproj` needs
  `Type="13B669BE-BB05-4DDF-9536-439F39A36129"`; without it, `dotnet build App.slnx` fails with
  `MSB4025 … ProjectType '' not found` (*verified*).
- **`dotnet add reference` refuses an `.asmproj`** ("incompatible targeted frameworks": the CLI
  does not know NuGet's `freestanding`/`libc` aliases, dotnet/sdk#57317). Write the
  `<ProjectReference Include="../Hello/Hello.asmproj" />` line.
- **In a classic `.sln`,** an entry needs the `Project("{13B669BE-…}") = …` line and
  `ProjectConfigurationPlatforms` lines for it. Without them, the build silently skips the
  project and still reports 0 errors (*verified*). Prefer `.slnx`.

### Write one source for every OS

With `ImplicitUsings` (the default), the platform layer is already there:

```nasm
extern memcpy

FUNCTION copy_bytes, 3, rbx         ; exported; 3 integer arguments; changes rbx
    mov     rbx, ARG1               ; rcx on Windows, rdi elsewhere
    sub     rsp, SHADOW_SPACE       ; one push (rbx) re-aligned the stack; Windows: 32-byte shadow space
    call    memcpy PLT              ; another library: wrt ..plt on Linux, nothing elsewhere
    add     rsp, SHADOW_SPACE
    RETURN                          ; restores rbx, then ret
ENDFUNCTION
```

- **`FUNCTION name [, nargs [, registers]]`** declares and exports (a `.drectve` export on
  Windows, a plain global on Linux and macOS), and saves the listed registers that this OS's
  convention makes callee-saved (`rdi`, `rsi`, `xmm6`-`xmm15` too on Windows).
  **`LOCAL_FUNCTION`** is file-local; **`HIDDEN_FUNCTION`** is global but exported from no
  image (use it for helpers other files or a static library's users call). `RETURN` restores
  and returns; `ENDFUNCTION` closes. In a program, `FUNCTION` exports nothing. The macros start
  with NASM's `__SECT__`: a function goes to the last `section` line's section (`.text` while
  the source named none), so a source without a `section` line links on Windows too.
- **ARM64 (`.s`):** AAPCS64 is the same everywhere (`x0`-`x7`, the result in `x0`); the macros
  of `asmsdk-gnu.inc` handle names and addressing: `FUNCTION`/`ENDFUNCTION name`,
  `CALL`/`TAILCALL`, `ADDRESS reg, label`, `RODATA`. Never touch `x18` (the platform register
  on Windows and macOS). On macOS every *variadic* argument goes on the stack, so `printf` is
  written per OS.
- **A file for one OS** (`x.linux.asm`, `x.win.asm`) may use that OS's own directives and
  system interface; `%ifdef WINDOWS` / `LINUX` / `MACOS` does the same inside one file.
- **`PROTO int32_t copy_bytes(void* dst, const void* src, size_t n)`** above a `FUNCTION`
  declares its C prototype for the C# bindings and the C header (see
  [Call assembly from .NET](#call-assembly-from-net)).

### Use an SDK version that is not on nuget.org

The SDK, its toolchain package and your own asm packages can come from a folder feed:

```xml
<configuration>
  <packageSources>
    <clear />
    <add key="local" value="artifacts/packages" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="local"><package pattern="AsmFoundation.*" /></packageSource>
    <packageSource key="nuget.org"><package pattern="*" /></packageSource>
  </packageSourceMapping>
</configuration>
```

- **Building that feed:** run `dotnet run toolchain/fetch.cs -- --rid <host-rid>` and
  `dotnet pack` in the AsmSdk repository, or download the packages from a release.
- **Package source mapping applies across `nuget.config` files.** A mapping in a parent
  folder hides any source that isn't mapped for a pattern (*verified*). Give every feed its
  own pattern.

### Call assembly from .NET

Add a `ProjectReference` from the `.csproj` to the `.asmproj`. The consumer targets reach the
.NET project through the asm project's implicit `AsmFoundation.Sdk` reference and treat it like
a package with a `runtimes/` folder.

**The generated bindings.** Give each export a `PROTO` line (and `STRUCT` lines for the structs
it takes):

```nasm
PROTO uint32_t crc_update(uint32_t crc, const uint8_t* data, size_t length)
FUNCTION crc_update, 3
```

A C# project for .NET 7 or later then calls it with nothing declared (*verified*):

```csharp
uint crc = Crc.Crc32.CrcUpdate(0, data);   // library "crc", source crc32.asm; a span overload too
```

- **The baseline** is a namespace named after the library (its `AssemblyName`, each dotted part
  in PascalCase), an internal static class per `.asm` file (folders as namespaces), the
  `STRUCT`s at its root, every function. A file with a function of its own name gives its class
  the suffix `Asm` (`answer.asm`'s `answer` is `Lib.AnswerAsm.Answer()`). The SDK writes it as
  source at build time (`obj/.../AsmBindings/<Namespace>.g.cs`); a package carries it, so its
  consumers need no AsmFoundation.Sdk. `AllowUnsafeBlocks` is set to `true` with bindings.
- **Shaping:** an `AsmBindings` item per library (`<AsmBindings Include="crc" Namespace="Acme.Crc"
  Nesting="Flat" ClassKind="Instance" Visibility="Public" />`, also `SpanOverloads`, `Virtual`,
  `Sealed`, `DefaultBindings`) or an `AsmBindings*` property for all (`ASM0146` for a value that
  is no option, `ASM0140` for an item that names no library). **`[AsmLibrary]` in code** turns
  the bindings generator on: `[assembly: AsmLibrary("crc", DefaultNamespace = …)]` reshapes the
  baseline, and `[AsmLibrary("crc", Files = ["crc32.asm"])]` on a `partial` class of the app's
  binds copies there. The code wins: a class's attribute, the library's assembly attribute, the
  global one, the `AsmBindings` item, the properties.
- **The checks:** `ASM0130` (a `PROTO`/`STRUCT` that does not parse, or C's `int`/`long`, which
  differ between platforms), `ASM0131` (no exported function of that name), `ASM0132` (the
  integer and pointer parameters differ from `FUNCTION`'s count), `ASM0133` (two RIDs declare it
  differently), `ASM0134`-`ASM0136`, and in C# `ASM0141`-`ASM0148`. The bindings need C# 11
  (`LangVersion`; `ASM0147`).
- **`<AsmGenerateBindings>false</AsmGenerateBindings>`** turns them off, for a project with its
  own imports. Without `PROTO` lines, declare the import yourself:

```csharp
[LibraryImport("crc", EntryPoint = "crc_update")]  // crc.dll, libcrc.so or libcrc.dylib
private static partial uint CrcUpdate(uint crc, ReadOnlySpan<byte> data, nuint length);
```

- **Portable build** (no RID): every RID the asm project builds, under `runtimes/<rid>/native/`,
  listed in `deps.json`; the .NET host loads the machine's own.
- **RID-specific build** (`-r linux-arm64`, or a `RuntimeIdentifier`): the one RID that serves
  it best by the .NET RID graph, copied flat beside the app. None fits: `ASM0040`, or the
  warning `ASM0049` and no library when the asm project sets
  `<OptionalOnUnlistedRuntimes>true</OptionalOnUnlistedRuntimes>` (for an app that copes).
- **Through a C# wrapper library** (app → `Crc.Net.csproj` → `Crc.asmproj`) the same: the .NET
  SDK adds the asm project to the app transitively. The wrapper itself builds portable.
- **Publishing:** `-r <rid>` puts the library beside the app; `PublishSingleFile` beside the
  single file, or inside it with `IncludeNativeLibrariesForSelfExtract=true` (the consumer
  targets mark asm libraries `AssetType=native`); `PublishAot` beside the native program,
  loaded at run time; trimming and `-t:PublishContainer` work as usual. Command-line publish
  switches (`-p:PublishAot=true`) do not reach the asm projects.
- **A static library inside a NativeAOT program:** a `ProjectReference` to a `StaticLibrary` is
  all a `PublishAot` project needs: `dotnet publish -r <rid>` builds it for that RID and adds the
  `DirectPInvoke` and `NativeLibrary` items itself (*verified* on every CI machine). Declare its
  entry points with `HIDDEN_FUNCTION`, or a Windows program exports them.
- **A plain `global` is not exported from a Windows DLL:** use `FUNCTION`, or an
  `ExportsFile`; otherwise .NET fails with `EntryPointNotFoundException` on Windows only.
- **IDEs know the bindings** from the asm library's first build on (a design-time build never
  builds a reference), and a package's from its restore.

**Where the binaries go: `BinariesCopyPath`** (build and publish alike), on the reference, as
the project's property, or on a `PackageReference` to an asm package:

```xml
<ProjectReference Include="../Crc/Crc.asmproj" BinariesCopyPath="native/{rid}" />
<PropertyGroup><BinariesCopyPath>RidFolders</BinariesCopyPath></PropertyGroup>
```

- **Values:** `Auto` (the default: `runtimes/<rid>/native/` portable, the app folder for one
  RID), `Runtimes`, `AppFolder`, `RidFolders` (`<rid>/`), or a folder inside the output with an
  optional `{rid}` (the RID each file was built for). Absolute, `..`, `< > : " | ? *` or another
  placeholder: `ASM0043`.
- **Which applies:** the reference's attribute, then the property, then the explicit choice of
  a .NET library the asm library comes through (so the attribute on a wrapper's reference
  shapes the app too), then `Auto`. Two wrappers that disagree: `ASM0046` (warning).
- **A folder without `{rid}`** in a portable build: `win-x64` and `win-arm64` both give
  `crc.dll`, so the build stops with `ASM0044`. Add `{rid}`, or narrow the reference's
  `RuntimeIdentifiers` to one RID per OS. Fine in a build for one RID (`native/crc.dll`).
- **Loading needs no code:** `deps.json` lists each library with `localPath` (`runtimeTargets`
  portable, `native` for one RID); the host loads from any such folder, framework-dependent
  and self-contained (*verified* on Windows and Linux). A C# project for .NET 5+ that puts a
  library outside the app folder also gets `obj/.../AsmNativeLibraryLoader.g.cs`, a
  `ResolvingUnmanagedDll` fallback that runs after .NET's own probing and any resolver of
  yours: it is how NativeAOT (no `deps.json`) finds `native/crc.dll` (*verified*).
  `AsmGenerateNativeLibraryLoader=false` turns it off.
- **`PrivateAssets="all"` on the asm reference of a .NET library** packs every RID's binary
  into that library's own package (`runtimes/<rid>/native/`, plus `buildTransitive/<tfm>/<id>.targets`
  for `BinariesCopyPath`) and drops the dependency on the asm package. The reference then does
  not flow to referencing projects either, nor do AsmSdk's targets. An app that references
  the library by project:
  - gets every RID's files where the library's `BinariesCopyPath` put them (the library hands
    them on laid out);
  - gets no `deps.json` entries;
  - loads through the library's generated loader.

  *Verified* on Windows and Linux, in builds and in a single-file publish, where the files
  stay beside the bundle.

See `references/interop.md` for the bindings in full, marshalling, publishing, Python `ctypes`,
the C header, and tests.

### Write C against an asm library

A library or program with `PROTO` or `STRUCT` lines gets `<AssemblyName>.h` at every build,
beside its API file (`bin/<Configuration>/<tfm>/hello.h` and each RID's folder), and
`dotnet pack` puts it under `include/`: the declarations (rendered from the prototypes, without
`fast`), each `STRUCT` as a C struct with checks of its size and offsets against the asm code's
layout (`_Static_assert` in C11, `static_assert` in C++11, a negative array size before them),
`extern "C"` and an include guard (*verified*: C11, C99 and C++11 with `-Wall -Wextra -pedantic
-Werror`, and C programs reading every struct field kind back through the real library).
`<AsmGenerateCHeader>false</AsmGenerateCHeader>` turns it off; a project's own
`include/<AssemblyName>.h` wins, and `dotnet pack` warns `ASM0149`.

### Run, publish and pack a program

```sh
dotnet run --project HelloApp                  # builds, then runs this machine's build
dotnet run --project HelloApp -r linux-x64     # a Linux build through WSL or in Docker
dotnet publish HelloApp -r linux-x64           # bin/Release/libc/linux-x64/publish/
```

- **`dotnet run`** picks a build this machine runs: its own RID, another it runs natively or
  emulated, the `wasi-wasm` build in wasmtime, then WSL, then Docker (`AsmRunIn` = `Auto`,
  `Host`, `Wasi`, `Wsl` or `Docker`; `ASM0091` when nothing can). `ASM0090` for a library.
- **A program gets the asm shared libraries it links** next to it, with a run path to find them
  there (`$ORIGIN`, `@loader_path`); `BinariesCopyPath` moves them (never on Windows: `ASM0047`).
- **`dotnet publish`** builds Release and writes one folder per RID. A .NET app or another
  program can reference a program (or its package) and gets it with its libraries, to start it
  as a helper process.
- **`<PackAsTool>true</PackAsTool>`** packs it as a .NET tool (a `DotnetTool` package plus one
  `DotnetToolRidPackage` per RID) for `dotnet tool install` (`ASM0053` for anything but a
  program with one target framework).

See `references/programs.md`.

### Link one asm project into another

`<ProjectReference Include="../Lib/Lib.asmproj" />` in an `.asmproj` does two things, for the
referencing build's RID:

- it adds the referenced project's public include folder to the include path: its
  `include/`, or its project folder when it has no `include/`;
- it links the referenced project's output: its static library when it has one, otherwise
  its shared library (on Windows, the DLL's import library), or its objects (`Objects`).

- **A RID-less static library** (no `RuntimeIdentifiers`) is built for whatever RID references
  it: the usual shape of a shared helper.
- **A Linux freestanding `Exe` links with `-static`, so it needs the static library.** Make the
  library `StaticLibrary`, or set `AsmProduceStaticLibrary=true`. Otherwise:
  `attempted static link of dynamic object` (*verified*).
- **A `freestanding` project cannot reference a `libc`-only one:** restore fails with
  `NU1201`. Make the referencing project `libc`, or let the reference build both
  (`TargetFrameworks=freestanding;libc`).
- **A static library's exports are exported again** by every shared library that links it
  (its globals on Linux and macOS, its `FUNCTION` directives on Windows). Keep its
  `FUNCTION`s to the public API; use `HIDDEN_FUNCTION` / `LOCAL_FUNCTION` for internals.

### Ship a library as a NuGet package

```xml
<PropertyGroup>
  <OutputType>StaticLibrary</OutputType>     <!-- or Library + AsmProduceStaticLibrary=true -->
  <RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>
  <PackageId>Acme.Crc</PackageId>
  <Version>1.2.0</Version>
</PropertyGroup>
```

`dotnet pack` writes, for every RID the project builds (`<fw>` is the NuGet framework behind
each target framework: netstandard1.0 for `freestanding`, netstandard2.0 for `libc`):

- `include/`, holding `include/**`, once, and the C header `<AssemblyName>.h`;
- `lib/<fw>/_._`, an empty marker per target framework, so NuGet refuses a `libc`-only
  package to a `freestanding` consumer (`NU1202`) instead of a link failing;
- `native/<rid>/<tfm>/`: the static library, a Windows DLL's import library, and a WebAssembly
  library's module and archive;
- `runtimes/<rid>/native/`: the shared library (`nativeassets/<fw>/` when the project
  targets both), which a `.csproj` consumer gets by NuGet's own rules;
- a generated `build/<fw>/` and `buildTransitive/<fw>/` `<PackageId>.props`, which gives an
  asm consumer its RID's build by the RID graph, or `ASM0060`;
- `<PackageId>.targets` beside them: `BinariesCopyPath` for the package's .NET consumers (a
  shared library) and the C# bindings' targets (`PROTO` or `STRUCT` lines), in plain MSBuild;
- with `PROTO` or `STRUCT` lines, the C# bindings: `contentFiles/cs/net7.0/AsmBindings/<AssemblyName>.cs.pp`
  (the baseline NuGet compiles into each C# consumer) and `build/bindings/` (the API file and
  the generator, for `[AsmLibrary]`).

The implicit `AsmFoundation.Sdk` dependency is removed from the `.nuspec` (`ASM0050`): a
package's consumers need nothing from the SDK, its bindings included.

- **Public include files must live in `include/`.** A project without an `include/` folder
  packs **no** include files, and its consumers' `%include` fails. A `ProjectReference`
  would still have worked, because it uses the project folder (*verified*).
- **A static library linked into a shared library is private** (the SDK sets
  `PrivateAssets="all"` on that reference when MSBuild restores), so the package does not
  depend on it. `PrivateAssets="none"` keeps the dependency. A `StaticLibrary` package keeps its
  dependencies: its consumers link both archives.
- **Central Package Management works,** with `Directory.Packages.props` and a
  `PackageReference` that has no version (*verified*).
- **Hide what a linked package's static library exports:** `HIDDEN_FUNCTION` in it, an
  `ExportsFile`, or on Linux `<LinkerArg Include="--exclude-libs ALL" />`.

See `references/dependencies-and-packaging.md` for consumer props, transitive flow,
publishing and versioning.

### Use the C library (`TargetFramework=libc`)

```nasm
extern puts

section .rodata
message: db "hello from assembly", 0

section .text
FUNCTION main
    sub     rsp, SHADOW_SPACE + 8   ; entered at rsp = 16n+8: align, plus Windows' shadow space
    lea     ARG1, [message]
    call    puts PLT
    xor     eax, eax                ; return 0
    add     rsp, SHADOW_SPACE + 8
    RETURN
ENDFUNCTION
```

The project sets `<OutputType>Exe</OutputType>` and `<TargetFramework>libc</TargetFramework>`;
this one source builds the four x64 RIDs (*verified*: it ran on Windows, Ubuntu and Alpine).

- **Each OS's stand-in lists its C library's names** (the SDK's `stubs/*.symbols`): one list
  for glibc and musl, one for libSystem, ucrtbase.dll's exports plus the SDK's own `printf`
  family wrappers for Windows, whose headers define those inline. A function a list lacks fails
  to link in an `Exe` with `undefined symbol: strsignal`: add it with
  `<AsmLibcSymbol Include="strsignal" />` (*verified*), which on Windows must be a ucrtbase.dll
  export.
- **A Linux shared library links an unlisted call anyway,** and binds it at load time
  (*verified*); Windows and macOS stop the link.
- **A variadic call** (`printf`) sets `al` to the number of vector registers on System V, and
  on Apple's ARM64 passes the variadic arguments on the stack.

The lists, versions, startup code and limits are in `references/runtimes-and-linking.md`.

### Defines, configurations and warnings

- **Add symbols with `DefineConstants`,** as in C#:
  `<DefineConstants>FAST_PATH;LEVEL=3</DefineConstants>` gives `-DFAST_PATH -DLEVEL=3`
  (`--defsym` for llvm-mc; WebAssembly takes names without values, `ASM0018`).
- **The implicit symbols are appended after the project body:** `DEBUG` or `RELEASE`,
  `FREESTANDING` or `LIBC`, the OS and CPU. So setting `DefineConstants` never drops them
  (*verified*), on the command line too. `DisableImplicitConfigurationDefines=true` and
  `DisableImplicitFrameworkDefines=true` turn the first two off.
- **Warnings:** `<NoWarn>$(NoWarn);label-orphan</NoWarn>` gives NASM `-w-label-orphan`,
  `WarningsAsErrors` `-w+error=<name>`, `WarningsNotAsErrors` `-w-error=<name>`; entries shaped
  otherwise (`NU5128`, `ASM0013`) are left to their tools.
- **Options set outside the project file are tracked:** a define, `NoWarn`, `ImplicitUsings`
  or `AsmFlags` changed in `Directory.Build.props` or with `-p:` assembles again (the SDK's
  `assemble-options.txt`). Linker arguments there are not: `dotnet build --no-incremental`.
- **In MSBuild text, `%` starts an escape.** A target that writes `%define …` must write
  `%25define`. `%de` is decoded as the character `0xDE` (*verified*).

### Include folders outside the project

```xml
<ItemGroup>
  <AsmIncludeDirectory Include="../common/include/" />       <!-- the -I path -->
  <None Include="../common/include/**/*.inc" />              <!-- makes edits rebuild -->
</ItemGroup>
```

With only the `AsmIncludeDirectory` line, editing `../common/include/x.inc` leaves the
**old objects in place**: the build is up to date, but stale (*verified*). The build
dependencies are the project's `None` items ending in `.inc`, its
`CustomAdditionalCompileInputs` items (an `%incbin` file), and the include folders of packages
and referenced projects.

### Settings for every asm project in a solution

`UsingAsmFoundationSdk` is already `true` when `Directory.Build.props` is read, so asm-only
settings can share one file with C# projects (*verified*):

```xml
<PropertyGroup Condition="'$(UsingAsmFoundationSdk)' == 'true'">
  <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  <RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>
</PropertyGroup>
```

For Linux shared libraries, also consider `<LinkerArg Include="-z defs" />` (an item, in an
`ItemGroup` conditioned on `$(RuntimeIdentifier.StartsWith('linux-'))`). A Linux `.so` links
even with an undefined symbol, so a misspelled `extern` otherwise fails only when the library
loads. With `-z defs` it fails at the link (*verified*). Windows and macOS always refuse.

### Build WebAssembly

`references/webassembly.md` is the full story; the shape (*verified*):

```xml
<Project Sdk="AsmFoundation.Sdk/0.4.0">
  <PropertyGroup>
    <RuntimeIdentifiers>browser-wasm;wasi-wasm</RuntimeIdentifiers>
  </PropertyGroup>
</Project>
```

```asm
// add.wasm.s: a stack machine; parameters are locals 0..n-1, the result is left on the stack
PROTO int32_t add_ints(int32_t a, int32_t b)
FUNCTION add_ints, (i32, i32) -> (i32)
    local.get 0
    local.get 1
    i32.add
ENDFUNCTION add_ints
```

- Each RID writes `Calc.wasm` (a module exporting its functions and `memory`) and `Calc.a` (the
  archive a .NET WebAssembly app links); a `wasi-wasm` `Exe` is a WASI command (`dotnet run`
  starts it in wasmtime). No unqualified file builds wasm: `.wasm.s`, `.browser.s`, `.wasi.s`.
- A .NET browser or WASI app takes a `ProjectReference` and gets the generated bindings (or a
  `[LibraryImport("Calc")]` of its own); it needs .NET's wasm workload for its own .NET version,
  else `ASM0054`.
- Never write an assembler constant (`.set`, `.equ`, `=`): llvm-mc's wasm writer crashes on
  them (`ASM0019`). End every data label with `ENDDATA name`, every function with `ENDFUNCTION
  name`, and put `PROTO` before its `FUNCTION`. No `STRUCT` lines in wasm sources yet.
- Write float constants as short exact decimals (`f32.const 1.0`, `0.5`) or hex floats
  (`f32.const 0x1.ae147ap-2` is 0.42): llvm-mc refuses `f32.const 1`, `0.42` and `0.1`, and
  `check_asmproj.py` prints the replacement.

## NASM rules that decide whether code links

Each is a NASM 3.02 or LLVM 23.1.5 result, per output format. `ImplicitUsings` (on by default)
writes `default rel`, the Linux note and `section .text` for you; the rules about them apply
with `<ImplicitUsings>disable</ImplicitUsings>` and to code assembled outside AsmSdk. The full
explanation and templates are in `references/nasm-for-asmsdk.md` and `references/platforms.md`.

| Rule | Applies to | What breaking it gives |
|---|---|---|
| `default rel` at the top of every source (`ImplicitUsings` writes it) | all | Linux `.so`/PIE: `relocation R_X86_64_32S cannot be used against local symbol; recompile with -fPIC`; macOS: NASM stops (`Mach-O 64-bit format does not support 32-bit absolute addresses`); Windows: `ASM0080` (the image is deleted) |
| `call f PLT` (`wrt ..plt`) for a function of **another library** (the C library, a referenced `.so`) | Linux `.so` | `relocation R_X86_64_PC32 cannot be used against symbol 'f'`. Within one library a plain call links: `-Bsymbolic` |
| another library's data through the GOT: `mov rax, [rel stdout wrt ..got]` (Linux), `..gotpcrel` (macOS) | `.so`, dylib | `R_X86_64_PC32 cannot be used against symbol 'stdout'` |
| no `mov rax, label` and no `dq label` in read-only data | Linux `.so`/PIE, macOS | Linux: `relocation R_X86_64_64 cannot be used against local symbol`; macOS: `ASM0081`, a text relocation. Jump tables as offsets (`dd .case - table`) work everywhere |
| `FUNCTION` (or `ExportsFile`) for what a DLL exports | Windows | a plain `global` is not exported: `EntryPointNotFoundException` |
| internals other files use: `HIDDEN_FUNCTION`; data has no macro, so one declaration per OS: `global d:data hidden 8` (Linux), `global d:private_extern` (macOS), a plain `global d` (Windows) | multi-OS libraries | a plain `global` is exported by the `.so` and the dylib (*verified*); `check_asmproj.py` reports a symbol hidden on one OS and exported on another (`ASMSRC022`) |
| ELF's directives only in Linux code | multi-OS sources | macho64 stops on `global f:function`, `:data`, `hidden` and `.note.GNU-stack`; win64 on `hidden`, `:data`; both on `wrt ..plt`/`..got` ("unrecognised symbol type", "symbol `..plt' not defined") |
| `section .note.GNU-stack noalloc noexec nowrite progbits` inside `%ifdef LINUX` (`ImplicitUsings` writes it) | Linux objects others link | the SDK passes `-z noexecstack` itself, but other linkers of your `.a` can mark the stack executable |
| a `section` line before the first label (`ImplicitUsings` ends with `section .text`; the function macros start with `__SECT__`) | Windows | NASM's COFF output writes a label defined before the first section directive as an undefined symbol: `undefined symbol: main` at the link |
| visibility **before** any size: `global h:function hidden (h.end - h)` | Linux-only files | `hidden` written after the size is silently ignored, and the symbol stays exported |
| `$name` for symbols that are NASM keywords | all | `wait`, `syscall` and `rel` as labels are parse errors |

- **Where `%include` looks:** NASM 3.02 tries the name in the working directory (the
  project folder) first. Then it tries the `-I` folders in order: the project's
  `include/`, the project folder, referenced projects and packages, and last the SDK's own
  (`asmsdk.inc`, `asmsdk-gnu.inc`). It does **not** search the folder of the file that holds
  the `%include` (*verified*). Write paths relative to the project folder or an include
  folder, or add the subfolder as an `AsmIncludeDirectory`.
- **Name include files `.inc`.** An `.asm` file pulled in with `%include` is also assembled
  on its own, which links its symbols twice: `duplicate symbol` (*verified*). Rename it
  `.inc`, or remove it with `<Compile Remove="helpers.asm" />`.
- **`section .rodata` works everywhere:** the SDK maps it to `.rdata` on Windows, where NASM
  would make an unknown section name executable code.

## Diagnostics

- **NASM's and llvm-mc's errors are MSBuild errors** at their file and line, relative to the
  project (`x.asm(12): error : …`; the SDK runs NASM with `-Xvc`), followed by `ASM0007`: the
  object was deleted, so the next build assembles the source again. IDEs list them and open the
  line.
- **`lld` errors are recognized** (`lld : error : undefined symbol: x`); the lines after them
  name the object and the source line.
- **Image checks after each Windows and macOS link:** `ASM0080` (a 32-bit absolute address in a
  64-bit Windows image, which lld-link accepts and the loader gets wrong above 4 GB), `ASM0081`
  (a fixup in a read-only Mach-O segment), `ASM0082` (unreadable image). A failed check
  deletes the image.
- **The SDK's errors:** `ASM0001` (no bundled toolchain: restore), `ASM0002` (bad
  `AsmToolchain`), `ASM0003` (a target framework other than `freestanding`/`libc`), `ASM0004`
  (a `.s` source with a toolchain without llvm-mc), `ASM0005` (System toolchain without a
  suitable `AsmLinkerCommand`), `ASM0006` (no toolchain package for this build machine),
  `ASM0007`, `ASM0010`-`ASM0013` (RIDs; `ASM0013` a warning), `ASM0015` (freestanding macOS
  program), `ASM0016`-`ASM0019` (WebAssembly), `ASM0020`-`ASM0025` (source selection),
  `ASM0026` (a generated file), `ASM0030` (`ExportsFile`), `ASM0040`-`ASM0042` and `ASM0049`
  (.NET consumers), `ASM0043`-`ASM0046` (`BinariesCopyPath`), `ASM0047`, `ASM0048`, `ASM0051`-
  `ASM0053` (programs), `ASM0054`-`ASM0055` (.NET WebAssembly apps), `ASM0050`, `ASM0060`,
  `ASM0061` (packages), `ASM0070` (C library stand-in), `ASM0080`-`ASM0082` (image checks),
  `ASM0090`-`ASM0093` (`dotnet run`), `ASM0100`-`ASM0108` (0.1.0 settings), `ASM0109`-`ASM0112`
  (0.3.0 names), `ASM0130`-`ASM0136` (`PROTO`, `STRUCT`, the API file), `ASM0140`-`ASM0149`
  (the C# bindings and the C header). `references/project-reference.md` has each one's cause and
  fix.

## IDEs

Rider, Visual Studio and VS Code show an `.asmproj` like a `.csproj`: `.asm` and `.s` files as
`Compile` items, every other file of the folder (`.inc` files among them) as `None`
(*verified* through MSBuild). Opening a solution never assembles or links: design-time builds
skip `CoreCompile`. A C# project's IntelliSense knows the generated bindings of its asm
references from their first build on, and a package's from its restore (*verified* through
Rider's and Visual Studio's design-time builds). If a user sees an empty project or MSB3073 lld
warnings on load, they are on 0.1.0: upgrade. Details:
<https://asmfoundation.github.io/AsmSdk/guide/ides.html>.

`references/troubleshooting.md` has every error found so far, with its cause and fix.

## Verify the outputs

`python <this-skill>/scripts/inspect_output.py bin/Debug/freestanding/linux-x64/libhello.so`
reports, per format:

- ELF: shared object, PIE or static executable; `SONAME`, `NEEDED`, `RUNPATH`, the
  interpreter; exported and imported symbols with types and sizes; whether the stack is
  executable;
- PE: DLL or program; its exports, imported DLLs and functions; ASLR and DEP;
- Mach-O: dylib or program; its install name, needed libraries, exports and imports by C name;
- WebAssembly: module or WASI command; exports, imports, memory, custom sections and the
  `asmapi` records;
- for a static library of any OS, its members and their symbols.

It finds `llvm-readobj` in the restored toolchain package by itself. Use `--expect-type`,
`--expect-export name` and `--expect-needed lib` to turn it into a check.

To *run* the outputs: `dotnet run` does it for a program (see
[Run, publish and pack a program](#run-publish-and-pack-a-program)). By hand, a Windows build
machine runs `win-x64` itself (Windows on Arm runs both Windows RIDs); Linux outputs run in a
container, and `linux-arm64` under QEMU (`docker run --platform linux/arm64`); macOS outputs need
a Mac (Apple silicon runs `osx-x64` under Rosetta). Files built on Windows have no execute bit,
so set it inside the container:

```sh
docker run --rm -v "$PWD:/w" -w /w mcr.microsoft.com/dotnet/runtime:10.0 \
  sh -c 'cp bin/Debug/libc/linux-x64/app /tmp/app && chmod +x /tmp/app && /tmp/app'
```

That image has glibc 2.39, so it runs `libc` programs too; `alpine:3` runs the `linux-musl-*`
ones (*verified*).

## Footguns (verified)

Every row was reproduced with an AsmSdk release.

| Symptom | Cause | Fix |
|---|---|---|
| `ASM0109`-`ASM0112` after upgrading to 0.4.0 | a 0.3.0 item or switch (`AsmSource`, `AsmInclude`, `EnableDefaultAsmItems`, `AsmLinkLibrary`), or a package packed by 0.3.0 | the line each error shows; pack the package again |
| `warning ASM0013` on `dotnet pack` or a portable publish | the project lists no `RuntimeIdentifiers`, so it ships the build machine's RID alone | list the platforms to ship, or `<NoWarn>ASM0013</NoWarn>` when one is the intent |
| `ASM0010` | no RID at all, on a build machine that is none of the eight | `<RuntimeIdentifiers>…</RuntimeIdentifiers>`, or `-r` |
| `ASM0023` for an ARM64 RID | NASM only builds x64 | a GNU-syntax `.s` file for ARM64, or drop the RID |
| `unrecognised symbol type 'function'` (macOS), `symbol '..plt' not defined` (Windows, macOS) | ELF's directives in a multi-OS source | `FUNCTION`, `call f PLT` from `asmsdk.inc`; `%ifdef LINUX` for the rest |
| `unknown section name .note.GNU-stack` (macOS) | the note outside `%ifdef LINUX` | wrap it, or delete it: `ImplicitUsings` writes it on Linux |
| `undefined symbol: main` on Windows only, though a NASM source defines it | no `section` line before the label, with `ImplicitUsings` off and without `asmsdk.inc`'s macros | `section .text` first, or leave `ImplicitUsings` on |
| `EntryPointNotFoundException` from .NET on Windows only | a plain `global` is no DLL export | `FUNCTION`, or an `ExportsFile` |
| `ASM0080` / `ASM0081` | an absolute address (no `default rel` with `ImplicitUsings` off, `mov rax, label`, `dq label` in `.rodata`) | `default rel`, `lea`, offset tables |
| `ASM0100`-`ASM0108` after upgrading from 0.1.0 | a 0.1.0 setting (`AsmLibraryName`, `AsmRuntime`, `AsmDefine`…) | the .NET name each error gives |
| `Ambiguous project name 'x'` at restore | two projects share an `AssemblyName`, and `PackageId` defaults to it | a `<PackageId>` per project |
| `NU1201` / `NU1202` | a `freestanding` project references `libc`-only code | make it `libc`, or multi-target the reference |
| Edited a shared `.inc`, output did not change | an include folder outside the project is not a dependency | also list the files as `None` items |
| `duplicate symbol` for a helper | an `%include`d `.asm` is also a source | name it `.inc`, or `<Compile Remove="…" />` |
| Consumers can't `%include` a packaged library's file | the project had no `include/` folder | move public `.inc` files into `include/` |
| `attempted static link of dynamic object` | Linux freestanding `Exe` given a `.so` | produce a static library (`StaticLibrary` / `AsmProduceStaticLibrary`) |
| `-rpath $ORIGIN` came out empty | on Linux/macOS build machines the link command runs through `/bin/sh` | quote it there: `'$ORIGIN'` (see `references/runtimes-and-linking.md`) |
| `undefined symbol: <C fn>` in a `libc` `Exe` | missing from that OS's stand-in list | `<AsmLibcSymbol Include="fn" />` |
| `MSB4025 … ProjectType '' not found` | `.slnx` entry without a type | `dotnet sln add`, or add the type GUID |
| `ASM0006` on an Intel Mac or Alpine | no toolchain package for that build machine | `AsmToolchain=System`, or `AsmToolchainDirectory` |
| `ASM0040` in a RID-specific .NET build | an asm reference lists no RID that serves the app's RID | add the RID to the asm project, build the app portable, or `OptionalOnUnlistedRuntimes` for an optional library |
| `ASM0044` with `BinariesCopyPath="native"` | a portable build of several RIDs of one OS puts two `x.dll` (or `libx.so`) in one folder | `native/{rid}`, or one RID per OS on the reference |
| The app's folder holds two layouts of one library after `dotnet build -o out` | `-o` is every project's output folder, so a wrapper library in between copies its own layout there too | `dotnet publish -o` (no such effect), or the app's own `OutDir` |
| `bin/Debug/net10.0/win-x64/` holds both a RID's library and a whole `-r win-x64` build | `RidFolders` in a portable build uses the same folder names as `dotnet build -r` | `native/{rid}` when you also build for one RID |
| `DllNotFoundException` under NativeAOT with a custom folder | no generated loader: a VB or F# project, below .NET 5, or `AsmGenerateNativeLibraryLoader=false` | keep the app folder for NativeAOT, or a resolver of your own |
| `error CS0101: The namespace '<global namespace>' already contains a definition for 'Crc'` | a type of the C# project is named like an asm library's baseline namespace | `<AsmBindings Include="crc" Namespace="Acme.Native.Crc" />` |
| `error CS8936: Feature 'ref fields' is not available in C# 10.0` in `AsmBindings/*.g.cs` | the project's `LangVersion` is below 11 | `<LangVersion>11</LangVersion>` or later, or `AsmGenerateBindings=false` |
| `ASM0143` from the bindings | a generated class would meet another name (two files becoming one class, a function named like the app's class that holds it), or an attributed class is not `partial` | rename one, or `Nesting`/`Namespace` to separate them; make the class `partial` |
| The C# build loads the bindings generator though no code uses `[AsmLibrary]` | the switch is a word search: `AsmLibrary` in a comment or string turns it on | nothing (it writes the same baseline), or reword the text |
| `ASM0019 … absolute addressing not supported!` (wasm) | a `.set`/`.equ`/`=` constant in a `.wasm.s` source | the number itself, or a macro emitting `i32.const N` (`references/webassembly.md`) |
| `Cannot parse real: 0.42`, or `invalid operand for instruction` on `f32.const 1` (wasm) | llvm-mc reads a float operand as a double and refuses an integer or a decimal it cannot prove exact (one whose significant digits need more than 63 bits, or no double holds) | a short exact decimal (`1.0`) or a hex float (`0x1.ae147ap-2`); `check_asmproj.py` (ASMWASM015) names it |
| `ASM0054` (wasm) | a .NET WebAssembly app without .NET's native wasm build for its .NET version | `wasm-tools`, or `wasi-experimental` + WASI SDK 25.0, on the SDK of the app's .NET; on SDK 11, `wasm-tools-net10` serves a `Microsoft.NET.Sdk.WebAssembly` app only: a `Microsoft.NET.Sdk` + `browser-wasm` app (wasmconsole shape) or a WASI app needs a .NET 10 SDK |
| `ASM0055` warning (wasm) | a build (not a publish) of a browser app with `RunAOTCompilation=true`: AOT happens only at publish | time a `dotnet publish`; `NoWarn` ASM0055 when the property is there for publishes |
| asm 10-30x faster than C# in a browser, but not in Node | a .NET browser *Debug* build (or one with `WasmDebugLevel` -1) runs with the debugger on in Chromium/Firefox: unoptimized interpreter, no jiterpreter | time a Release build (the SDK sets `WasmDebugLevel` 0 there) or a publish |

## References: read the one the task needs

| File | Read it when |
|---|---|
| `references/project-reference.md` | you need any property, item, metadata, target, generated file or error, with its exact default |
| `references/projects.md` | templates, sources and include files, `ImplicitUsings`, defines, warnings, incremental and reproducible builds, solutions |
| `references/platforms.md` | choosing RIDs, sources per platform and qualifiers, `asmsdk.inc` / `asmsdk-gnu.inc`, exports per OS, the C library per OS, build machines |
| `references/runtimes-and-linking.md` | choosing `freestanding` or `libc`, entry points per OS, the C library stand-ins, the exact link lines, rpath, `-z defs`, stripping, platform limits |
| `references/nasm-for-asmsdk.md` | writing or fixing NASM sources: position-independent code, symbols, `PROTO` and `STRUCT` lines, sections, includes, calling conventions, Linux system calls, templates |
| `references/programs.md` | `dotnet run`, the libraries a program links, `dotnet publish`, a program as a dependency, `PackAsTool` |
| `references/dependencies-and-packaging.md` | ProjectReference and PackageReference flows, pack layout per RID, consumer props, versions, feeds, publishing |
| `references/interop.md` | calling asm from .NET (the generated bindings, `[AsmLibrary]`, P/Invoke by RID, publishing, single file, NativeAOT, tests), Python, or C (the generated header) |
| `references/toolchain.md` | Bundled or System toolchain, the tools and versions, offline builds, unsupported hosts, provenance |
| `references/ci-and-release.md` | GitHub Actions on several machines, caching, running the outputs, versioning from tags, trusted publishing |
| `references/troubleshooting.md` | any error message: exact text, cause, fix |
| `references/internals.md` | the target graph and incremental rules, the RID outer build, extending the build (generated includes, post-link steps) |
| `references/webassembly.md` | anything `browser-wasm` / `wasi-wasm`: sources and macros, PROTO on wasm, .NET WebAssembly apps, modules for JavaScript, WASI programs, packages, the measured traps |

## Scripts

All three need only Python 3.8+ and read nothing outside the paths given (and the NuGet cache).

- `scripts/new_asmproj.py <dir> --kind library|static|exe|objects [--framework libc]
  [--rids "win-x64;linux-x64"] [--assembly-name n] [--sln x.slnx]
  [--package-id Id --version 1.0.0] [--sdk-version 0.4.0]` scaffolds a project; existing
  files are reported and left alone.
- `scripts/check_asmproj.py <path> [--json] [--no-info]` lints projects and sources for the
  footguns above, judging each source for the RIDs and OSes it builds (a RID-less project takes
  its referencing projects' RIDs; with none known, platform findings are warnings) and for
  `ImplicitUsings`. It reads the SDK's C library lists from the NuGet cache when that version is
  restored. It exits 1 when it finds an error-level problem.
- `scripts/inspect_output.py <file> [--json] [--expect-type t] [--expect-export s]
  [--expect-needed lib] [--expect-import i] [--expect-nonexec-stack] [--readobj path]`
  summarizes an ELF, PE, Mach-O or WebAssembly output or a static library. It exits 1 when an
  expectation fails.

## Limits of AsmSdk 0.4.0

- Ten RIDs: x86-64 and ARM64 on Windows, Linux (glibc and musl) and macOS, and WebAssembly's
  `browser-wasm` and `wasi-wasm`. No 32-bit targets, no RISC-V.
- Languages: NASM for x64, GNU syntax (llvm-mc) for ARM64 and for x64 files that name a
  qualifier, LLVM's WebAssembly assembly for wasm. No MASM, no C compiler.
- macOS has no freestanding programs (`ASM0015`); a `libc` program needs glibc 2.34+ on Linux;
  WebAssembly is `freestanding` only, with no `STRUCT` lines yet.
- A static glibc executable needs a real sysroot: use `AsmToolchain=System` on Linux.
- The C# bindings are for C# projects on .NET 7 or later (C# 11); a library's prototypes use
  fixed-size C types (`int32_t`, not `int` or `long`).
- A design-time build never builds a reference: an IDE knows a referenced library's bindings
  from its first build on.
