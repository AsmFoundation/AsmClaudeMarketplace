; Acme.Crc - bit-by-bit CRC-32 (reflected, polynomial 0xEDB88320).
;
;   uint32_t crc_step(uint32_t crc, uint32_t byte);
;
; System V AMD64 ABI: crc in edi, byte in esi (low 8 bits used), result in eax.
; Start from CRC_SEED (crc.inc) and xor the final value with 0xFFFFFFFF to get
; the standard CRC-32 of the data.

bits 64

global crc_step

section .text

crc_step:
    movzx   esi, sil            ; only the low 8 bits of 'byte' take part
    mov     eax, edi
    xor     eax, esi            ; crc ^= byte
    mov     ecx, 8
.bit:
    mov     edx, eax
    shr     eax, 1              ; crc >>= 1
    and     edx, 1              ; old low bit
    neg     edx                 ; 0 or 0xFFFFFFFF
    and     edx, 0xEDB88320
    xor     eax, edx            ; old low bit set: crc ^= polynomial
    dec     ecx
    jnz     .bit
    ret

section .note.GNU-stack noalloc noexec nowrite progbits
