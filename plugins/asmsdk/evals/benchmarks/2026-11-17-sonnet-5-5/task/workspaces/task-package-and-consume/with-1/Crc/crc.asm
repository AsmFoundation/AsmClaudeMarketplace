; crc.asm - bit-by-bit CRC-32 step (IEEE 802.3, reflected, polynomial 0xEDB88320).
; The public declaration lives in include/crc.inc.
default rel                         ; position-independent: links into a static program, a PIE or a .so
bits 64

CRC_POLY equ 0xEDB88320

section .text

; uint32_t crc_step(uint32_t crc, uint32_t byte)      System V ABI: crc in edi, byte in esi
; Example: crc_step(0xFFFFFFFF, 0x61) == 0x174841BC (the CRC-32 of "a" before the final xor).
global crc_step:function (crc_step.end - crc_step)
crc_step:
    movzx   eax, sil                ; only the low 8 bits of byte take part
    xor     eax, edi                ; crc ^= byte
    mov     ecx, 8                  ; eight bits per byte
.bit:
    mov     edx, eax
    and     edx, 1                  ; edx = lowest bit of crc
    neg     edx                     ; 0 or 0xFFFFFFFF
    and     edx, CRC_POLY           ; 0 or the polynomial
    shr     eax, 1                  ; crc >>= 1
    xor     eax, edx                ; ... ^ polynomial when the shifted-out bit was 1
    dec     ecx
    jnz     .bit
    ret                             ; result in eax
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
