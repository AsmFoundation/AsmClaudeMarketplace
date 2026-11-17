; crc.inc - public include file of the Acme.Crc package.
;
;   uint32_t crc_step(uint32_t crc, uint32_t byte);
;
; System V AMD64 calling convention: crc in EDI, byte in ESI (only the low
; 8 bits are used), new crc returned in EAX. Reflected CRC-32, polynomial
; 0xEDB88320. Start from CRC_SEED and XOR the final value with 0xFFFFFFFF to
; get the standard CRC-32 of the data.

%ifndef ACME_CRC_INC
%define ACME_CRC_INC

CRC_SEED equ 0xFFFFFFFF

extern crc_step

%endif
