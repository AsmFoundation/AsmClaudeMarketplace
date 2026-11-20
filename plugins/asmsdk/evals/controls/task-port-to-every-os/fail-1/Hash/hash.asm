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
