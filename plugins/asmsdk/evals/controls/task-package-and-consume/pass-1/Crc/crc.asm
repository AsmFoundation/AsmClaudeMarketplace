; uint32_t crc_step(uint32_t crc, uint32_t byte): one byte of CRC-32, bit by bit.
%include "asmsdk.inc"
default rel

section .text
FUNCTION crc_step, 2
    mov     eax, ARG1d
    movzx   r9d, ARG2b
    xor     eax, r9d
    mov     r8d, 8
.bit:
    shr     eax, 1
    jnc     .next
    xor     eax, 0xEDB88320
.next:
    dec     r8d
    jnz     .bit
    RETURN
ENDFUNCTION

%ifdef LINUX
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
