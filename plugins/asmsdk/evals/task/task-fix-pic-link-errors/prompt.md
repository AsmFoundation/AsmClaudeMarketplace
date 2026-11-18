---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-fix-pic-link-errors]
---

`dotnet build` of our shared library project `Hash/Hash.asmproj` (AsmFoundation.Sdk 0.2.0, default settings, builds libHash.so) fails at link time:

```
lld : error : relocation R_X86_64_PC32 cannot be used against symbol 'mix64'; recompile with -fPIC
lld : error : relocation R_X86_64_PC32 cannot be used against symbol 'hash_seed'; recompile with -fPIC
```

The two sources are `Hash/hash.asm`:

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

Only `hash64` is meant to be the library's public API. Fix the code. The sources are not checked out here: write both corrected files to `Hash/hash.asm` and `Hash/mix.asm` in the current directory. You cannot run commands. Keep explanations short.
