; crc.inc - public interface of the Acme.Crc package (bit-by-bit CRC-32).
;
; This file lives in include/ on purpose: dotnet pack ships only that folder, and the package's
; generated props then put it on the NASM include path of every asm project that references
; Acme.Crc. Consumers simply write:  %include "crc.inc"
%ifndef ACME_CRC_INC
%define ACME_CRC_INC

CRC_SEED equ 0xFFFFFFFF             ; initial value of a running CRC

; uint32_t crc_step(uint32_t crc, uint32_t byte)      System V AMD64: crc = edi, byte = esi, result = eax
;   Folds the low 8 bits of "byte" into "crc" (reflected CRC-32, polynomial 0xEDB88320).
;   Start from CRC_SEED and xor the final value with 0xFFFFFFFF to get the standard CRC-32.
extern crc_step

%endif
