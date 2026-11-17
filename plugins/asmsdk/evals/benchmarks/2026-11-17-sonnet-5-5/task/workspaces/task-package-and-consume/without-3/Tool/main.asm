; Tool - freestanding Linux x86-64 executable (no libc): calls crc_step, exits 0.

bits 64

%include "crc.inc"              ; CRC_SEED and extern crc_step, from the Acme.Crc package

global _start

section .text

_start:
    mov     edi, CRC_SEED       ; crc  = CRC_SEED
    mov     esi, 0x61           ; byte = 'a'
    call    crc_step            ; eax = 0x174841BC (CRC-32 of "a" before the final xor)

    mov     eax, 60             ; SYS_exit
    xor     edi, edi            ; status 0
    syscall

section .note.GNU-stack noalloc noexec nowrite progbits
