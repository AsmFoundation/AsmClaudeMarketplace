---
type: regex
target:
  source: file
  path: Hash/hash.asm
pattern: '\bARG1|\bWINDOWS\b|\bwin64\b'
---

hash64 reads its argument where each OS passes it, rcx on Windows and rdi elsewhere: asmsdk.inc's ARG1, or a WINDOWS (or win64 output format) guard. The original reads and changes rdi on every OS; on Windows rdi is no argument but a register the caller expects back unchanged.
