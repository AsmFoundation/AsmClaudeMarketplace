default rel

; mix64 and hash_seed are `hidden` in mix.asm: they are internal to
; libHash.so, so direct PC-relative references to them are fine here.
extern mix64, hash_seed

section .text
; hash64 is the library's only public (exported) symbol.
global hash64:function
hash64:                 ; uint64_t hash64(uint64_t x)
    mov rax, [rel hash_seed]
    xor rdi, rax
    call mix64
    ret

section .note.GNU-stack noalloc noexec nowrite progbits
