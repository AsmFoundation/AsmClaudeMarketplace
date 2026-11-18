---
type: regex
target:
  source: file
  path: Calc.Native/Calc.Native.asmproj
pattern: '<AssemblyName>\s*calc\s*</'
---

The output is libcalc.so (AssemblyName = calc; 0.2.0 removed AsmLibraryName).
