---
type: regex
target:
  source: file
  path: Calc.Native/calc.asm
pattern: '\bARG[12]|\bWINDOWS\b|\bwin64\b'
---

calc_sum reads its arguments where each OS passes them, rcx and rdx on Windows and rdi and rsi elsewhere: asmsdk.inc's ARG1 and ARG2, or a WINDOWS (or win64 output format) guard. The prompt allows a single source, so a source per OS is no way out.
