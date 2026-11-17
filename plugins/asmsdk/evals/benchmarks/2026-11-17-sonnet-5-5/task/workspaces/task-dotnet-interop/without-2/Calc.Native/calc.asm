; calc.asm - NASM syntax, x86-64, System V AMD64 ABI, ELF64.
;
;   int64_t calc_sum(const int64_t *values, int64_t count);
;
; Arguments: rdi = values, rsi = count.  Result: rax.
; Returns 0 when count <= 0.  Overflow wraps (two's complement).

bits 64
default rel

section .text

global calc_sum:function
calc_sum:
    xor     eax, eax            ; sum = 0
    test    rsi, rsi
    jle     .done               ; count <= 0 -> return 0
.next:
    add     rax, [rdi]          ; sum += *values
    add     rdi, 8              ; values++
    dec     rsi                 ; count--
    jnz     .next
.done:
    ret

; Mark the stack as non-executable (avoids linker warnings).
section .note.GNU-stack noalloc noexec nowrite progbits
