; crc.asm - Acme.Crc: one bit-by-bit CRC-32 step.
;
; uint32_t crc_step(uint32_t crc, uint32_t byte)
;   System V AMD64 ABI: crc in edi, byte in esi (only its low 8 bits are used), result in eax.
;   Reflected CRC-32, polynomial 0xEDB88320 (zlib, PNG, Ethernet).
;
; Check: crc_step(0xFFFFFFFF, 0x61) = 0x174841BC, and 0x174841BC ^ 0xFFFFFFFF = 0xE8B7BE43,
; the standard CRC-32 of "a".
;
; The public contract is include/crc.inc (extern crc_step, CRC_SEED); nothing here needs it.
default rel
bits 64

CRC32_POLY equ 0xEDB88320

section .text

global crc_step:function (crc_step.end - crc_step)
crc_step:
    movzx   eax, sil            ; eax = byte & 0xFF
    xor     eax, edi            ; crc ^= byte
    mov     ecx, 8              ; one pass per bit
.bit:
    shr     eax, 1              ; CF = the bit shifted out
    jnc     .next
    xor     eax, CRC32_POLY     ; it was 1: fold in the polynomial
.next:
    dec     ecx
    jnz     .bit
    ret
.end:

section .note.GNU-stack noalloc noexec nowrite progbits
