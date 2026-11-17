default rel
section .data
; "hidden" = internal to libHash.so: not exported, and hash.asm can reference it
; directly (no PLT/GOT). Visibility must come BEFORE the size: NASM silently
; ignores it in "data 8 hidden".
global hash_seed:data hidden 8
hash_seed: dq 0x9E3779B97F4A7C15
section .text
global mix64:function hidden    ; internal helper, not part of the public API
mix64:                  ; uint64_t mix64(uint64_t x)
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
