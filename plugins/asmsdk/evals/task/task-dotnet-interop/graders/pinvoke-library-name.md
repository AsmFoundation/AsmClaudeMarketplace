---
type: regex
target:
  source: file
  path: Calc.App/Program.cs
pattern: '(LibraryImport|DllImport)\s*\(\s*"(lib)?calc(\.so)?"'
---

P/Invoke names the library so that Linux probes libcalc.so.
