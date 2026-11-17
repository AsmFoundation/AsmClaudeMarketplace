default rel

; mix64 and hash_seed are defined `hidden` in mix.asm (internal to libHash.so),
; so the references below bind locally: no GOT/PLT needed.
extern mix64, hash_seed

section .text
global hash64:function  ; the library's only exported symbol
hash64:                 ; uint64_t hash64(uint64_t x)
    mov rax, [rel hash_seed]
    xor rdi, rax
    jmp mix64           ; tail call: a `call` here would enter mix64 with rsp misaligned by 8
section .note.GNU-stack noalloc noexec nowrite progbits
