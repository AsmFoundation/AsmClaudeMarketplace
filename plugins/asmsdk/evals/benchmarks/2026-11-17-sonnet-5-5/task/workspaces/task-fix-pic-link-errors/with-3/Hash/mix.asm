default rel
section .data
; Internal to libHash.so: hidden keeps it out of the exports and lets hash.asm
; read it with a plain PC-relative load. Write the visibility before the size:
; NASM silently ignores it after the size.
global hash_seed:data hidden 8
hash_seed: dq 0x9E3779B97F4A7C15
section .text
; Internal helper: hidden = not exported, and hash.asm can call it directly.
global mix64:function hidden
mix64:                  ; uint64_t mix64(uint64_t x)
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
