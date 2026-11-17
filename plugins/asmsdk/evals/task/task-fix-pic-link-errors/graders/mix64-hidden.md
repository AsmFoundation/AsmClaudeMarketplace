---
type: regex
target:
  source: file
  path: Hash/mix.asm
pattern: 'global\s+mix64\s*:\s*function\s+hidden\b'
---

mix64 is hidden (visibility before any size): not exported, and a direct call links.
