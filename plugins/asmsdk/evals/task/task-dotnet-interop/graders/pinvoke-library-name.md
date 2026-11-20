---
type: regex
target:
  source: file
  path: Calc.App/Program.cs
pattern: '(LibraryImport|DllImport)\s*\(\s*"calc"|const\s+string\s+\w+\s*=\s*"calc"\s*;'
---

P/Invoke names the library calc, which .NET probes as calc.dll on Windows and as libcalc.so and libcalc.dylib elsewhere. "libcalc" works on Linux and macOS and fails on Windows with DllNotFoundException (measured with this suite's negative control).
