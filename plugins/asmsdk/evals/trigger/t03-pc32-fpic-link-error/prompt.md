---
max_turns: 5
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger, should-trigger]
---

dotnet build of my assembly library project fails with `lld : error : relocation R_X86_64_PC32 cannot be used against symbol 'crc_fold'; recompile with -fPIC`. crc_fold is defined in another .asm file of the same project. How do I fix it?
