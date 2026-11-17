; main.asm - freestanding Linux x86-64 program (no libc).
; Calls crc_step(CRC_SEED, 0x61) from the Acme.Crc package, then exits with status 0.
default rel
bits 64

%include "crc.inc"                  ; CRC_SEED and "extern crc_step", from the package's include/ folder

SYS_EXIT_GROUP equ 231              ; Linux x86-64 system call number

section .text

; _start: the kernel jumps here with rsp 16-byte aligned (rsp -> argc, argv, ...). It never returns.
global _start:function (_start.end - _start)
_start:
    mov     edi, CRC_SEED           ; crc  = 0xFFFFFFFF
    mov     esi, 0x61               ; byte = 'a'
    call    crc_step wrt ..plt      ; a direct call once linked statically
                                    ; eax = 0x174841BC (0xE8B7BE43, the CRC-32 of "a", before the final xor)
    mov     eax, SYS_EXIT_GROUP
    xor     edi, edi                ; status 0
    syscall
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
