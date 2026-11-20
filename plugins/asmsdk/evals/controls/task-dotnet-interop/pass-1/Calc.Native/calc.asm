; int64_t calc_sum(const int64_t *values, int64_t count)
%include "asmsdk.inc"
default rel

section .text
FUNCTION calc_sum, 2            ; exported on every OS, the DLL included
    xor     eax, eax
    test    ARG2, ARG2          ; rsi on Linux and macOS, rdx on Windows
    jle     .done
.next:
    add     rax, [ARG1]         ; rdi / rcx
    add     ARG1, 8
    dec     ARG2
    jnz     .next
.done:
    RETURN
ENDFUNCTION

%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
