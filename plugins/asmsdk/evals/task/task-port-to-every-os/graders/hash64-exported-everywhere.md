---
type: regex
target:
  source: file
  path: Hash/hash.asm
pattern: 'FUNCTION\s+hash64\b|-export:\s*hash64\b'
---

hash64 is exported on every OS, Windows included: a DLL exports only what a directive or an ExportsFile names, and the project file stays as given, so the source carries the directive (asmsdk.inc's FUNCTION, or a .drectve section with -export:hash64). A plain global builds and exports nothing from Hash.dll.
