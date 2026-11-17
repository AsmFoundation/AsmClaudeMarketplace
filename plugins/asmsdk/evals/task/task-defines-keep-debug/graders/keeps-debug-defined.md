---
type: regex
target:
  source: file
  path: Fast/Fast.asmproj
pattern: '<AsmDefine\s+Include="USE_AVX2(=1)?"|<AsmDefineConstants[^>]*>[^<]*\bDEBUG\b'
---

DEBUG survives: an AsmDefine item, or an AsmDefineConstants value that names DEBUG itself (the SDK applies its DEBUG default only when the property is empty, after the project body).
