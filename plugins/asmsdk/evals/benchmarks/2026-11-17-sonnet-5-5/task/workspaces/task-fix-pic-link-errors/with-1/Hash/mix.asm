default rel
; hash_seed and mix64 are internal to libHash: "hidden" keeps them out of the
; export table and lets hash.asm reference them directly (no PLT/GOT).
; Keep "hidden" before any size: NASM silently ignores it after the size.
section .data
global hash_seed:data hidden 8
hash_seed: dq 0x9E3779B97F4A7C15
section .text
global mix64:function hidden
mix64:                  ; uint64_t mix64(uint64_t x)
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
