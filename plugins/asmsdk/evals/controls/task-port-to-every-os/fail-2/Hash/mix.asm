; Negative control: hidden on Linux only; macOS exports mix64 and hash_seed.
default rel
section .data
%ifdef LINUX
global hash_seed:data hidden 8
%else
global hash_seed
%endif
hash_seed: dq 0x9E3779B97F4A7C15
section .text
%ifdef LINUX
global mix64:function hidden
%else
global mix64
%endif
mix64:
    mov rax, rdi
    shr rax, 33
    xor rax, rdi
    ret
%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
