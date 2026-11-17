---
type: regex
target:
  source: file
  path: Calc.slnx
pattern: 'Calc\.Native\.asmproj[^>]*13B669BE-BB05-4DDF-9536-439F39A36129|13B669BE-BB05-4DDF-9536-439F39A36129[^>]*Calc\.Native\.asmproj'
flags: i
---

The .slnx entry for the .asmproj carries the generic MSBuild type GUID (MSB4025 without it).
