; crc.inc - public interface of Acme.Crc.
; Lives in include/, the only folder the package ships and consumers get on their include path.
%ifndef ACME_CRC_INC
%define ACME_CRC_INC

CRC_SEED equ 0xFFFFFFFF         ; initial value of the running CRC

; uint32_t crc_step(uint32_t crc, uint32_t byte)
;   System V AMD64 ABI: crc in edi, byte in esi (only its low 8 bits are used), result in eax.
;   One reflected CRC-32 step (polynomial 0xEDB88320). Start from CRC_SEED, feed every byte,
;   then xor the last result with 0xFFFFFFFF to get the standard CRC-32.
extern crc_step

%endif
