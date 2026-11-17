---
type: regex
target:
  source: file
  path: Crc/Crc.asmproj
pattern: '<OutputType>\s*StaticLibrary\s*</|<AsmProduceStaticLibrary>\s*true\s*<'
---

The library produces a .a, which a freestanding (static) executable can link.
