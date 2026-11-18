---
name: asmsdk
description: Build, reference, package and release x86-64 assembly with AsmSdk (the AsmFoundation.Sdk MSBuild SDK) - .asmproj projects that turn NASM sources into Linux shared libraries, static libraries and executables with dotnet build, share them as versioned NuGet packages and P/Invoke them from .csproj projects. Use it whenever an .asmproj, AsmFoundation.Sdk, AsmFoundation.Toolchain or an msbuild-sdks entry for assembly is involved, or the user wants to build, link, version, package, test or ship NASM code with MSBuild, dotnet build or pack, NuGet, a .sln or .slnx, or CI - including link errors such as "recompile with -fPIC", "undefined symbol" or "attempted static link of dynamic object", ASM0xxx errors, TargetFramework libc and the libc stub, include paths and DefineConstants, an .asmproj that looks empty in an IDE, and calling assembly from C# or Python - even when AsmSdk is not named. Not for MASM, GAS, Windows or macOS object formats, CMake or Makefile builds, or questions about what an instruction does.
---

# AsmSdk: x86-64 assembly projects on MSBuild and NuGet

AsmSdk is the AsmFoundation's project, dependency and build management for x86-64
assembly. An `.asmproj` is to NASM what a `.csproj` is to C#:

- `dotnet build` assembles and links it;
- `ProjectReference` and `PackageReference` share code between projects;
- `dotnet pack` turns it into a versioned NuGet package.

Restore downloads a bundled toolchain (NASM 3.02, plus LLVM 23.1.5's `ld.lld`,
`llvm-ar` and `llvm-readobj`) as a NuGet package. So a Windows, Linux or macOS build
machine produces the same **Linux x86-64 ELF**, and needs nothing installed beyond the
.NET SDK.

This skill documents **AsmFoundation.Sdk 0.2.0**. Each behavior marked *verified* was
measured by building with an AsmSdk release and its bundled tools; where 0.2.0 changed a
behavior, AsmSdk's own end-to-end tests verify the new one. If `global.json` pins another
version, check the SDK's documentation site, <https://asmfoundation.github.io/AsmSdk/>
(or that release's `docs/asmproj.md`), where the two might differ. The site has the same
facts written for people, so it is the page to link a user to.

**0.2.0 renamed every setting to .NET's own** (`AssemblyName`, `TargetFramework`,
`DefineConstants`, `DebugSymbols`, `StartupObject`, `LinkerArg`/`ExportsFile`, `OutputType`),
with no compatibility layer. A 0.1.0 project (`AsmLibraryName`, `AsmRuntime`, `AsmDefine`…)
fails with `ASM0100`-`ASM0108`, each naming its replacement; the
[changelog](https://github.com/AsmFoundation/AsmSdk/blob/main/CHANGELOG.md) has the table.
`check_asmproj.py` reports them all before a build (`ASMPRJ013`).

`<this-skill>` below stands for the skill's base directory, which is shown when the skill
loads. The scripts live in its `scripts/` folder, and the references in `references/`.

## Orient yourself first

1. **Find the pieces:**
   - `*.asmproj`;
   - `global.json` (`"msbuild-sdks": { "AsmFoundation.Sdk": "<version>" }`);
   - `*.slnx` / `*.sln`;
   - `nuget.config`;
   - `Directory.Build.props` and `Directory.Packages.props`.
2. **Lint before you reason:** `python <this-skill>/scripts/check_asmproj.py <repo-or-project>`
   reports the footguns below, with the file, line and fix. It reads files only.
3. **Build:** `dotnet build`. When a build fails with `MSB3073`, the real message is the
   NASM or `lld` line printed just above it (see [Diagnostics](#diagnostics)).
4. **Inspect the outputs:** use `python <this-skill>/scripts/inspect_elf.py <file>` rather
   than reasoning about them (see [Verify the outputs](#verify-the-outputs)).

## The model in one screen

```text
global.json            { "msbuild-sdks": { "AsmFoundation.Sdk": "0.2.0" } }
nuget.config           only when the SDK or your packages come from a private or local feed
App.slnx               <Project Path="Hello/Hello.asmproj" Type="13B669BE-BB05-4DDF-9536-439F39A36129" />
Hello/Hello.asmproj    <Project Sdk="AsmFoundation.Sdk"> ... </Project>
Hello/include/*.inc    public include files: referencing projects and package consumers get them
Hello/**/*.asm         every .asm is a source (one NASM run each); every .inc an include file
```

| `OutputType` | Output in `bin/<Configuration>/<tfm>/` | Notes |
|---|---|---|
| `Library` (default) | `lib<name>.so` | position-independent code required |
| `StaticLibrary` | `lib<name>.a` | deterministic archive with a symbol index |
| `Exe` | `<name>` (no extension) | static `_start` (`freestanding`), or a PIE entering `main` (`libc`) |
| `Objects` | nothing; `.o` files in `obj/` | see the known issue in [footguns](#footguns-verified) |

- `<name>` is `AssemblyName`. It defaults to the project name, as in .NET. **`PackageId`
  defaults to it too**, so two projects that share an `AssemblyName` (a `.a` and a `.so` of
  one library) need a `PackageId` each, or restore fails with "Ambiguous project name".
- `<tfm>` is the target framework, `freestanding` or `libc`, as in .NET's
  `bin/Release/net10.0/` (*verified*).
- `AsmProduceStaticLibrary=true` also writes `lib<name>.a` next to a `.so`.
- Objects go to `obj/<Configuration>/<tfm>/asm/obj/<subfolder>/<file>.o`.

**Runtimes are target frameworks.** `freestanding` (the default) links nothing, and the
code makes raw system calls. `libc` links glibc dynamically through a generated `libc.so.6`
stub, so no Linux sysroot is needed. An `Exe` on `libc` then starts in `main` (the SDK's
`crt1` calls `__libc_start_main`), and the program needs **glibc 2.34+** at run time.

- `<TargetFrameworks>freestanding;libc</TargetFrameworks>` builds both, like a
  multi-targeted `.csproj`.
- NuGet enforces what links: a `libc` project may reference `freestanding` code, but a
  `freestanding` project that references `libc`-only code fails at restore (`NU1201` for a
  project, `NU1202` for a package). A .NET project gets the `libc` build of a project that
  targets both (*verified*).

**Configurations and symbols, as in C#:**

- `Debug` defines `DEBUG` and writes DWARF (`DebugSymbols=true`, `-g -F dwarf`).
- `Release` defines `RELEASE` and writes no DWARF (`<DebugSymbols>true</DebugSymbols>` adds it).
- Every build also defines `FREESTANDING` or `LIBC`, so one source can serve both
  frameworks with `%ifdef LIBC` (*verified*).

**Toolchain:** `AsmToolchain=Bundled` (the default) downloads
`AsmFoundation.Toolchain.<host-rid>` during restore, for `win-x64`, `linux-x64` or
`osx-arm64` only. `AsmToolchain=System` uses `nasm`, `ld` and `ar` from PATH.

## Recipes

### Start a project or a solution

```sh
python <this-skill>/scripts/new_asmproj.py Hello --kind library --assembly-name hello --sln App.slnx
```

The script writes `global.json` (when missing), the `.asmproj`, an `include/` file, and a
starter source that follows the linking rules. It also adds the project to the `.slnx`
with the type GUID. It never overwrites a file. Kinds are `library`, `static`, `exe` and
`objects`; `--framework libc` targets glibc, and `--package-id`/`--version` make the
project packable.

By hand, the minimum is a `global.json`, the project file and one `.asm`:

```xml
<Project Sdk="AsmFoundation.Sdk">
  <PropertyGroup>
    <AssemblyName>hello</AssemblyName>      <!-- bin/Debug/freestanding/libhello.so -->
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

Add a `ProjectReference` from the `.csproj` to the `.asmproj`. That reference builds the
asm project and copies `lib<name>.so` next to the program, including on `dotnet publish`.
It adds no assembly reference. From a project that targets both frameworks, the `.csproj`
gets the `libc` build (NuGet's nearest framework to `net10.0`).

```csharp
[LibraryImport("hello", EntryPoint = "hello_add")]   // probes libhello.so on Linux
private static partial int HelloAdd(int a, int b);
```

The `.so` is a Linux x86-64 ELF, so the program runs only on Linux x64. On a Windows build
machine, run it under WSL or in a Docker Linux container. See `references/interop.md` for
marshalling, Python `ctypes`, C headers, and tests.

### Link one asm project into another

`<ProjectReference Include="../Lib/Lib.asmproj" />` in an `.asmproj` does two things:

- it adds the referenced project's public include folder to the include path: its
  `include/`, or its project folder when it has no `include/`;
- it links the referenced project's output: its static library when it has one, otherwise
  its shared library.

- **A freestanding `Exe` links with `-static`, so it needs the static library.** Make the
  library `StaticLibrary`, or set `AsmProduceStaticLibrary=true`. Otherwise:
  `attempted static link of dynamic object` (*verified*).
- **A `freestanding` project cannot reference a `libc`-only one:** restore fails with
  `NU1201`. Make the referencing project `libc`, or let the reference build both
  (`TargetFrameworks=freestanding;libc`).
- **Code that goes into a `.so` must be position-independent,** including code that
  arrives from a `.a`.

### Ship a library as a NuGet package

```xml
<PropertyGroup>
  <OutputType>StaticLibrary</OutputType>     <!-- or Library + AsmProduceStaticLibrary=true -->
  <PackageId>Acme.Crc</PackageId>
  <Version>1.2.0</Version>
</PropertyGroup>
```

`dotnet pack` writes this layout (`<fw>` is the NuGet framework behind each target
framework: netstandard1.0 for `freestanding`, netstandard2.0 for `libc`):

- `include/`, holding `include/**`, once;
- `lib/<fw>/_._`, an empty marker per target framework, so NuGet refuses a `libc`-only
  package to a `freestanding` consumer (`NU1202`) instead of a link failing;
- `native/linux-x64/<tfm>/lib<name>.a`;
- `runtimes/linux-x64/native/lib<name>.so` (`nativeassets/<fw>/` when the project targets both);
- `src/`, when `AsmPackSources=true`;
- a generated `build/<fw>/` and `buildTransitive/<fw>/` `<PackageId>.props`.

A consuming `.asmproj` references the package by version with
`<PackageReference Include="Acme.Crc" Version="1.2.0" />`. It then gets the package's
include folder and its static library (or its `.so` with `AsmPackageLinkKind=Shared`). A
consuming `.csproj` gets the `.so`.

- **Public include files must live in `include/`.** A project without an `include/` folder
  packs **no** include files, and its consumers' `%include` fails. A `ProjectReference`
  would still have worked, because it uses the project folder (*verified*).
- **Central Package Management works,** with `Directory.Packages.props` and a
  `PackageReference` that has no version (*verified*).
- **A `.so` that links a package's `.a` exports that archive's global symbols too.** Add
  `<LinkerArg Include="--exclude-libs ALL" />` to keep them private (*verified*), or list
  the exports in an `ExportsFile` (a version script).

See `references/dependencies-and-packaging.md` for consumer props, transitive flow,
publishing and versioning.

### Run on glibc (`TargetFramework=libc`)

```nasm
default rel
extern printf
section .rodata
fmt: db "%d arguments", 10, 0
section .text
global main:function
main:                               ; int main(int argc, char **argv)
    push    rbx                     ; entered at rsp = 16n+8: one push re-aligns to 16
    mov     esi, edi
    lea     rdi, [fmt]
    xor     eax, eax                ; variadic call: al = number of vector registers used
    call    printf wrt ..plt
    xor     eax, eax
    pop     rbx
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
```

The project sets `<OutputType>Exe</OutputType>` and `<TargetFramework>libc</TargetFramework>`.

- **A function the stub does not list fails to link in an `Exe`** with
  `undefined symbol: strsignal`. Add it with `<AsmLibcSymbol Include="strsignal" />`
  (*verified*).
- **A shared library with that same call links anyway,** and binds the function from glibc
  at load time (*verified*).

The stub's list, versions and limits are in `references/runtimes-and-linking.md`.

### Defines and configurations

- **Add symbols with `DefineConstants`,** as in C#:
  `<DefineConstants>FAST_PATH;LEVEL=3</DefineConstants>` gives `-DFAST_PATH -DLEVEL=3`.
- **The implicit symbols are appended after the project body:** `DEBUG` or `RELEASE`, and
  `FREESTANDING` or `LIBC`. So setting `DefineConstants` never drops them (*verified*).
  `DisableImplicitConfigurationDefines=true` and `DisableImplicitFrameworkDefines=true` turn
  them off.
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
  <AsmFlags>-Xvc</AsmFlags>                          <!-- NASM messages become MSBuild errors -->
  <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
</PropertyGroup>
```

For shared libraries, also consider `<LinkerArg Include="-z defs" />` (an item, in an
`ItemGroup` with the same condition). A `.so` links even with an undefined symbol, so a
misspelled `extern` otherwise fails only when the library loads. With `-z defs` it fails at
the link (*verified*).

## NASM rules that decide whether code links

Every one of these is a *verified* `ld.lld` or NASM 3.02 result. The full explanation and
templates are in `references/nasm-for-asmsdk.md`.

| Rule | Applies to | What breaking it gives |
|---|---|---|
| `default rel` at the top of every source | all | NASM 3: `implicit DEFAULT ABS is deprecated` (an error with `TreatWarningsAsErrors`); `.so`/PIE: `relocation R_X86_64_32S cannot be used against local symbol; recompile with -fPIC` |
| `call fn wrt ..plt` for a function in another object or library | `.so` | `relocation R_X86_64_PC32 cannot be used against symbol 'fn'; recompile with -fPIC` |
| …or define the helper `global fn:function hidden` (visibility **before** any size: `hidden (fn.end - fn)`, `data hidden 8`) | `.so` | the same error. A hidden symbol is also not exported. NASM silently ignores `hidden` written after the size |
| data from another object or library through the GOT: `mov rax, [rel stdout wrt ..got]`, or make it `hidden` | `.so` | `R_X86_64_PC32 cannot be used against symbol 'stdout'` |
| no `mov rax, label` (absolute addresses in `.text`) | `.so`/PIE | `relocation R_X86_64_64 cannot be used against local symbol` |
| jump tables as offsets (`dd t1 - table`), or `dq label` only in a **writable** section | `.so` | `dq label` in `.rodata` (or in a `.data.rel.ro` declared without `write`) fails as above |
| `global name:function` (and `:data`) | exports | the export has type NONE and size 0, which degrades profilers, debuggers and symbolizers |
| `section .note.GNU-stack noalloc noexec nowrite progbits` | objects others link | the SDK passes `-z noexecstack` itself, but other linkers of your `.a` can mark the stack executable |
| `$name` for symbols that are NASM keywords | all | `wait`, `syscall` and `rel` as labels are parse errors |

- **Where `%include` looks:** NASM 3.02 tries the name in the working directory (the
  project folder) first. Then it tries the `-I` folders in order: the project's
  `include/`, the project folder, then referenced projects and packages. It does **not**
  search the folder of the file that holds the `%include` (*verified*). Write paths
  relative to the project folder or an include folder, or add the subfolder as an
  `AsmIncludeDirectory`.
- **Name include files `.inc`.** An `.asm` file pulled in with `%include` is also assembled
  on its own, which links its symbols twice: `duplicate symbol` (*verified*). Rename it
  `.inc`, or remove it with `<AsmSource Remove="helpers.asm" />`.

## Diagnostics

- **NASM messages are not MSBuild diagnostics by default:** the build reports
  `error MSB3073: The command "…nasm…" exited with code 1`, and NASM's own line
  (`file.asm:12: error: …`) is printed above it as plain text. NASM warnings are not counted
  either. `-v:q` hides them all, so build at the default verbosity or `-v:n`.
- **`<AsmFlags>-Xvc</AsmFlags>`** switches NASM to `file.asm(12): error : …`, which MSBuild
  and IDEs count and link to the line (*verified*).
- **`lld` errors are recognized** (`lld : error : undefined symbol: x`). The lines after
  them name the object and the source line.
- **`ASM0001`:** the toolchain package is missing. Run `dotnet restore`, or use
  `AsmToolchain=System`.
- **`ASM0002`:** a bad `AsmToolchain` value.
- **`ASM0003`:** a `TargetFramework` other than `freestanding` or `libc`.
- **`ASM0100`-`ASM0108`:** a 0.1.0 setting; each error names its replacement.

## IDEs

Since 0.2.0, Rider, Visual Studio and VS Code show an `.asmproj` like a `.csproj`: `.asm`
files as `AsmSource`, `.inc` files as `AsmInclude`, and every other file of the folder as
`None` (*verified* through MSBuild). Under 0.1.0 the projects looked empty, because the item
types were not declared (`AvailableItemName`). Opening a solution never assembles or links:
design-time builds skip `CoreCompile`. If a user sees an empty project or MSB3073 lld
warnings on load, they are on 0.1.0: upgrade. Details:
<https://asmfoundation.github.io/AsmSdk/guide/ides.html>.

`references/troubleshooting.md` has every error found so far, with its cause and fix.

## Verify the outputs

`python <this-skill>/scripts/inspect_elf.py bin/Debug/freestanding/libhello.so` reports:

- the ELF type (shared object, PIE or static executable);
- `SONAME`, `NEEDED`, `RUNPATH` and the interpreter;
- the entry point;
- the exported and undefined dynamic symbols;
- whether the stack is executable;
- for an archive, its members and symbols.

It finds `llvm-readobj` in the restored toolchain package by itself. Use
`--expect-export name` and `--expect-needed lib` to turn it into a check.

To *run* the outputs, use Linux x86-64: a Linux CI job, WSL, or a container. Files built
on Windows have no execute bit, so set it inside the container:

```sh
docker run --rm -v "$PWD:/w" -w /w mcr.microsoft.com/dotnet/runtime:10.0 \
  sh -c 'chmod +x bin/Debug/libc/app && ./bin/Debug/libc/app'
```

That image has glibc 2.39, so it runs libc programs too (*verified*).

## Footguns (verified)

Every row was reproduced with an AsmSdk release, except the last one. That one follows
from the toolchain packages that exist: `win-x64`, `linux-x64` and `osx-arm64`.

| Symptom | Cause | Fix |
|---|---|---|
| `ASM0100`-`ASM0108` after upgrading | a 0.1.0 setting (`AsmLibraryName`, `AsmRuntime`, `AsmDefine`…) | the .NET name each error gives |
| `Ambiguous project name 'x'` at restore | two projects share an `AssemblyName`, and `PackageId` defaults to it | a `<PackageId>` per project |
| `NU1201` / `NU1202` | a `freestanding` project references `libc`-only code | make it `libc`, or multi-target the reference |
| outputs are not where a script expects | 0.2.0 adds the target framework folder | `bin/<Configuration>/<tfm>/` |
| Edited a shared `.inc`, output did not change | include folder outside the project is not a dependency | also list the files as `AsmInclude` items |
| `duplicate symbol` for a helper | an `%include`d `.asm` is also a source | name it `.inc` or `AsmSource Remove` |
| Consumers can't `%include` a packaged library's file | the project had no `include/` folder | move public `.inc` files into `include/` |
| `attempted static link of dynamic object` | freestanding `Exe` given a `.so` | produce a `.a` (`StaticLibrary` / `AsmProduceStaticLibrary`) |
| `cannot open …/obj/…/x.o` in a project referencing an `Objects` project | a known issue (0.1.0 and 0.2.0): the object paths are relative to the wrong project | use `StaticLibrary` instead of `Objects` |
| `-rpath $ORIGIN` came out empty | on Linux/macOS build machines the link command runs through `/bin/sh` | quote it there: `'$ORIGIN'` (see `references/runtimes-and-linking.md`) |
| `undefined symbol: <libc fn>` in a `libc` `Exe` | missing from the stub's list | `<AsmLibcSymbol Include="fn" />` |
| `MSB4025 … ProjectType '' not found` | `.slnx` entry without a type | add the type GUID |
| Restore fails for `AsmFoundation.Toolchain.osx-x64` (or `linux-arm64`, `win-arm64`) | no toolchain package for that build machine | `AsmToolchain=System`, or `AsmToolchainDirectory` |

## References: read the one the task needs

| File | Read it when |
|---|---|
| `references/project-reference.md` | you need any property, item, metadata, target, generated file or error, with its exact default |
| `references/runtimes-and-linking.md` | choosing `freestanding` or `libc`, entry points, the libc stub, link lines, rpath, `-z defs`, stripping, glibc and musl limits |
| `references/nasm-for-asmsdk.md` | writing or fixing sources: position-independent code, symbols, sections, includes, the System V ABI, Linux system calls, templates |
| `references/dependencies-and-packaging.md` | ProjectReference and PackageReference flows, pack layout, consumer props, versions, feeds, publishing |
| `references/interop.md` | calling asm from .NET (P/Invoke, publish, tests) or Python, or writing a C header |
| `references/toolchain.md` | Bundled or System toolchain, versions, offline builds, unsupported hosts, the execute bit |
| `references/ci-and-release.md` | GitHub Actions, caching, running the outputs on Linux, versioning from tags, trusted publishing |
| `references/troubleshooting.md` | any error message: exact text, cause, fix |
| `references/internals.md` | the target graph and incremental rules, extending the build (generated includes, post-link steps) |

## Scripts

All three need only Python 3.8+ and read nothing outside the paths given.

- `scripts/new_asmproj.py <dir> --kind library|static|exe|objects [--framework libc]
  [--assembly-name n] [--sln x.slnx] [--package-id Id --version 1.0.0] [--sdk-version 0.2.0]`
  scaffolds a project; existing files are reported and left alone.
- `scripts/check_asmproj.py <path> [--json]` lints projects and sources for the footguns
  above. It exits 1 when it finds an error-level problem.
- `scripts/inspect_elf.py <file> [--json] [--expect-export s] [--expect-needed lib]
  [--readobj path]` summarizes an ELF file or archive. It exits 1 when an expectation
  fails.

## Limits of AsmSdk 0.2.0

- Output is Linux x86-64 ELF only: NASM syntax, System V ABI. There are no Windows PE,
  macOS Mach-O, MASM or GAS projects, and no C compiler.
- A `libc` program needs glibc 2.34+ (`libc.so.6`, `ld-linux-x86-64.so.2`). musl is not
  supported.
- A static glibc executable needs a real sysroot: use `AsmToolchain=System` on Linux.
