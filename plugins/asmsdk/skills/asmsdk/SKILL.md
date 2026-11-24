---
name: asmsdk
description: Build, reference, package and release x86-64 and ARM64 assembly with AsmSdk (the AsmFoundation.Sdk MSBuild SDK) - .asmproj projects that turn NASM (x64) and GNU-syntax (ARM64) sources into shared libraries, static libraries and programs for seven runtime identifiers (win-x64, win-arm64, linux-x64, linux-arm64, linux-musl-x64, osx-x64, osx-arm64) with dotnet build, share them as versioned NuGet packages, and P/Invoke them from .csproj projects, which get the right binary per RID. Use it whenever an .asmproj, AsmFoundation.Sdk, AsmFoundation.Toolchain or an msbuild-sdks entry for assembly is involved, or the user wants to build, link, version, package, test or ship assembly with MSBuild, dotnet build, pack or publish, NuGet, a .sln or .slnx, or CI - including link errors such as "recompile with -fPIC", "undefined symbol", "unrecognised symbol type", "attempted static link of dynamic object", ASM0xxx errors (ASM0010 no RuntimeIdentifiers, ASM0023, ASM0080), RuntimeIdentifiers and per-RID source files, asmsdk.inc or asmsdk-gnu.inc, TargetFramework libc and the C library stand-ins, Windows DLL exports, Mach-O, single-file or NativeAOT publishing of an app that uses asm, and calling assembly from C# or Python; and, in the release after 0.3.0, WebAssembly - browser-wasm and wasi-wasm from .wasm.s sources (asmsdk-wasm.inc), .wasm modules for JavaScript, WASI programs in wasmtime, .NET WebAssembly apps (Blazor) that link asm, wasm-ld and ASM0054 - even when AsmSdk is not named. Not for MASM, CMake or Makefile builds, inline assembly in C, or questions about what an instruction does.
---

# AsmSdk: x86-64 and ARM64 assembly projects on MSBuild and NuGet

AsmSdk is the AsmFoundation's project, dependency and build management for assembly. An
`.asmproj` is to assembly what a `.csproj` is to C#:

- `dotnet build` assembles and links it, once per runtime identifier (RID);
- `ProjectReference` and `PackageReference` share code between projects;
- `dotnet pack` turns it into a versioned NuGet package with every RID's binary;
- a `.csproj` that references it gets the binary of the platform it builds or runs for.

One project builds **seven RIDs** from any build machine: `win-x64`, `win-arm64`, `linux-x64`,
`linux-arm64`, `linux-musl-x64`, `osx-x64`, `osx-arm64`. x64 code is NASM (`.asm`); ARM64 code
is GNU syntax (`.s`) for `llvm-mc`. Restore downloads a bundled toolchain as a NuGet package
(NASM 3.02, plus LLVM 23.1.5's `llvm-mc`, `lld` as `ld.lld`, `lld-link` and `ld64.lld`,
`llvm-ar` and `llvm-readobj`) for five build machines, so nothing needs to be installed beyond
the .NET SDK.

This skill documents **AsmFoundation.Sdk 0.3.0**. Each behavior marked *verified* was measured
by building with an AsmSdk release and its bundled tools; the references are the
documentation site's 0.3.0 pages, whose statements were measured with 0.3.0 (they say so) and
are covered by AsmSdk's end-to-end tests on five native build machines (Windows x64 and Arm,
Linux x64 and ARM64, Apple silicon). If `global.json` pins another version, check the SDK's
site, <https://asmfoundation.github.io/AsmSdk/> (or that release's `docs/asmproj.md`). The
site has the same facts written for people, so it is the page to link a user to.

**WebAssembly is the third target, in the release after 0.3.0** (on AsmSdk's `main` branch
now): the RIDs `browser-wasm` and `wasi-wasm`, built from `.s` files qualified for them
(`name.wasm.s`) in LLVM's WebAssembly assembly, into `.wasm` modules, WASI programs and the
archives .NET WebAssembly apps link. 0.3.0 stops a wasm RID with `ASM0011`. For anything
WebAssembly, read `references/webassembly.md` first: its stack-machine model, macros and
measured traps (no assembler constants, no `.pushsection`, `ENDDATA` sizes) differ from both
native targets.

**0.3.0 broke 0.2.0 projects on purpose, with no compatibility layer:**

- **`RuntimeIdentifiers` are required.** A project builds the RIDs it lists, the ones a
  referencing project asks for, or `-r`; with none, `ASM0010`. 0.2.0's `AsmTargetRid` and
  `AsmFormat` are gone (ignored).
- **Outputs are per RID:** `bin/<Configuration>/<tfm>/<rid>/`.
- **A source for several OSes uses `asmsdk.inc`** (`FUNCTION`, `ARG1`.., `PLT`): ELF's own
  directives (`global f:function`, `hidden`, `wrt ..plt`, `.note.GNU-stack`) stop macOS's or
  Windows' NASM output.
- **Linux shared libraries link `-Bsymbolic`:** a call within the library needs no PLT.
- **NASM runs with `-Xvc`:** its messages are MSBuild errors with file and line.

0.2.0 renamed every 0.1.0 setting to .NET's own (`AssemblyName`, `TargetFramework`,
`DefineConstants`, `DebugSymbols`, `StartupObject`, `LinkerArg`/`ExportsFile`, `OutputType`);
a 0.1.0 project fails with `ASM0100`-`ASM0108`, each naming its replacement. The
[changelog](https://github.com/AsmFoundation/AsmSdk/blob/main/CHANGELOG.md) has both migration
tables. `check_asmproj.py` reports every removed setting before a build (`ASMPRJ013`).

`<this-skill>` below stands for the skill's base directory, which is shown when the skill
loads. The scripts live in its `scripts/` folder, and the references in `references/`.

## Orient yourself first

1. **Find the pieces:**
   - `*.asmproj` (and its `RuntimeIdentifiers`);
   - `global.json` (`"msbuild-sdks": { "AsmFoundation.Sdk": "<version>" }`);
   - `*.slnx` / `*.sln`;
   - `nuget.config`;
   - `Directory.Build.props` and `Directory.Packages.props`.
2. **Lint before you reason:** `python <this-skill>/scripts/check_asmproj.py <repo-or-project>`
   reports the footguns below, with the file, line and fix, judged for the platforms each
   source is built for. It reads files only.
3. **Build:** `dotnet build`. Each RID's inner build prints `<Project> -> <output>`. A NASM
   or `llvm-mc` error is reported at its file and line; an `lld` error names the object.
4. **Inspect the outputs:** `python <this-skill>/scripts/inspect_output.py <file>` (ELF, PE
   or Mach-O) rather than reasoning about them (see [Verify the outputs](#verify-the-outputs)).

## The model in one screen

```text
global.json            { "msbuild-sdks": { "AsmFoundation.Sdk": "0.3.0" } }
nuget.config           only when the SDK or your packages come from a private or local feed
App.slnx               <Project Path="Crc/Crc.asmproj" Type="13B669BE-BB05-4DDF-9536-439F39A36129" />
Crc/Crc.asmproj        <Project Sdk="AsmFoundation.Sdk"> ... <RuntimeIdentifiers>...</RuntimeIdentifiers>
Crc/include/*.inc      public include files: referencing projects and package consumers get them
Crc/**/*.asm           NASM sources: the x64 RIDs
Crc/**/*.s             GNU-syntax sources (llvm-mc): the ARM64 RIDs
Crc/x.linux.asm        a file-name qualifier narrows a source to some RIDs (most specific wins)
```

| `OutputType` | Windows | Linux | macOS | Notes |
|---|---|---|---|---|
| `Library` (default) | `name.dll` (+ `name.dll.lib`) | `libname.so` | `libname.dylib` | position-independent code required |
| `StaticLibrary` | `name.lib` | `libname.a` | `libname.a` | |
| `Exe` | `name.exe` | `name` | `name` (`libc` only) | `_start` (`freestanding`) or `main` (`libc`) |
| `Objects` | objects in `obj/` | | | linked by a referencing asm project |

- Every output lands in `bin/<Configuration>/<tfm>/<rid>/`, `<tfm>` being `freestanding` or
  `libc`. `dotnet build -o <folder>` gives each RID `<folder>/<rid>/`.
- `<name>` is `AssemblyName`. It defaults to the project name, as in .NET. **`PackageId`
  defaults to it too**, so two projects that share an `AssemblyName` (a static and a shared
  build of one library) need a `PackageId` each, or restore fails with "Ambiguous project name".
- `AsmProduceStaticLibrary=true` also writes the static library next to a shared one.

**Choosing RIDs:** `<RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>` (any
of the seven), one `<RuntimeIdentifier>`, or none: then the project builds what a referencing
project asks for (`<ProjectReference ... RuntimeIdentifiers="linux-x64;win-x64" />`, a .NET
app's RID) or `-r`. Built alone with none: `ASM0010`. A RID outside the seven: `ASM0011`; one
the project does not list: `ASM0012`.

**Sources per RID:** the extension is the language (`.asm` NASM, x64 only; `.s` GNU syntax for
llvm-mc). A qualifier before the extension narrows a file: a RID (`x.win-x64.asm`), an OS family
(`win`, `linux`, `linux-musl`, `osx`), `unix`, or a CPU (`x64`, `arm64`). Among the files of one
name, the most specific wins per RID (RID 50, `linux-musl` 40, OS 30, `unix` 20, CPU 10, none 1).
Errors: `ASM0020` (a tie), `ASM0021` (a NASM file for ARM64 only), `ASM0023` (a listed RID no
source builds: typically NASM only, with an ARM64 RID listed), `ASM0024` (a source listed twice).

**Runtimes are target frameworks, on every OS.** `freestanding` (the default) links no C
library: Linux code makes system calls, Windows code calls kernel32 (linked into every Windows
output), and macOS has no freestanding programs (`ASM0015`; libraries are fine). `libc` links
the platform's C library through SDK-written stand-ins, so no sysroot or platform SDK is
needed: glibc 2.34+ or musl (Linux), libSystem (macOS), the Universal C Runtime `ucrtbase.dll`
(Windows). A `libc` program enters `main`.

- `<TargetFrameworks>freestanding;libc</TargetFrameworks>` builds both, like a multi-targeted
  `.csproj`.
- NuGet enforces what links: a `libc` project may reference `freestanding` code, but a
  `freestanding` project that references `libc`-only code fails at restore (`NU1201` for a
  project, `NU1202` for a package). A .NET project gets the `libc` build of a project that
  targets both (*verified*).

**Configurations and symbols, as in C#:**

- `Debug` defines `DEBUG` and writes debug information (DWARF; CodeView and a `.pdb` on
  Windows). `Release` defines `RELEASE` and writes none (`<DebugSymbols>true</DebugSymbols>`
  adds it).
- Every build also defines `FREESTANDING` or `LIBC` (*verified*), the OS (`WINDOWS`, `LINUX`,
  `MACOS`, plus `MUSL`) and the CPU (`X64`, `ARM64`); a program defines `ASMSDK_EXECUTABLE`,
  and a project with an `ExportsFile` `ASMSDK_EXPORTS_FILE`. NASM tests them with `%ifdef`,
  llvm-mc with `.ifdef`.

**Toolchain:** `AsmToolchain=Bundled` (the default) downloads `AsmFoundation.Toolchain.<host>`
during restore, for build machines `win-x64`, `win-arm64`, `linux-x64`, `linux-arm64` and
`osx-arm64`; any of them builds all seven RIDs. Intel Macs and musl hosts have no package
(`ASM0006`): `AsmToolchain=System` uses `nasm`, `llvm-mc`, a linker and `ar` from PATH, and
needs `AsmLinkerCommand` set to `lld-link`, `ld64.lld` or `ld.lld` for RIDs its GNU `ld` cannot
link (`ASM0005`).

## Recipes

### Start a project or a solution

```sh
python <this-skill>/scripts/new_asmproj.py Hello --kind library --assembly-name hello --sln App.slnx
```

The script writes `global.json` (when missing), the `.asmproj` with `RuntimeIdentifiers`, an
`include/` file, and starter sources that follow the linking rules on every OS: a NASM file for
the x64 RIDs (through `asmsdk.inc`) and a GNU-syntax file for the ARM64 RIDs (through
`asmsdk-gnu.inc`). It also adds the project to the `.slnx` with the type GUID, and never
overwrites a file. Kinds are `library`, `static`, `exe` and `objects`; `--framework libc`
targets the C library; `--rids` picks the RIDs (default: every RID the kind can build, so all
seven, or all but macOS for a freestanding program); `--package-id`/`--version` make the
project packable. Every kind and framework was built for all its RIDs and the programs run on
Windows x64, Ubuntu, Alpine and Linux ARM64 (*verified*).

By hand, the minimum is a `global.json`, the project file and one source per CPU you target:

```xml
<Project Sdk="AsmFoundation.Sdk">
  <PropertyGroup>
    <AssemblyName>hello</AssemblyName>      <!-- hello.dll, libhello.so, libhello.dylib -->
    <RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers>
  </PropertyGroup>
</Project>
```

- **In a `.slnx`,** an `.asmproj` needs `Type="13B669BE-BB05-4DDF-9536-439F39A36129"`
  (the generic MSBuild project type). Without it, `dotnet build App.slnx` fails with
  `MSB4025 … ProjectType '' not found` (*verified*).
- **`dotnet sln add` refuses an `.asmproj`,** in both `.slnx` and `.sln`, with
  `has an unknown project type and cannot be added to the solution file` (*verified*). Add
  the entry by hand, or with the script above.
- **In a classic `.sln`,** an entry needs two parts (*verified*):
  - a `Project("{13B669BE-BB05-4DDF-9536-439F39A36129}") = …` line;
  - `ProjectConfigurationPlatforms` lines for it. Without them, the build silently skips
    the project and still reports 0 errors.

  Prefer `.slnx`.
- **A solution build of a RID-less project builds nothing for it by itself** (a message says
  so); its referencing projects build it for their RIDs.

### Write one source for every OS

```nasm
default rel                         ; RIP-relative everywhere: required on every OS
%include "asmsdk.inc"               ; FUNCTION, ARG1.., SHADOW_SPACE, PLT for this RID's OS
extern memcpy

section .text
FUNCTION copy_bytes, 3, rbx         ; exported; 3 integer arguments; changes rbx
    mov     rbx, ARG1               ; rcx on Windows, rdi elsewhere
    sub     rsp, SHADOW_SPACE       ; one push (rbx) re-aligned the stack; Windows: 32-byte shadow space
    call    memcpy PLT              ; another library: wrt ..plt on Linux, nothing elsewhere
    add     rsp, SHADOW_SPACE
    RETURN                          ; restores rbx, then ret
ENDFUNCTION

%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
```

- **`FUNCTION name [, nargs [, registers]]`** declares and exports (a `.drectve` export on
  Windows, a plain global on Linux and macOS), and saves the listed registers that this OS's
  convention makes callee-saved (`rdi`, `rsi`, `xmm6`-`xmm15` too on Windows).
  **`LOCAL_FUNCTION`** is file-local; **`HIDDEN_FUNCTION`** is global but exported from no
  image (use it for helpers other files or a static library's users call). `RETURN` restores
  and returns; `ENDFUNCTION` closes. In a program, `FUNCTION` exports nothing.
- **ARM64 (`.s`, `.include "asmsdk-gnu.inc"`):** AAPCS64 is the same everywhere (`x0`-`x7`, the
  result in `x0`); the macros handle names and addressing: `FUNCTION`/`ENDFUNCTION name`,
  `CALL`/`TAILCALL`, `ADDRESS reg, label`, `RODATA`. Never touch `x18` (the platform register
  on Windows and macOS). On macOS every *variadic* argument goes on the stack, so `printf` is
  written per OS.
- **A file for one OS** (`x.linux.asm`, `x.win.asm`) may use that OS's own directives and
  system interface; `%ifdef WINDOWS` / `LINUX` / `MACOS` does the same inside one file.

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

Add a `ProjectReference` from the `.csproj` to the `.asmproj`. Nothing else: the consumer
targets reach the .NET project through the asm project's implicit `AsmFoundation.Sdk`
reference and treat it like a package with a `runtimes/` folder.

```csharp
[LibraryImport("crc", EntryPoint = "crc_update")]  // crc.dll, libcrc.so or libcrc.dylib
private static partial uint CrcUpdate(uint crc, ReadOnlySpan<byte> data, nuint length);
```

- **Portable build** (no RID): every RID the asm project lists, under
  `runtimes/<rid>/native/`, listed in `deps.json`; the .NET host loads the machine's own.
- **RID-specific build** (`-r linux-arm64`, or a `RuntimeIdentifier`): the one RID that serves
  it best by the .NET RID graph (`linux-arm64` serves `linux-musl-arm64`), copied flat beside
  the app. None fits: `ASM0040`.
- **Through a C# wrapper library** (app → `Crc.Net.csproj` → `Crc.asmproj`) the same: the .NET
  SDK adds the asm project to the app transitively. The wrapper itself builds portable.
- **Publishing:** `-r <rid>` puts the library beside the app; `PublishSingleFile` beside the
  single file, or inside it with `IncludeNativeLibrariesForSelfExtract=true` (the consumer
  targets mark asm libraries `AssetType=native`); `PublishAot` beside the native program,
  loaded at run time; trimming and `-t:PublishContainer` work as usual. Command-line publish
  switches (`-p:PublishAot=true`) do not reach the asm projects.
- **A static library inside a NativeAOT program:** `<DirectPInvoke Include="crc" />` and
  `<NativeLibrary Include=".../<rid>/crc.lib or libcrc.a" />`, by hand (the consumer targets
  skip static libraries); declare its entry points with `HIDDEN_FUNCTION`, or a Windows program
  exports them.
- **A plain `global` is not exported from a Windows DLL:** use `FUNCTION`, or an
  `ExportsFile`; otherwise .NET fails with `EntryPointNotFoundException` on Windows only.

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

See `references/interop.md` for marshalling, publishing, Python `ctypes`, C headers, and tests.

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

- `include/`, holding `include/**`, once;
- `lib/<fw>/_._`, an empty marker per target framework, so NuGet refuses a `libc`-only
  package to a `freestanding` consumer (`NU1202`) instead of a link failing;
- `native/<rid>/<tfm>/`: the static library, and a Windows DLL's import library;
- `runtimes/<rid>/native/`: the shared library (`nativeassets/<fw>/` when the project
  targets both), which a `.csproj` consumer gets by NuGet's own rules;
- a generated `build/<fw>/` and `buildTransitive/<fw>/` `<PackageId>.props`, which gives an
  asm consumer its RID's build by the RID graph, or `ASM0060`;
- with a shared library, `<PackageId>.targets` beside them: `BinariesCopyPath` for the
  package's .NET consumers, in plain MSBuild (the package does not depend on the SDK).

The implicit `AsmFoundation.Sdk` dependency is removed from the `.nuspec` (`ASM0050`).

- **Public include files must live in `include/`.** A project without an `include/` folder
  packs **no** include files, and its consumers' `%include` fails. A `ProjectReference`
  would still have worked, because it uses the project folder (*verified*).
- **A static library linked in is still a package dependency.** `dotnet pack` makes every
  `ProjectReference` a dependency. So a shared library that links
  `../CrcCore/CrcCore.asmproj` depends on that project's package. When that package was never
  published, every consumer fails restore with `NU1101`. Mark such a reference
  `PrivateAssets="all"`: its code is inside already (*verified*). A `StaticLibrary` package
  keeps the dependency: its consumers link both archives.
- **Central Package Management works,** with `Directory.Packages.props` and a
  `PackageReference` that has no version (*verified*).
- **Hide what a linked package's static library exports:** `HIDDEN_FUNCTION` in it, an
  `ExportsFile`, or on Linux `<LinkerArg Include="--exclude-libs ALL" />`.

See `references/dependencies-and-packaging.md` for consumer props, transitive flow,
publishing and versioning.

### Use the C library (`TargetFramework=libc`)

```nasm
default rel
%include "asmsdk.inc"
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

### Defines and configurations

- **Add symbols with `DefineConstants`,** as in C#:
  `<DefineConstants>FAST_PATH;LEVEL=3</DefineConstants>` gives `-DFAST_PATH -DLEVEL=3`
  (`--defsym` for llvm-mc).
- **The implicit symbols are appended after the project body:** `DEBUG` or `RELEASE`,
  `FREESTANDING` or `LIBC`, the OS and CPU. So setting `DefineConstants` never drops them
  (*verified*). `DisableImplicitConfigurationDefines=true` and
  `DisableImplicitFrameworkDefines=true` turn the first two off.
- **In MSBuild text, `%` starts an escape.** A target that writes `%define …` must write
  `%25define`. `%de` is decoded as the character `0xDE` (*verified*).

### Include folders outside the project

```xml
<ItemGroup>
  <AsmIncludeDirectory Include="../common/include/" />       <!-- the -I path -->
  <AsmInclude Include="../common/include/**/*.inc" />        <!-- makes edits rebuild -->
</ItemGroup>
```

With only the `AsmIncludeDirectory` line, editing `../common/include/x.inc` leaves the
**old objects in place**: the build is up to date, but stale (*verified*). Only the
project's own `AsmInclude` items, and the include folders of packages and referenced
projects, are build dependencies.

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

### Build WebAssembly (the release after 0.3.0)

`references/webassembly.md` is the full story; the shape (*verified* with a `main` build):

```xml
<Project Sdk="AsmFoundation.Sdk">
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
- A .NET browser or WASI app takes a `ProjectReference` and the same `[LibraryImport("Calc")]`
  (or the generated bindings); it needs .NET's wasm workload for its own .NET version, else
  `ASM0054`.
- Never write an assembler constant (`.set`, `.equ`, `=`): llvm-mc's wasm writer crashes on
  them (`ASM0019`). End every data label with `ENDDATA name`, every function with `ENDFUNCTION
  name`, and put `PROTO` before its `FUNCTION`.

## NASM rules that decide whether code links

Each is a NASM 3.02 or LLVM 23.1.5 result, per output format. The full explanation and
templates are in `references/nasm-for-asmsdk.md` and `references/platforms.md`.

| Rule | Applies to | What breaking it gives |
|---|---|---|
| `default rel` at the top of every source | all | Linux `.so`/PIE: `relocation R_X86_64_32S cannot be used against local symbol; recompile with -fPIC`; macOS: NASM stops (`Mach-O 64-bit format does not support 32-bit absolute addresses`); Windows: `ASM0080` (the image is deleted) |
| `call f PLT` (`wrt ..plt`) for a function of **another library** (the C library, a referenced `.so`) | Linux `.so` | `relocation R_X86_64_PC32 cannot be used against symbol 'f'`. Within one library a plain call links: `-Bsymbolic` |
| another library's data through the GOT: `mov rax, [rel stdout wrt ..got]` (Linux), `..gotpcrel` (macOS) | `.so`, dylib | `R_X86_64_PC32 cannot be used against symbol 'stdout'` |
| no `mov rax, label` and no `dq label` in read-only data | Linux `.so`/PIE, macOS | Linux: `relocation R_X86_64_64 cannot be used against local symbol`; macOS: `ASM0081`, a text relocation. Jump tables as offsets (`dd .case - table`) work everywhere |
| `FUNCTION` (or `ExportsFile`) for what a DLL exports | Windows | a plain `global` is not exported: `EntryPointNotFoundException` |
| internals other files use: `HIDDEN_FUNCTION`; data has no macro, so one declaration per OS: `global d:data hidden 8` (Linux), `global d:private_extern` (macOS), a plain `global d` (Windows) | multi-OS libraries | a plain `global` is exported by the `.so` and the dylib (*verified*); `check_asmproj.py` reports a symbol hidden on one OS and exported on another (`ASMSRC022`) |
| ELF's directives only in Linux code | multi-OS sources | macho64 stops on `global f:function`, `:data`, `hidden` and `.note.GNU-stack`; win64 on `hidden`, `:data`; both on `wrt ..plt`/`..got` ("unrecognised symbol type", "symbol `..plt' not defined") |
| `section .note.GNU-stack noalloc noexec nowrite progbits` inside `%ifdef LINUX` | Linux objects others link | the SDK passes `-z noexecstack` itself, but other linkers of your `.a` can mark the stack executable |
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
  `.inc`, or remove it with `<AsmSource Remove="helpers.asm" />`.
- **`section .rodata` works everywhere:** the SDK maps it to `.rdata` on Windows, where NASM
  would make an unknown section name executable code.

## Diagnostics

- **NASM's and llvm-mc's errors are MSBuild errors** at their file and line
  (`x.asm(12): error : …`; the SDK runs NASM with `-Xvc`), followed by `ASM0007`: the object
  was deleted, so the next build assembles the source again. IDEs list them and open the line.
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
  `ASM0007`, `ASM0010`-`ASM0012` (RIDs), `ASM0015` (freestanding macOS program),
  `ASM0020`-`ASM0024` (source selection), `ASM0030` (`ExportsFile`), `ASM0040`-`ASM0042`
  (.NET consumers), `ASM0043`-`ASM0046` (`BinariesCopyPath`: a bad value, two files on one
  path, the loader not written, two wrappers that disagree), `ASM0050`, `ASM0060`, `ASM0061`
  (packages), `ASM0070` (C library
  stand-in), `ASM0080`-`ASM0082` (image checks), `ASM0100`-`ASM0108` (0.1.0 settings).
  `references/project-reference.md` has each one's cause and fix.

## IDEs

Rider, Visual Studio and VS Code show an `.asmproj` like a `.csproj`: `.asm` and `.s` files as
`AsmSource`, `.inc` files as `AsmInclude`, and every other file of the folder as `None`
(*verified* through MSBuild). Opening a solution never assembles or links: design-time builds
skip `CoreCompile`. If a user sees an empty project or MSB3073 lld warnings on load, they are on
0.1.0: upgrade. Details: <https://asmfoundation.github.io/AsmSdk/guide/ides.html>.

`references/troubleshooting.md` has every error found so far, with its cause and fix.

## Verify the outputs

`python <this-skill>/scripts/inspect_output.py bin/Debug/freestanding/linux-x64/libhello.so`
reports, per format:

- ELF: shared object, PIE or static executable; `SONAME`, `NEEDED`, `RUNPATH`, the
  interpreter; exported and imported symbols with types and sizes; whether the stack is
  executable;
- PE: DLL or program; its exports, imported DLLs and functions; ASLR and DEP;
- Mach-O: dylib or program; its install name, needed libraries, exports and imports by C name;
- for a static library of any OS, its members and their symbols.

It finds `llvm-readobj` in the restored toolchain package by itself. Use `--expect-type`,
`--expect-export name` and `--expect-needed lib` to turn it into a check.

To *run* the outputs: a Windows build machine runs `win-x64` itself (Windows on Arm runs both
Windows RIDs); Linux outputs run in a container, and `linux-arm64` under QEMU
(`docker run --platform linux/arm64`); macOS outputs need a Mac (Apple silicon runs `osx-x64`
under Rosetta). Files built on Windows have no execute bit, so set it inside the container:

```sh
docker run --rm -v "$PWD:/w" -w /w mcr.microsoft.com/dotnet/runtime:10.0 \
  sh -c 'cp bin/Debug/libc/linux-x64/app /tmp/app && chmod +x /tmp/app && /tmp/app'
```

That image has glibc 2.39, so it runs `libc` programs too; `alpine:3` runs `linux-musl-x64`
ones (*verified*).

## Footguns (verified)

Every row was reproduced with an AsmSdk release.

| Symptom | Cause | Fix |
|---|---|---|
| `ASM0010` after upgrading to 0.3.0 | the project names no RID (`AsmTargetRid` is ignored now) | `<RuntimeIdentifiers>…</RuntimeIdentifiers>` |
| `ASM0023` for an ARM64 RID | NASM only builds x64 | a GNU-syntax `.s` file for ARM64, or drop the RID |
| `unrecognised symbol type 'function'` (macOS), `symbol '..plt' not defined` (Windows, macOS) | ELF's directives in a multi-OS source | `FUNCTION`, `call f PLT` from `asmsdk.inc`; `%ifdef LINUX` for the rest |
| `unknown section name .note.GNU-stack` (macOS) | the note outside `%ifdef LINUX` | wrap it |
| `EntryPointNotFoundException` from .NET on Windows only | a plain `global` is no DLL export | `FUNCTION`, or an `ExportsFile` |
| `ASM0080` / `ASM0081` | an absolute address (no `default rel`, `mov rax, label`, `dq label` in `.rodata`) | `default rel`, `lea`, offset tables |
| `ASM0100`-`ASM0108` after upgrading from 0.1.0 | a 0.1.0 setting (`AsmLibraryName`, `AsmRuntime`, `AsmDefine`…) | the .NET name each error gives |
| `Ambiguous project name 'x'` at restore | two projects share an `AssemblyName`, and `PackageId` defaults to it | a `<PackageId>` per project |
| `NU1201` / `NU1202` | a `freestanding` project references `libc`-only code | make it `libc`, or multi-target the reference |
| Edited a shared `.inc`, output did not change | include folder outside the project is not a dependency | also list the files as `AsmInclude` items |
| `duplicate symbol` for a helper | an `%include`d `.asm` is also a source | name it `.inc` or `AsmSource Remove` |
| Consumers can't `%include` a packaged library's file | the project had no `include/` folder | move public `.inc` files into `include/` |
| `attempted static link of dynamic object` | Linux freestanding `Exe` given a `.so` | produce a static library (`StaticLibrary` / `AsmProduceStaticLibrary`) |
| `-rpath $ORIGIN` came out empty | on Linux/macOS build machines the link command runs through `/bin/sh` | quote it there: `'$ORIGIN'` (see `references/runtimes-and-linking.md`) |
| `undefined symbol: <C fn>` in a `libc` `Exe` | missing from that OS's stand-in list | `<AsmLibcSymbol Include="fn" />` |
| `MSB4025 … ProjectType '' not found` | `.slnx` entry without a type | add the type GUID |
| `ASM0006` on an Intel Mac or Alpine | no toolchain package for that build machine | `AsmToolchain=System`, or `AsmToolchainDirectory` |
| `ASM0040` in a RID-specific .NET build | an asm reference lists no RID that serves the app's RID (also for an optional component) | add the RID to the asm project, or build the app portable |
| `ASM0044` with `BinariesCopyPath="native"` | a portable build of several RIDs of one OS puts two `x.dll` (or `libx.so`) in one folder | `native/{rid}`, or one RID per OS on the reference |
| The app's folder holds two layouts of one library after `dotnet build -o out` | `-o` is every project's output folder, so a wrapper library in between copies its own layout there too | `dotnet publish -o` (no such effect), or the app's own `OutDir` |
| `bin/Debug/net10.0/win-x64/` holds both a RID's library and a whole `-r win-x64` build | `RidFolders` in a portable build uses the same folder names as `dotnet build -r` | `native/{rid}` when you also build for one RID |
| `DllNotFoundException` under NativeAOT with a custom folder | no generated loader: a VB or F# project, below .NET 5, or `AsmGenerateNativeLibraryLoader=false` | keep the app folder for NativeAOT, or a resolver of your own |
| `ASM0019 … absolute addressing not supported!` (wasm, after 0.3.0) | a `.set`/`.equ`/`=` constant in a `.wasm.s` source | the number itself, or a macro emitting `i32.const N` (`references/webassembly.md`) |
| `ASM0054` (wasm, after 0.3.0) | a .NET WebAssembly app without .NET's native wasm build for its .NET version | `wasm-tools`, or `wasi-experimental` + WASI SDK 25.0, on the SDK of the app's .NET (a .NET 10 SDK for net10.0: SDK 11.0.100's `wasm-tools-net10` did not build such apps) |
| asm 10-30x faster than C# in a browser, but not in Node | a .NET browser *build* runs with the debugger on in Chromium/Firefox (`debugLevel -1`): unoptimized interpreter, no jiterpreter | time a publish, or `<WasmDebugLevel>0</WasmDebugLevel>` |

## References: read the one the task needs

| File | Read it when |
|---|---|
| `references/project-reference.md` | you need any property, item, metadata, target, generated file or error, with its exact default |
| `references/platforms.md` | choosing RIDs, sources per platform and qualifiers, `asmsdk.inc` / `asmsdk-gnu.inc`, exports per OS, the C library per OS, build machines |
| `references/runtimes-and-linking.md` | choosing `freestanding` or `libc`, entry points per OS, the C library stand-ins, the exact link lines, rpath, `-z defs`, stripping, platform limits |
| `references/nasm-for-asmsdk.md` | writing or fixing NASM sources: position-independent code, symbols, sections, includes, calling conventions, Linux system calls, templates |
| `references/dependencies-and-packaging.md` | ProjectReference and PackageReference flows, pack layout per RID, consumer props, versions, feeds, publishing |
| `references/interop.md` | calling asm from .NET (P/Invoke by RID, publishing, single file, NativeAOT, tests) or Python, or writing a C header |
| `references/toolchain.md` | Bundled or System toolchain, the tools and versions, offline builds, unsupported hosts, provenance |
| `references/ci-and-release.md` | GitHub Actions on several machines, caching, running the outputs, versioning from tags, trusted publishing |
| `references/troubleshooting.md` | any error message: exact text, cause, fix |
| `references/internals.md` | the target graph and incremental rules, the RID outer build, extending the build (generated includes, post-link steps) |
| `references/webassembly.md` | anything `browser-wasm` / `wasi-wasm` (the release after 0.3.0): sources and macros, PROTO on wasm, .NET WebAssembly apps, modules for JavaScript, WASI programs, packages, the measured traps |

## Scripts

All three need only Python 3.8+ and read nothing outside the paths given (and the NuGet cache).

- `scripts/new_asmproj.py <dir> --kind library|static|exe|objects [--framework libc]
  [--rids "win-x64;linux-x64"] [--assembly-name n] [--sln x.slnx]
  [--package-id Id --version 1.0.0] [--sdk-version 0.3.0]` scaffolds a project; existing
  files are reported and left alone.
- `scripts/check_asmproj.py <path> [--json] [--no-info]` lints projects and sources for the
  footguns above, judging each source for the RIDs and OSes it builds (a RID-less project takes
  its referencing projects' RIDs; with none known, platform findings are warnings). It reads
  the SDK's C library lists from the NuGet cache when that version is restored. It exits 1 when
  it finds an error-level problem.
- `scripts/inspect_output.py <file> [--json] [--expect-type t] [--expect-export s]
  [--expect-needed lib] [--expect-nonexec-stack] [--readobj path]` summarizes an ELF, PE or
  Mach-O output or a static library. It exits 1 when an expectation fails.

## Limits of AsmSdk 0.3.0

- Seven RIDs: x86-64 and ARM64 on Windows, Linux (glibc, and musl on x64) and macOS. No 32-bit
  targets, no `linux-musl-arm64` build of its own (the RID graph serves it from `linux-arm64`
  for .NET consumers), no RISC-V. No WebAssembly in 0.3.0 (`ASM0011`): `browser-wasm` and
  `wasi-wasm` come with the next release (`references/webassembly.md`).
- Languages: NASM for x64, GNU syntax (llvm-mc) for ARM64 and for x64 files that name a
  qualifier. No MASM, no C compiler.
- macOS has no freestanding programs (`ASM0015`); a `libc` program needs glibc 2.34+ on Linux.
- A static glibc executable needs a real sysroot: use `AsmToolchain=System` on Linux.
- The consumer targets skip static libraries, so NativeAOT's `DirectPInvoke` is wired by hand,
  and a RID-specific .NET build stops (`ASM0040`) for an asm reference that does not list its RID.
