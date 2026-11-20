---
type: regex
target:
  source: file
  path: Calc.Native/Calc.Native.asmproj
pattern: '<AssemblyName>\s*calc\s*</'
---

The library is named calc, which each RID turns into libcalc.so, calc.dll or libcalc.dylib (AssemblyName; 0.2.0 removed AsmLibraryName).
