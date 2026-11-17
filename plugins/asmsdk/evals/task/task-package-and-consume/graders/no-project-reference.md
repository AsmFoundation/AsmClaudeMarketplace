---
type: regex
target:
  source: file
  path: Tool/Tool.asmproj
pattern: '<ProjectReference'
match: not_contains
---

Tool has no <ProjectReference> element (the word in a comment is fine).
