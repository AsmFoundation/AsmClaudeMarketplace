# The toolchain: AsmFoundation.Sdk 0.1.0

AsmSdk needs three tools: an assembler (NASM), an ELF linker and an archiver. By default
they come from a NuGet package, so a build machine needs only the .NET SDK.

## Contents

1. [Bundled toolchain](#bundled-toolchain)
2. [Supported build machines](#supported-build-machines)
3. [Pinning, offline and air-gapped builds](#pinning-offline-and-air-gapped-builds)
4. [System toolchain](#system-toolchain)
5. [Finding the tools yourself](#finding-the-tools-yourself)
6. [Provenance and licenses](#provenance-and-licenses)

## Bundled toolchain

`AsmToolchain=Bundled` is the default.

- **Restore:** it adds
  `<PackageDownload Include="AsmFoundation.Toolchain.$(AsmHostRid)" Version="[$(AsmToolchainVersion)]" />`.
  NuGet extracts that package into the global packages folder: `~/.nuget/packages`, or
  `$NUGET_PACKAGES` when set.
- **Version:** `AsmToolchainVersion` defaults to the version the SDK release was tested
  with (`0.1.0` for SDK 0.1.0, read from the SDK's generated `AsmFoundation.Sdk.Version.props`).
- **What the package holds** (`tools/`), toolchain 0.1.0:

  | Tool | Version | Run as |
  |---|---|---|
  | `nasm` | 3.02 | `nasm -f elf64 …` |
  | `lld` | LLVM 23.1.5 | `lld -flavor gnu …` (`ld.lld`) |
  | `llvm-ar` | LLVM 23.1.5 | `llvm-ar rcsD …` |
  | `llvm-readobj` | LLVM 23.1.5 | not used by the build; for inspecting outputs |

- **Before each build,** `_AsmResolveToolchain` checks that `nasm`, `lld` and `llvm-ar`
  exist. When one is missing it fails with **ASM0001**:
  `The bundled toolchain was not found in '<dir>'. Run 'dotnet restore' …`. This happens
  when:
  - the build ran with `--no-restore` before any restore downloaded the package;
  - the global packages folder was cleaned (`dotnet nuget locals all --clear`);
  - `NUGET_PACKAGES` points somewhere else at build time than it did at restore time.
- **The execute bit:** NuGet does not keep it, so on Linux and macOS the SDK runs
  `chmod +x` on the three tools before every build. It is cheap and idempotent. If your
  global packages folder is read-only, pre-set the bits once, or use
  `AsmToolchainDirectory`.

## Supported build machines

`AsmHostRid` comes from the .NET SDK's own RID (`NETCoreSdkRuntimeIdentifier`):

- the OS becomes `win-`, `osx-` or `linux-`, and the architecture is kept;
- distribution RIDs such as `ubuntu.24.04-x64` become `linux-x64`.

| Build machine | `AsmHostRid` | Package exists (toolchain 0.1.0) |
|---|---|---|
| Windows x64 | `win-x64` | yes (about 39 MB) |
| Linux x64 (glibc) | `linux-x64` | yes (statically built NASM, stripped LLVM tools) |
| Linux x64 musl (Alpine) | `linux-x64` | the same package, but its LLVM tools are official LLVM release binaries built for glibc. Use `AsmToolchain=System` there (`apk add nasm lld llvm`) |
| macOS Apple silicon | `osx-arm64` | yes |
| macOS Intel | `osx-x64` | **no** |
| Linux arm64 | `linux-arm64` | **no** |
| Windows arm64 | `win-arm64` | **no** |

On a machine without a package, restore fails with
`NU1101: Unable to find package AsmFoundation.Toolchain.<rid>`. The options are:

- **`AsmToolchain=System`,** with `nasm` and a GNU-compatible `ld` and `ar` installed;
- **`AsmToolchainDirectory`,** pointing at a folder with `nasm`, `lld` and `llvm-ar` built
  for that machine;
- **`AsmHostRid`, set to a RID the machine can emulate.** For example `win-x64` on Windows
  arm64, where x64 emulation runs the tools.

Every host produces the same Linux x86-64 ELF output, so a team can mix Windows, Linux and
macOS machines.

## Pinning, offline and air-gapped builds

- **Pin a toolchain:** `<AsmToolchainVersion>0.1.0</AsmToolchainVersion>`, for example in
  `Directory.Build.props`. Toolchain packages carry their own version, so a new SDK release
  need not change the tools.
- **Offline builds:** restore once with network access. After that, the global packages
  folder satisfies every build. In CI, cache it (see `ci-and-release.md`).
- **Air-gapped builds:**
  - **A mirror:** put `AsmFoundation.Sdk.<v>.nupkg` and
    `AsmFoundation.Toolchain.<rid>.<v>.nupkg` in an internal feed or folder feed, and map
    `AsmFoundation.*` to it in `nuget.config`.
  - **No restore of the toolchain at all:** set
    `<AsmToolchainDirectory>/opt/asm-tools/</AsmToolchainDirectory>`. No download happens,
    and the folder must hold `nasm`, `lld` and `llvm-ar` (with `.exe` on Windows).
- **The SDK itself:** the SDK package is resolved through `global.json`'s `msbuild-sdks`.
  NuGet's SDK resolver uses the same `nuget.config` feeds. If it cannot find the version,
  the build fails with `MSB4236: The SDK 'AsmFoundation.Sdk' specified could not be found`.

## System toolchain

```xml
<PropertyGroup>
  <AsmToolchain>System</AsmToolchain>
  <!-- optional: full commands, with arguments -->
  <AsmNasmCommand>/usr/local/bin/nasm</AsmNasmCommand>
  <AsmLinkerCommand>ld.lld</AsmLinkerCommand>      <!-- or ld (GNU binutils) -->
  <AsmArchiverCommand>llvm-ar</AsmArchiverCommand>  <!-- or ar -->
</PropertyGroup>
```

- **Use it** when the link needs a real sysroot (a static glibc executable, libraries
  outside the stub), when the build machine has no toolchain package, or when policy
  requires distribution-packaged tools.
- **The same link lines are used** (see `runtimes-and-linking.md`). GNU `ld` accepts all of
  them.
- **GNU `ld` resolves archives in command-line order,** unlike `lld`. List
  `AsmLinkLibrary` items so that each library comes after the code that uses it.
- **GNU `ar rcsD`** produces a deterministic archive too.
- **NASM 2.16** (Ubuntu 24.04's `nasm` package) does not know the two warning names the
  SDK disables. Every source then prints
  `nasm: warning: unknown warning name: reloc-rel-dword [-w+unknown-warning]` (and the
  same for `reloc-abs-qword`). The run still exits 0, even with `TreatWarningsAsErrors`
  (*verified*).
- **NASM 2.16 also lacks NASM 3's `implicit DEFAULT ABS is deprecated` warning**
  (*verified*). A missing `default rel` therefore shows up only as a link error. Prefer
  NASM 3.x.

## Finding the tools yourself

For inspecting outputs or reproducing a build step by hand:

```text
<global-packages>/asmfoundation.toolchain.<rid>/<version>/tools/{nasm,lld,llvm-ar,llvm-readobj}[.exe]
<global-packages> = $NUGET_PACKAGES, or ~/.nuget/packages (%USERPROFILE%\.nuget\packages on Windows)
```

- `scripts/inspect_elf.py` looks there automatically.
- `dotnet build -v:n` prints every NASM and `lld` command line exactly as run, and each
  can be re-run by hand from the project folder.

## Provenance and licenses

- **How the packages are built:** the AsmSdk repository's `toolchain/fetch.py` builds the
  toolchain packages from pins in `toolchain/versions.json`:
  - Windows gets the official NASM binary;
  - Linux (statically) and macOS get NASM built from the official source;
  - every platform gets the official LLVM release's `lld`, `llvm-ar` and `llvm-readobj`.

  Every download is verified against its SHA-256 before use.
- **Licenses:** NASM is BSD-2-Clause, and the LLVM tools are Apache-2.0 WITH LLVM-exception.
  The license texts ship inside the package's `tools/` folder. The SDK itself is Apache-2.0.
