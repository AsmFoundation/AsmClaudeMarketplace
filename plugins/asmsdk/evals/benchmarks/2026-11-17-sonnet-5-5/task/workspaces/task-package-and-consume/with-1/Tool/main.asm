; main.asm - freestanding Linux x86-64 program (no libc).
; Calls crc_step from the Acme.Crc package, then exits with status 0.
default rel
bits 64

%include "crc.inc"                  ; from the Acme.Crc package: CRC_SEED and extern crc_step

SYS_EXIT_GROUP equ 231

section .text

global _start:function (_start.end - _start)
_start:
    ; The kernel enters _start with rsp 16-byte aligned and no return address on the stack,
    ; so the call below already meets the System V alignment rule. Never ret from _start.
    mov     edi, CRC_SEED           ; uint32_t crc  = CRC_SEED
    mov     esi, 0x61               ; uint32_t byte = 'a'
    call    crc_step wrt ..plt      ; eax = 0x174841BC; a direct call once linked statically

    mov     eax, SYS_EXIT_GROUP
    xor     edi, edi                ; exit status 0
    syscall
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
