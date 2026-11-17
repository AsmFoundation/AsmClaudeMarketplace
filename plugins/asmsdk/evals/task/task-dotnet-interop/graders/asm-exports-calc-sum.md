---
type: regex
target:
  source: file
  path: Calc.Native/calc.asm
pattern: 'global\s+\$?calc_sum\b'
---

calc.asm exports calc_sum.
