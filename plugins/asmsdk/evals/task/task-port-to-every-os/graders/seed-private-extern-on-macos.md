---
type: regex
target:
  source: file
  path: Hash/mix.asm
pattern: 'hash_seed\s*:\s*private_extern\b'
---

hash_seed is private_extern on macOS: no asmsdk.inc macro covers data, and a plain global is exported by libHash.dylib.
