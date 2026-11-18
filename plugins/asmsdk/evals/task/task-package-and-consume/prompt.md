---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-package-and-consume]
---

Create from scratch, in the current directory, two x86-64 assembly projects built with AsmFoundation.Sdk 0.2.0 (NASM):

1. `Crc/Crc.asmproj`: a static library whose source `Crc/crc.asm` exports `uint32_t crc_step(uint32_t crc, uint32_t byte)` (any simple bit-by-bit CRC-32 step is fine). Its public include file `crc.inc` declares the function (extern) and `CRC_SEED equ 0xFFFFFFFF`. `dotnet pack` must produce the NuGet package `Acme.Crc` version 1.2.0, and asm projects that reference that package must get crc.inc on their include path automatically.
2. `Tool/Tool.asmproj`: a freestanding Linux executable (no libc) whose `Tool/main.asm` includes crc.inc, calls crc_step(CRC_SEED, 0x61) and exits with status 0. It must consume Acme.Crc as a NuGet package by version (a PackageReference), not through a project reference.

Packages are restored from a local folder feed `packages/` in the current directory (filled by `dotnet pack Crc/Crc.asmproj -o packages`) plus nuget.org. Write every file that is needed to disk, in the current directory. You cannot run commands. Keep explanations short.
