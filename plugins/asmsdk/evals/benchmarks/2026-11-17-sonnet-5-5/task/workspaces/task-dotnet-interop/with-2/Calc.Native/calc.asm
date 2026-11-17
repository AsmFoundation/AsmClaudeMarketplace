; calc.asm - int64_t calc_sum(const int64_t *values, int64_t count)
;
; Adds up `count` signed 64-bit integers that start at `values`.
; Returns 0 when count <= 0, without reading the array. The sum wraps on overflow.
;
; System V AMD64 ABI: rdi = values, rsi = count, result in rax.
; Leaf function: no stack use; it clobbers only rax, rdi, rsi and the flags.

default rel
bits 64

section .text

global calc_sum:function (calc_sum.end - calc_sum)
calc_sum:
    xor     eax, eax                ; sum = 0
    test    rsi, rsi
    jle     .done                   ; count <= 0 (signed): nothing to add
.loop:
    add     rax, [rdi]              ; sum += *values
    add     rdi, 8                  ; values++
    dec     rsi                     ; count--
    jnz     .loop
.done:
    ret
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
