; A freestanding Linux program: crc_step(CRC_SEED, 'a'), then exit(0).
%include "crc.inc"
default rel

section .text
global _start
_start:
    mov     edi, CRC_SEED
    mov     esi, 0x61
    call    crc_step            ; rsp is 16-aligned at _start, so the callee sees 16n+8
    mov     eax, 231            ; exit_group
    xor     edi, edi
    syscall

section .note.GNU-stack noalloc noexec nowrite progbits
