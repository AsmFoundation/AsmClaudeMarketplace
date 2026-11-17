default rel

; Internal helpers of libHash.so, not public API. They are `hidden`, so they
; stay out of the dynamic symbol table and cannot be preempted. That makes the
; direct PC-relative references from hash.asm legal in a shared library
; (lld rejects R_X86_64_PC32 against preemptible symbols).

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
