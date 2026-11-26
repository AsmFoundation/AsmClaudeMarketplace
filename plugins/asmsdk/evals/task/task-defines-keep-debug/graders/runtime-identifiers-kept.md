---
type: regex
target:
  source: file
  path: Fast/Fast.asmproj
pattern: '<RuntimeIdentifiers>\s*linux-x64;win-x64\s*</RuntimeIdentifiers>'
---

The runtime identifiers are unchanged: a project without them builds the build machine's RID only (0.4.0's default).
