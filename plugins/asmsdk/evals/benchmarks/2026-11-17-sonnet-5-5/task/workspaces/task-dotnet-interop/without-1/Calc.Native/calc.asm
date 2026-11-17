; calc.asm - NASM, x86-64, System V AMD64 ABI (ELF64 shared object)
;
;   int64_t calc_sum(const int64_t *values, int64_t count);
;
; in : rdi = values, rsi = count
; out: rax = values[0] + ... + values[count - 1]  (0 when count <= 0)
; rdi and rsi are caller-saved, so no registers need to be preserved.

bits 64

global calc_sum:function

section .text

calc_sum:
        xor     eax, eax                ; sum = 0
        test    rsi, rsi
        jle     .done                   ; count <= 0 -> return 0
.next:
        add     rax, [rdi]              ; sum += *values
        add     rdi, 8                  ; values++
        dec     rsi
        jnz     .next
.done:
        ret

; Mark the stack as non-executable (avoids linker warnings).
section .note.GNU-stack noalloc noexec nowrite progbits
