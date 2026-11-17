; int64_t calc_sum(const int64_t *values, int64_t count)
;
; Returns values[0] + ... + values[count - 1], or 0 when count <= 0.
; System V AMD64 ABI: rdi = values, rsi = count, result in rax.

bits 64

global calc_sum:function

section .text

calc_sum:
        xor     eax, eax                ; sum = 0
        test    rsi, rsi
        jle     .done                   ; count <= 0 -> return 0

.loop:
        add     rax, [rdi]              ; sum += *values
        add     rdi, 8                  ; values++
        dec     rsi                     ; count--
        jnz     .loop

.done:
        ret

; Mark the stack as non-executable. Without this, the linker may flag libcalc.so as
; needing an executable stack, which newer glibc versions refuse to dlopen.
section .note.GNU-stack noalloc noexec nowrite progbits
