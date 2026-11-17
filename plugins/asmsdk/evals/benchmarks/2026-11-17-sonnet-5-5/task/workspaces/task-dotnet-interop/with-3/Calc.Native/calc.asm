; calc.asm - x86-64 System V ABI, NASM syntax.
;
; int64_t calc_sum(const int64_t *values, int64_t count)
;
;   rdi = values   pointer to `count` consecutive 64-bit integers
;   rsi = count    number of elements; zero or negative means nothing to add
;   rax = result   the sum (wraps modulo 2^64 on overflow)
;
; Freestanding and position-independent: no libc, no relocations.

default rel
bits 64

section .text

global calc_sum:function (calc_sum.end - calc_sum)
calc_sum:
    xor     eax, eax                ; sum = 0
    test    rsi, rsi
    jle     .done                   ; count <= 0 (signed): return 0
.loop:
    add     rax, [rdi]              ; sum += *values
    add     rdi, 8                  ; values++
    dec     rsi                     ; count--
    jnz     .loop
.done:
    ret
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
