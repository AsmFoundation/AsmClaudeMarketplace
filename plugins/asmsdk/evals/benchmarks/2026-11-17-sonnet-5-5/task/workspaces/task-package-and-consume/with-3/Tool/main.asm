; main.asm - freestanding Linux x86-64 program (no libc): crc_step(CRC_SEED, 'a'), then exit(0).
default rel
bits 64

%include "crc.inc"                  ; from the Acme.Crc package: CRC_SEED, extern crc_step

section .text

global _start:function
_start:                             ; rsp is 16-byte aligned here, as a call site requires
    mov     edi, CRC_SEED           ; crc
    mov     esi, 0x61               ; byte 'a'
    call    crc_step wrt ..plt      ; from libcrc.a; a direct call once linked statically

    mov     eax, 231                ; exit_group
    xor     edi, edi                ; status 0
    syscall

section .note.GNU-stack noalloc noexec nowrite progbits
