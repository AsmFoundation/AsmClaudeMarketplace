---
type: regex
target:
  source: file
  path: Calc.Native/calc.asm
pattern: 'FUNCTION\s+calc_sum\b|global\s+\$?_?calc_sum\b'
---

calc.asm defines calc_sum as a global symbol (asmsdk.inc's FUNCTION, or a global by hand). Whether each RID's library really exports it, the DLL included, is build_check.py's to judge.
