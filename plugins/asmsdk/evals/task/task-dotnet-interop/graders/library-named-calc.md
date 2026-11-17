---
type: regex
target:
  source: file
  path: Calc.Native/Calc.Native.asmproj
pattern: '<(AsmLibraryName|AssemblyName)>\s*calc\s*</'
---

The output is libcalc.so (AsmLibraryName or AssemblyName = calc).
