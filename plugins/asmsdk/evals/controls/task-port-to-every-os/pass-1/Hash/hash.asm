; hash.asm - the library's public API: uint64_t hash64(uint64_t x), on every OS.
%include "asmsdk.inc"
default rel

extern mix64, hash_seed         ; mix.asm: global in the library, exported by none

section .text
; FUNCTION exports hash64 everywhere: global:function on ELF, global on Mach-O
; (the SDK adds the underscore), and a -export directive for the Windows DLL.
FUNCTION hash64, 1
    sub     rsp, SHADOW_SPACE + 8   ; align rsp to 16 for the call; Windows' callee owns 32 bytes above it
    mov     rax, [rel hash_seed]
    xor     ARG1, rax               ; rdi on Linux and macOS, rcx on Windows
    call    mix64                   ; takes its argument in ARG1 too
    add     rsp, SHADOW_SPACE + 8
    RETURN
ENDFUNCTION

%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
