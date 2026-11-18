---
type: regex
target:
  source: file
  path: Fast/Fast.asmproj
pattern: '<DefineConstants[^>]*>[^<]*\bUSE_AVX2(=1)?\b'
---

The symbol is added through DefineConstants, 0.2.0's property: the SDK appends DEBUG or RELEASE (and FREESTANDING or LIBC) after the project body, so Debug keeps DEBUG. build_check.py builds both configurations to prove it.
