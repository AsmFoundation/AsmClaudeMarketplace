---
type: regex
target:
  source: file
  path: Calc.App/Calc.App.csproj
pattern: '<ProjectReference\s+Include="[^"]*Calc\.Native\.asmproj"'
---

The app references the asm project, which puts each RID's library in the app's output (runtimes/<rid>/native/ for a portable app, where the .NET host picks the one for the machine).
