; Acme.Crc public interface.

%ifndef ACME_CRC_INC
%define ACME_CRC_INC

CRC_SEED equ 0xFFFFFFFF

; uint32_t crc_step(uint32_t crc, uint32_t byte)
; System V AMD64 ABI: edi = running CRC, esi = next byte (low 8 bits), eax = new CRC.
extern crc_step

%endif
