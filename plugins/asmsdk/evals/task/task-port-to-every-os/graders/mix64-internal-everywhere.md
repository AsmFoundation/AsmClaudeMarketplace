---
type: regex
target:
  source: file
  path: Hash/mix.asm
pattern: 'HIDDEN_FUNCTION\s+mix64\b|mix64\s*:\s*private_extern\b'
---

mix64 stays global inside the library and is exported by none of the three: asmsdk.inc's HIDDEN_FUNCTION, or by hand private_extern on macOS (whose NASM rejects hidden) besides hidden on Linux. Without either, libHash.dylib exports mix64.
