; mix.asm - the library's internals: global inside the library, exported by no image.
%include "asmsdk.inc"
default rel

section .data
; No macro covers data: hidden on ELF, private_extern on Mach-O (whose NASM
; rejects hidden), and a plain global on Windows, where a DLL exports only
; what it is told to.
%ifdef LINUX
global hash_seed:data hidden 8
%elifdef MACOS
global hash_seed:private_extern
%else
global hash_seed
%endif
hash_seed: dq 0x9E3779B97F4A7C15

section .text
; uint64_t mix64(uint64_t x): HIDDEN_FUNCTION = global, hidden / private_extern,
; no export directive.
HIDDEN_FUNCTION mix64, 1
    mov     rax, ARG1
    shr     rax, 33
    xor     rax, ARG1
    RETURN
ENDFUNCTION

%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
