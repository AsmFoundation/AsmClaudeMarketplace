; Negative control: Linux-minded. Builds for every RID, but calc.dll exports nothing
; (a plain global is no DLL export) and Windows would pass the arguments in rcx/rdx.
default rel
section .text
global calc_sum
calc_sum:
    xor rax, rax
    test rsi, rsi
    jle .done
.next:
    add rax, [rdi]
    add rdi, 8
    dec rsi
    jnz .next
.done:
    ret
%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
