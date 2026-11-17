default rel
section .data
; Internal to libHash: hidden = not exported, bound locally at link time.
global hash_seed:data hidden 8
hash_seed: dq 0x9E3779B97F4A7C15
section .text
; Internal to libHash: hidden = not exported, bound locally at link time.
global mix64:function hidden
mix64:                  ; uint64_t mix64(uint64_t x)
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
