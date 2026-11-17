; main.asm - freestanding Linux x86-64 program (no libc, no C runtime).
; Calls crc_step(CRC_SEED, 0x61) from the Acme.Crc package, then exits with status 0.

bits 64

%include "crc.inc"              ; from the Acme.Crc package: CRC_SEED, extern crc_step

global _start

section .text

_start:
    mov     edi, CRC_SEED       ; arg 1: crc   (System V AMD64: EDI, ESI)
    mov     esi, 0x61           ; arg 2: byte 'a'
    call    crc_step            ; EAX = 0x174841BC (CRC-32 of "a" before the final inversion)

    xor     edi, edi            ; exit status 0
    mov     eax, 60             ; SYS_exit
    syscall

section .note.GNU-stack noalloc noexec nowrite progbits
