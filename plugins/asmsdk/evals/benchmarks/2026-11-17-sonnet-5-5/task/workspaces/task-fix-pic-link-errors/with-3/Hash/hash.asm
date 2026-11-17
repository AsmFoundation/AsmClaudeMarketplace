default rel
; mix64 and hash_seed are hidden in mix.asm, so plain PC-relative access links
; (no PLT or GOT needed) and only hash64 is exported.
extern mix64, hash_seed
section .text
global hash64:function
hash64:                 ; uint64_t hash64(uint64_t x)
    mov rax, [rel hash_seed]
    xor rdi, rax
    jmp mix64           ; tail call: a call here would enter mix64 with rsp misaligned
section .note.GNU-stack noalloc noexec nowrite progbits
