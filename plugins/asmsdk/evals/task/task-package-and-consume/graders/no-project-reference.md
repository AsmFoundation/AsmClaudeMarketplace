---
type: regex
target:
  source: file
  path: Tool/Tool.asmproj
pattern: 'ProjectReference'
match: not_contains
---

Tool does not use a ProjectReference.
