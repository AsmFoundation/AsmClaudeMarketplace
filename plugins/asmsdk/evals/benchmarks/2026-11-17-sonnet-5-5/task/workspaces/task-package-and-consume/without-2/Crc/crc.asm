; crc.asm - bit-by-bit CRC-32 step (IEEE 802.3, reflected, polynomial 0xEDB88320)
;
;   uint32_t crc_step(uint32_t crc, uint32_t byte);
;
; System V AMD64 ABI: crc in edi, byte in esi (only the low 8 bits are used),
; result in eax. Clobbers ecx and esi (both caller-saved).
; Start from CRC_SEED and XOR the final value with 0xFFFFFFFF for the standard CRC-32.
;
; crc.inc is for callers; it is not included here because it declares crc_step extern.

bits 64

global crc_step

section .text

crc_step:
    mov     eax, edi            ; eax = crc
    movzx   esi, sil            ; byte &= 0xFF
    xor     eax, esi            ; crc ^= byte
    mov     ecx, 8              ; 8 bits per byte
.bit:
    shr     eax, 1              ; CF = bit shifted out
    jnc     .next
    xor     eax, 0xEDB88320     ; reflected polynomial
.next:
    dec     ecx
    jnz     .bit
    ret

section .note.GNU-stack noalloc noexec nowrite progbits
