; crc.inc - public interface of Acme.Crc (CRC-32, reflected, polynomial 0xEDB88320).
; Packed as include/crc.inc; consumers get it on their include path and write: %include "crc.inc"
%ifndef ACME_CRC_INC
%define ACME_CRC_INC

CRC_SEED equ 0xFFFFFFFF             ; initial value of the running CRC

; uint32_t crc_step(uint32_t crc, uint32_t byte)
;   crc  (edi): running CRC, start with CRC_SEED
;   byte (esi): next input byte, only the low 8 bits are used
;   returns (eax): the updated CRC. Apply the final "xor 0xFFFFFFFF" yourself.
extern crc_step

%endif
