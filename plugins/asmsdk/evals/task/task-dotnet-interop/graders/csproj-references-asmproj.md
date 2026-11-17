---
type: regex
target:
  source: file
  path: Calc.App/Calc.App.csproj
pattern: '<ProjectReference\s+Include="[^"]*Calc\.Native\.asmproj"'
---

The app references the asm project, which copies libcalc.so next to it.
