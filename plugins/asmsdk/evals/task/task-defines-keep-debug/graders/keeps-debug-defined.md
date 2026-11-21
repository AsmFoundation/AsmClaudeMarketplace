---
type: regex
target:
  source: file
  path: Fast/Fast.asmproj
pattern: '<DefineConstants[^>]*>[^<]*\bUSE_AVX2(=1)?\b'
---

The symbol is added through DefineConstants: after the project body the SDK appends DEBUG or RELEASE, FREESTANDING or LIBC, the OS (LINUX or WINDOWS here) and the CPU (X64), so Debug keeps DEBUG. build_check.py builds both configurations for both RIDs to prove it.
