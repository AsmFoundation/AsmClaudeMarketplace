; crc.asm - Acme.Crc: one step of a bit-by-bit CRC-32 (reflected, polynomial 0xEDB88320).
; The public contract is include/crc.inc.
default rel                         ; RIP-relative addressing: the code is position-independent
bits 64

%include "crc.inc"                  ; CRC_SEED and "extern crc_step" (found through -I include/)

CRC_POLY equ 0xEDB88320             ; reflected CRC-32 (IEEE 802.3) polynomial

section .text

; uint32_t crc_step(uint32_t crc, uint32_t byte)
;   System V AMD64: crc = edi, byte = esi, result = eax. Clobbers only eax, ecx, edx.
global crc_step:function (crc_step.end - crc_step)
crc_step:
    movzx   eax, sil                ; only the low 8 bits of "byte" count
    xor     eax, edi                ; crc ^= byte
    mov     ecx, 8                  ; 8 bits per byte
.bit:
    mov     edx, eax
    shr     eax, 1                  ; crc >>= 1
    and     edx, 1                  ; the bit that was shifted out ...
    neg     edx                     ; ... as a mask: 0 or 0xFFFFFFFF
    and     edx, CRC_POLY
    xor     eax, edx                ; crc ^= polynomial, if that bit was set
    dec     ecx
    jnz     .bit
    ret
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
