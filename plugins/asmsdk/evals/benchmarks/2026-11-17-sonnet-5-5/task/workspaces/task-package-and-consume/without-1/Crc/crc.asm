; crc.asm - Acme.Crc: one bit-by-bit CRC-32 step (reflected, polynomial 0xEDB88320).
;
;   uint32_t crc_step(uint32_t crc, uint32_t byte);
;
; System V AMD64 ABI: crc in EDI, byte in ESI (low 8 bits used), result in EAX.
; Clobbers EAX, ECX, EDX only. The caller supplies the start value (CRC_SEED in
; crc.inc) and does the final inversion, so calls can be chained over a buffer.

bits 64

global crc_step

section .text

crc_step:
    movzx   edx, sil            ; edx = byte & 0xFF
    mov     eax, edi            ; eax = crc
    xor     eax, edx            ; crc ^= byte
    mov     ecx, 8              ; 8 bits per byte
.bit:
    shr     eax, 1              ; CF = bit shifted out
    jnc     .next
    xor     eax, 0xEDB88320     ; reflected CRC-32 polynomial
.next:
    dec     ecx
    jnz     .bit
    ret

%ifidn __OUTPUT_FORMAT__, elf64
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
