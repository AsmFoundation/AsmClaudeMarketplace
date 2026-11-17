; crc.inc - public interface of Acme.Crc (bit-by-bit CRC-32, reflected, polynomial 0xEDB88320)

%ifndef CRC_INC
%define CRC_INC

; Initial CRC value. XOR the final value with 0xFFFFFFFF to get the standard CRC-32.
CRC_SEED equ 0xFFFFFFFF

; uint32_t crc_step(uint32_t crc, uint32_t byte)
;   System V AMD64 ABI: crc in edi, byte in esi (low 8 bits used); result in eax.
extern crc_step

%endif
