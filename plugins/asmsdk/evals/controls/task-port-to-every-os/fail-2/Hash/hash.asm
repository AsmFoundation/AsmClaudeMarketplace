; Negative control: builds for every RID, but a plain global is no DLL export.
default rel
extern mix64, hash_seed
section .text
%ifdef LINUX
global hash64:function
%else
global hash64
%endif
hash64:
    mov rax, [rel hash_seed]
    xor rdi, rax
    call mix64
    ret
%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
