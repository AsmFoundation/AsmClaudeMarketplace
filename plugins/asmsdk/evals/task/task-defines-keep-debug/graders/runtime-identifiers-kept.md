---
type: regex
target:
  source: file
  path: Fast/Fast.asmproj
pattern: '<RuntimeIdentifiers>\s*linux-x64;win-x64\s*</RuntimeIdentifiers>'
---

The runtime identifiers are unchanged: 0.3.0 has no default, and a project without them stops with ASM0010.
