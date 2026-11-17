; main.asm - freestanding Linux x86-64 program (no libc).
; Calls crc_step(CRC_SEED, 'a') from Acme.Crc, then exits with status 0.

bits 64

%include "crc.inc"              ; from the Acme.Crc package (include path comes from its build/Acme.Crc.targets)

global _start

section .text

_start:
    mov     edi, CRC_SEED       ; crc  = 0xFFFFFFFF
    mov     esi, 0x61           ; byte = 'a'
    call    crc_step            ; eax = 0x174841BC (~eax = 0xE8B7BE43 = CRC-32 of "a")

    mov     eax, 60             ; SYS_exit
    xor     edi, edi            ; status 0
    syscall

section .note.GNU-stack noalloc noexec nowrite progbits
