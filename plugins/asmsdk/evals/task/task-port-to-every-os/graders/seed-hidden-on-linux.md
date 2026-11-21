---
type: regex
target:
  source: file
  path: Hash/mix.asm
pattern: 'hash_seed\s*:\s*((data|object)\s+)?(hidden|internal)\b'
---

hash_seed is hidden on Linux, with the visibility before the size (data hidden 8; 'data 8 hidden' is silently not hidden). Win64's and macho64's NASM reject both the type and the visibility, so this line needs a Linux guard.
