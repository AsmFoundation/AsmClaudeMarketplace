# The toolchain: AsmFoundation.Sdk 0.3.0

AsmSdk builds with four tools: two assemblers, NASM for x64 code and LLVM's `llvm-mc` for
GNU-syntax code (ARM64), a linker (`lld`, which links ELF, PE/COFF and Mach-O) and an archiver
(`llvm-ar`). A fifth, `llvm-readobj`, ships alongside them for inspecting what was built. All
of them come from one NuGet package per build machine, so the .NET SDK is the only thing a
build machine needs.

| Package | Build machine |
|---|---|
| [`AsmFoundation.Toolchain.win-x64`](https://www.nuget.org/packages/AsmFoundation.Toolchain.win-x64) | Windows x64 |
| [`AsmFoundation.Toolchain.win-arm64`](https://www.nuget.org/packages/AsmFoundation.Toolchain.win-arm64) | Windows on Arm |
| [`AsmFoundation.Toolchain.linux-x64`](https://www.nuget.org/packages/AsmFoundation.Toolchain.linux-x64) | Linux x64 (glibc) |
| [`AsmFoundation.Toolchain.linux-arm64`](https://www.nuget.org/packages/AsmFoundation.Toolchain.linux-arm64) | Linux ARM64 (glibc) |
| [`AsmFoundation.Toolchain.osx-arm64`](https://www.nuget.org/packages/AsmFoundation.Toolchain.osx-arm64) | macOS on Apple silicon |

Every package builds the same outputs, for all seven runtime identifiers: Windows, Linux
(glibc and musl) and macOS, on x64 and ARM64. A team can mix Windows, Linux and macOS
machines.

## Contents

1. [How a build gets it](#how-a-build-gets-it)
2. [What is in it](#what-is-in-it)
3. [Supported build machines](#supported-build-machines)
4. [The tools](#the-tools)
5. [Pinning, offline and system tools](#pinning-offline-and-system-tools)
6. [How the packages are built](#how-the-packages-are-built)

## How a build gets it

- **You never reference the package yourself.** Restore adds this to every `.asmproj`:

  ```xml
  <PackageDownload Include="AsmFoundation.Toolchain.$(AsmHostRid)" Version="[$(AsmToolchainVersion)]" />
  ```

  NuGet extracts the package into the global packages folder: `~/.nuget/packages`, or
  `$NUGET_PACKAGES` when set.
- **`AsmToolchainVersion` defaults to the version the SDK release was tested with:** `0.1.0`
  for SDK 0.1.0 and 0.2.0, and `0.2.0` for SDK 0.3.0, which needs its `llvm-mc`. Toolchain
  packages carry their own version, so a new SDK release does not download unchanged tools
  again.
- **A `PackageDownload` is not a dependency.** Packages built from your projects do not list
  the toolchain, and their consumers download their own.
- **Before each build,** the SDK checks that the tools are present. If one is missing, the
  build stops with `ASM0001` and the fix: run `dotnet restore`.
- **On Linux and macOS** the SDK also restores the tools' execute bit, which NuGet does not
  keep.

## What is in it

Toolchain 0.2.0:

| Tool | Version | Used for |
|---|---|---|
| `nasm` | 3.02 | assembling `.asm` sources: `-f win64`, `elf64` or `macho64` |
| `llvm-mc` | LLVM 23.1.5 | assembling `.s` sources (GNU syntax), for the target triple of each RID. New in 0.2.0 |
| `lld` | LLVM 23.1.5 | linking: `lld -flavor gnu` (`ld.lld`) for Linux, `-flavor link` (`lld-link`) for Windows, `-flavor darwin` (`ld64.lld`) for macOS; and writing import libraries (`-flavor link -lib`) |
| `llvm-ar` | LLVM 23.1.5 | writing static libraries (`llvm-ar rcsD`), in each OS's archive format |
| `llvm-readobj` | LLVM 23.1.5 | not used by the build; inspecting outputs |

Toolchain 0.1.0 had no `llvm-mc`: a `.s` source, or an ARM64 `libc` build, stops with
`ASM0004` there.

[The tools](toolchain.md#the-tools) shows the exact command lines the build runs, and how to run each
tool yourself.

## Supported build machines

`AsmHostRid` comes from the .NET SDK's own runtime identifier:

- the operating system becomes `win-`, `osx-` or `linux-`, and the architecture is kept;
- distribution identifiers such as `ubuntu.24.04-x64` become `linux-x64`.

| Build machine | `AsmHostRid` | Toolchain 0.2.0 | Toolchain 0.1.0 |
|---|---|---|---|
| Windows x64 | `win-x64` | yes | yes |
| Windows on Arm | `win-arm64` | yes: native LLVM tools; NASM's x64 build runs under Windows' x64 emulation | no |
| Linux x64 (glibc) | `linux-x64` | yes | yes |
| Linux ARM64 (glibc) | `linux-arm64` | yes: NASM built from source | no |
| macOS on Apple silicon | `osx-arm64` | yes | yes |
| Linux x64 with musl (Alpine) | `linux-musl-x64` | no: LLVM's Linux tools are glibc programs | no |
| macOS on Intel | `osx-x64` | no: LLVM publishes no Intel Mac build | no |

On a machine without a package, the build stops with `ASM0006`, before restore tries to
download one. You have three options:

- **Use the machine's own tools** with `AsmToolchain=System`: Homebrew's or Alpine's `nasm`,
  `llvm` and `lld` packages have all of them.
- **Point `AsmToolchainDirectory`** at a folder of tools built for that machine.
- **Emulate a supported machine:** set `AsmHostRid` to one the machine can run.

All three are described in [Pinning, offline and system tools](toolchain.md#pinning-offline-and-system-tools).

## The tools

The five tools in `AsmFoundation.Toolchain`, the exact commands the build runs with them,
and how to run them yourself.

### Where they are

```text
<global packages>/asmfoundation.toolchain.<rid>/<version>/tools/
    nasm[.exe]  llvm-mc[.exe]  lld[.exe]  llvm-ar[.exe]  llvm-readobj[.exe]
    VERSIONS.txt  LICENSE.nasm.txt  LICENSE.llvm.txt

<global packages> = $NUGET_PACKAGES, or ~/.nuget/packages (%USERPROFILE%\.nuget\packages on Windows)
```

For example, after a restore on Windows:
`%USERPROFILE%\.nuget\packages\asmfoundation.toolchain.win-x64\0.2.0\tools\nasm.exe`.

`dotnet build -v:n` prints every command exactly as run. Copy one and run it from the
project folder to experiment.

### NASM 3.02

The build runs NASM once per `.asm` source of each x64 RID, from the project folder:

```text
nasm -f elf64 [-g -F dwarf] -w+all -w-reloc-rel-dword -w-reloc-abs-qword [-w+error] $(AsmFlags)
     -I"<project>/include/" -I"<project>/" -I"<references and packages>/"... -I"<sdk>/include/"
     -DDEBUG -DFREESTANDING -DLINUX -DX64 ...
     -o "<project>/obj/Debug/freestanding/linux-x64/asm/obj/hello.o" "<project>/hello.asm"
```

- The format is `-f win64` for Windows, with `-D.rodata=.rdata`, and `-f macho64` for macOS,
  with `--gprefix _` (Mach-O's underscore on every global and extern).
- Debug builds add `-g -F dwarf`, or `-g -F cv8` (CodeView) for Windows. `-w+error` comes
  with `TreatWarningsAsErrors`.
- All paths use forward slashes on every OS, because a backslash right before a closing
  quote would escape the quote on Windows.

**A listing shows the machine code next to each line** (the bytes on the home page came
from one):

```sh
nasm -f elf64 -l hello.lst -o hello.o hello.asm
```

```text
     5 00000000 8D0437                      lea     eax, [rdi + rsi]
     6 00000003 C3                          ret
```

**For MSBuild diagnostics,** add `<AsmFlags>-Xvc</AsmFlags>`. NASM then reports
`hello.asm(5): error : …`, which MSBuild counts and IDEs link to.

### llvm-mc 23.1.5

The build runs `llvm-mc` once per `.s` source of each RID, with the RID's target triple:

```text
llvm-mc --triple=aarch64-linux-gnu --filetype=obj [-g] $(AsmLlvmMcFlags)
        -I "<project>/include/" ... -I "<sdk>/include/"
        --defsym=DEBUG=1 --defsym=FREESTANDING=1 --defsym=LINUX=1 --defsym=ARM64=1
        -o "<project>/obj/Debug/freestanding/linux-arm64/asm/obj/hello.o" "<project>/hello.s"
```

| RID | Triple |
|---|---|
| `win-arm64` / `win-x64` | `aarch64-pc-windows-msvc` / `x86_64-pc-windows-msvc` |
| `linux-arm64` / `linux-x64` | `aarch64-linux-gnu` / `x86_64-linux-gnu` |
| `linux-musl-x64` | `x86_64-linux-musl` |
| `osx-arm64` / `osx-x64` | `arm64-apple-macos11.0` / `x86_64-apple-macos11.0` (`AsmMacOSMinimumVersion`) |

- `-g` (DWARF) is added in Debug builds, except for Windows, whose debuggers read PDBs.
- `--defsym` takes integers only: a define `NAME` becomes `NAME=1`, and a non-numeric value
  is llvm-mc's error.

**A listing** shows the encoding of each instruction:
`llvm-mc --triple=aarch64-linux-gnu --show-encoding hello.s`.

### lld 23.1.5

The package's `lld` is LLVM's multi-flavor linker, one program with three drivers. The build
runs it as `lld -flavor gnu` (`ld.lld`, GNU `ld`'s command line) for Linux,
`lld -flavor link` (`lld-link`, Microsoft `link.exe`'s) for Windows, and
`lld -flavor darwin` (`ld64.lld`, Apple `ld`'s) for macOS:

```text
lld -flavor gnu -shared -soname libhello.so -Bsymbolic -z relro -z now --hash-style=gnu
    -o ".../bin/Debug/freestanding/linux-x64/libhello.so" ".../obj/Debug/freestanding/linux-x64/asm/obj/hello.o"
    [link inputs] [C library stub] -z noexecstack --build-id=sha1 [ExportsFile] [LinkerArg items]

lld -flavor link -dll -noentry -out:".../win-x64/hello.dll" -implib:".../win-x64/hello.dll.lib"
    ".../hello.o" [link inputs] [ucrtbase.lib] kernel32.lib -nodefaultlib -machine:x64 -Brepro

lld -flavor darwin -dylib -install_name @rpath/libhello.dylib -o ".../osx-arm64/libhello.dylib"
    ".../hello.o" [link inputs] [libSystem.tbd] -arch arm64 -platform_version macos 11.0 11.0
```

[Runtimes and linking](runtimes-and-linking.md#the-exact-link-lines) has the line
for each kind of output on each OS. The drivers differ from GNU `ld` in two ways that matter
here:

- **They resolve symbols from archives regardless of their order** on the command line.
- **ld.lld refuses text relocations by default.** That is why non-PIC code in a Linux shared
  library fails with `recompile with -fPIC`. lld-link and ld64.lld accept some fixups their
  loaders cannot apply, which the SDK then reports itself (`ASM0080`, `ASM0081`).

`lld -flavor link -lib -def:<file>.def -machine:x64 -out:<file>.lib` also writes the import
libraries the SDK links Windows outputs against (kernel32, the UCRT).

### llvm-ar 23.1.5

```text
llvm-ar rcsD --format=gnu ".../bin/Debug/freestanding/linux-x64/libhello.a" ".../obj/Debug/freestanding/linux-x64/asm/obj/hello.o" ...
```

`r` replaces members, `c` creates the archive, `s` writes the symbol index that linkers
need, and `D` makes the archive deterministic (zero timestamps, owners and modes). The format
is the OS's: `gnu` for Linux, `coff` for Windows (`hello.lib`), `darwin` for macOS. The build
deletes the archive first, so members of removed sources do not linger.

To list an archive's members: `llvm-ar t libhello.a`.

### llvm-readobj 23.1.5

The build does not use it. It is there to check what was built, in every format:

| Question | Command |
|---|---|
| Which format and CPU? | `llvm-readobj --file-headers <file>` (`Format: COFF-ARM64`, `elf64-x86-64`, `Mach-O arm64`, …) |
| What does a DLL export and import? | `llvm-readobj --coff-exports --coff-imports hello.dll` |
| What does a dylib export, and which libraries does it load? | `llvm-readobj --symbols --needed-libs libhello.dylib` (`Extern` marks an export) |
| Shared object, PIE or static executable? | `llvm-readobj --file-headers --dynamic-table app` (a PIE is `SharedObject` with `FLAGS_1 PIE`) |
| SONAME, NEEDED, RUNPATH | `llvm-readobj --dynamic-table libhello.so` |
| What is exported, with types and sizes? | `llvm-readobj --dyn-syms libhello.so` |
| Is the stack executable? | `llvm-readobj --program-headers libhello.so` (look for `PT_GNU_STACK` without `PF_X`) |
| Which relocations are left for the loader? | `llvm-readobj -r libhello.so` |
| All of it, for a script | `llvm-readobj --elf-output-style=JSON --file-headers --dynamic-table --dyn-syms libhello.so` |

For GNU `readelf`-style output, add `--elf-output-style=GNU`; the same binary copied as
`llvm-readelf` defaults to it. The
[asmsdk Claude Code plugin](../scripts/inspect_output.py) includes
`inspect_output.py`. It finds this binary in the package cache by itself and prints one
summary per file. It can also check expectations in CI, such as "exports `hello_add`" or
"needs `libc.so.6`".

## Pinning, offline and system tools

### Pin a toolchain version

```xml
<!-- Directory.Build.props -->
<PropertyGroup>
  <AsmToolchainVersion>0.1.0</AsmToolchainVersion>
</PropertyGroup>
```

Without this, each project uses the version its SDK release was tested with. Pinning keeps
the tools fixed across SDK upgrades, until you change the pin.

### Offline builds

Restore once with network access. After that, the global packages folder satisfies every
build. In CI, cache that folder; [CI and releases](ci-and-release.md) has a
workflow that does.

> [!NOTE]
> `ASM0001` means the toolchain is not where restore puts it. Common causes:
>
> - a build with `--no-restore` on a machine that never restored;
> - a cleared NuGet cache (`dotnet nuget locals all --clear`);
> - `NUGET_PACKAGES` set to different folders at restore time and at build time.

### Air-gapped builds

- **Mirror the packages.** Put `AsmFoundation.Sdk.<v>.nupkg` and
  `AsmFoundation.Toolchain.<rid>.<v>.nupkg` in an internal feed or folder feed, and map
  `AsmFoundation.*` to it in `nuget.config`:

  ```xml
  <configuration>
    <packageSources>
      <clear />
      <add key="internal" value="\\fileserver\nuget" />
    </packageSources>
  </configuration>
  ```

- **Skip the toolchain download entirely.** Point `AsmToolchainDirectory` at a folder that
  holds `nasm`, `llvm-mc`, `lld` and `llvm-ar` (with `.exe` on Windows):

  ```xml
  <AsmToolchainDirectory>/opt/asm-tools/</AsmToolchainDirectory>
  ```

  No `PackageDownload` is added, and the SDK runs the tools from that folder.

The SDK package itself is resolved through `global.json`'s `msbuild-sdks` from the same
feeds. If it cannot be found, the build fails with
`MSB4236: The SDK 'AsmFoundation.Sdk' specified could not be found`.

### System toolchain

```xml
<PropertyGroup>
  <AsmToolchain>System</AsmToolchain>
  <!-- optional: full commands, with arguments -->
  <AsmNasmCommand>/usr/local/bin/nasm</AsmNasmCommand>
  <AsmLlvmMcCommand>llvm-mc</AsmLlvmMcCommand>
  <AsmLinkerCommand>ld.lld</AsmLinkerCommand>      <!-- or ld (GNU binutils), for Linux RIDs -->
  <AsmLinkerCommand Condition="$(RuntimeIdentifier.StartsWith('win-'))">lld-link</AsmLinkerCommand>
  <AsmLinkerCommand Condition="$(RuntimeIdentifier.StartsWith('osx-'))">ld64.lld</AsmLinkerCommand>
  <AsmArchiverCommand>llvm-ar</AsmArchiverCommand>  <!-- or ar -->
</PropertyGroup>
```

With `AsmToolchain=System`, the SDK runs `nasm`, `llvm-mc`, `ld` and `ar` from `PATH`, or the
commands you name.

**When to use it:**

- a link that needs a real Linux sysroot, such as a static glibc executable;
- a build machine with no toolchain package (Alpine, Intel macOS): Homebrew's and Alpine's
  `nasm`, `llvm` and `lld` packages have every tool;
- a policy that requires distribution-packaged tools.

**What changes:**

- **Windows and macOS RIDs need an LLVM linker.** The default, `ld`, is GNU `ld`, which links
  ELF only, so a Windows or macOS RID without `AsmLinkerCommand` stops with `ASM0005`. Name
  `lld-link` (it also writes the SDK's import libraries, as `lld-link -lib`) or `ld64.lld`,
  conditioned on the RID as above.
- **So does the Linux RID of the other architecture.** A distribution's GNU `ld` links its own
  machine's ELF only (Ubuntu x64's has no AArch64 emulation, and stops with "file in wrong
  format"), so `linux-arm64` on an x64 machine, or `linux-x64` on an ARM64 one, stops with
  `ASM0005` before any tool runs. `ld.lld` links every architecture, as in the example above;
  a cross `ld` such as `aarch64-linux-gnu-ld` works when named. A static library never links,
  and is not checked.
- **The link lines stay the same,** and GNU `ld` accepts the Linux ones for its own architecture.
- **GNU `ld` resolves archives in command-line order,** unlike `ld.lld`. List
  `AsmLinkLibrary` items so that each library comes after the code that uses it.
- **NASM 2.16** (Ubuntu 24.04's `nasm` package) does not know the two warning names the SDK
  turns off. Every source then prints `nasm: warning: unknown warning name: reloc-rel-dword`.
  This is harmless: NASM still exits 0, even with `TreatWarningsAsErrors`.
- **NASM 2.16 lacks NASM 3's `implicit DEFAULT ABS is deprecated` warning.** A missing
  `default rel` then shows up only as a link error. Prefer NASM 3.

Any other `AsmToolchain` value fails with `ASM0002`.

## How the packages are built

Every toolchain package is built from official upstream releases, pinned by SHA-256. The
build is in the AsmSdk repository:
[`toolchain/fetch.cs`](https://github.com/AsmFoundation/AsmSdk/blob/main/toolchain/fetch.cs),
a .NET 10 file-based app, reads its pins from
[`toolchain/versions.json`](https://github.com/AsmFoundation/AsmSdk/blob/main/toolchain/versions.json).

### Where each tool comes from

| Tool | Windows x64 and Windows on Arm | Linux x64 and Linux ARM64 | macOS arm64 |
|---|---|---|---|
| `nasm` 3.02 | the official NASM Windows binary (x64; Windows on Arm runs it under its x64 emulation, since NASM publishes no ARM64 Windows build) | built from the official NASM source on a machine of that CPU, statically linked and stripped | built from the official NASM source, natively for arm64 |
| `llvm-mc`, `lld`, `llvm-ar`, `llvm-readobj` (LLVM 23.1.5) | the official LLVM release archive for that CPU | the official LLVM release archive for that CPU (binaries stripped) | the official LLVM release archive |

- **Only four members are extracted from LLVM.** The release archives are large, so
  `fetch.cs` streams them and keeps only `llvm-mc`, `lld`, `llvm-ar` and `llvm-readobj`. It decodes
  `.tar.xz` with SharpCompress, since .NET has no xz decoder. On the 901 MB Windows archive
  that took 83.5 s, against 78.0 s for Python's lzma, the decoder of the earlier `fetch.py`,
  and staged byte-identical tools.
- **macOS binaries are not stripped,** because stripping would break their code
  signatures.

### The pins

Toolchain package version 0.2.0 (0.1.0 used the same downloads, minus the two ARM64 ones):

| Download | SHA-256 |
|---|---|
| `nasm-3.02.tar.xz` (source) | `87336eba53b4acfe917424ab5d500d2b0054d9f5148d35c2273ccf2cfb712f0d` |
| `nasm-3.02-win64.zip` | `161d0bfaff53c2f9e9f3e69fd0672323ebabafd1268976a5cec11be92a19aee7` |
| `clang+llvm-23.1.5-x86_64-pc-windows-msvc.tar.xz` | `62fdada7f6fa2b73856486dfbbdba3d2c1882991621615bcb55c60207611c6d4` |
| `clang+llvm-23.1.5-aarch64-pc-windows-msvc.tar.xz` | `f06382f2c99c68a4e80f7044446df1fcf52bc3cc05158626bd0b966d51a5369a` |
| `LLVM-23.1.5-Linux-X64.tar.xz` | `f72edb0b36580ece7f52e23858f00c18fad4e87395ea7ad05d7e55c39f8fc78a` |
| `LLVM-23.1.5-Linux-ARM64.tar.xz` | `44f1e4b7a125b2763d56386a199928dd57ec32e151cc6042dce2f7b0da7bb651` |
| `LLVM-23.1.5-macOS-ARM64.tar.xz` | `aba592b4a15e8f90c634c5367b51ec8418b8bcd2829865db331a17dc9418dcff` |
| LLVM `LICENSE.TXT` (llvmorg-23.1.5) | `8d85c1057d742e597985c7d4e6320b015a9139385cff4cbae06ffc0ebe89afee` |

`fetch.cs` verifies each hash before it opens the file. Inside each package,
`tools/VERSIONS.txt` records the exact tool versions.

### Building a toolchain package yourself

```sh
dotnet run toolchain/fetch.cs -- --rid win-x64   # or win-arm64, linux-x64, linux-arm64, osx-arm64: downloads, verifies, stages
dotnet pack toolchain/AsmFoundation.Toolchain.csproj -p:ToolchainRid=win-x64 -o artifacts/packages
```

`fetch.cs` keeps its downloads in a cache keyed by hash, so a second run downloads nothing.
NASM is built from source on Linux and macOS, which needs a C compiler and `make` on that
machine, of the package's CPU: the `linux-arm64` package is staged on an ARM64 machine.

### Licenses

| Component | License | In the package |
|---|---|---|
| NASM | BSD-2-Clause | `tools/LICENSE.nasm.txt` |
| LLVM tools | Apache-2.0 WITH LLVM-exception | `tools/LICENSE.llvm.txt` |
| AsmFoundation.Sdk and the packaging | Apache-2.0 | `LICENSE` |

The package license expression is
`BSD-2-Clause AND Apache-2.0 WITH LLVM-exception AND Apache-2.0`.
