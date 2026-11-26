---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-port-to-every-os]
---

Our shared library project `Hash/Hash.asmproj` (AsmFoundation.Sdk 0.4.0) was built for linux-x64 only. We added Windows and macOS:

```xml
<Project Sdk="AsmFoundation.Sdk">
  <PropertyGroup>
    <RuntimeIdentifiers>linux-x64;win-x64;osx-x64</RuntimeIdentifiers>
  </PropertyGroup>
</Project>
```

and `dotnet build` now fails:

```
mix.asm(4): error : unrecognised symbol type `data' on `hash_seed'
mix.asm(4): error : unrecognised symbol type `8' on `hash_seed'
hash.asm(10): error : unknown section name .note.GNU-stack
hash.asm(10): error : segment name `.note.GNU-stack' not recognized
```

The linux-x64 build still links, but its libHash.so exports `mix64` and `hash_seed` besides `hash64`. The two sources are `Hash/hash.asm`:

```nasm
default rel
extern mix64, hash_seed
section .text
global hash64:function
hash64:                 ; uint64_t hash64(uint64_t x)
    mov rax, [rel hash_seed]
    xor rdi, rax
    call mix64
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
```

and `Hash/mix.asm`:

```nasm
default rel
section .data
global hash_seed:data 8
hash_seed: dq 0x9E3779B97F4A7C15
section .text
global mix64:function
mix64:                  ; uint64_t mix64(uint64_t x)
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
```

`hash64` is the library's only public API, called from C on all three platforms. `mix64` and `hash_seed` must stay in `mix.asm` (other sources will use them later), and none of the three libraries may export them. Fix the code so that the project above builds for all three RIDs. The sources are not checked out here: write both corrected files to `Hash/hash.asm` and `Hash/mix.asm` in the current directory, and leave the project file as it is. You cannot run commands. Keep explanations short.
