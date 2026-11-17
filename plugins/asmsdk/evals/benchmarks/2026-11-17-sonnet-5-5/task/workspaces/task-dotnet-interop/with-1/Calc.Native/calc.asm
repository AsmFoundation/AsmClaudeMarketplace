; calc.asm - libcalc.so, x86-64 System V ABI, NASM syntax.
default rel
bits 64

section .text

; int64_t calc_sum(const int64_t *values, int64_t count)
;   rdi = values, rsi = count; returns the sum in rax (wraps on overflow).
;   A count <= 0 returns 0 without reading memory.
global calc_sum:function (calc_sum.end - calc_sum)
calc_sum:
    xor     eax, eax                ; sum = 0
    test    rsi, rsi
    jle     .done                   ; count <= 0: nothing to add
.loop:
    add     rax, [rdi]              ; sum += *values
    add     rdi, 8                  ; values++
    dec     rsi                     ; count--
    jnz     .loop
.done:
    ret
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
