---
type: regex
target:
  source: file
  path: Hash/mix.asm
pattern: 'global\s+hash_seed\s*:\s*data\s+hidden\b|global\s+hash_seed\s*:\s*hidden\b'
---

hash_seed is hidden, with the visibility before the size (data hidden 8; 'data 8 hidden' is silently not hidden).
