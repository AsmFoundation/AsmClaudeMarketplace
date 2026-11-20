; crc.inc - Acme.Crc's public API.
%ifndef ACME_CRC_INC
%define ACME_CRC_INC

; uint32_t crc_step(uint32_t crc, uint32_t byte): one byte of CRC-32 (reflected, 0xEDB88320).
extern crc_step

CRC_SEED equ 0xFFFFFFFF

%endif
