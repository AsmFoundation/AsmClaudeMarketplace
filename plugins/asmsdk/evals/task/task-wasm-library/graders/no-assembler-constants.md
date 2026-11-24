---
type: regex
target:
  source: file
  path: Sum/sum.wasm.s
pattern: '(^|\n)\s*(\.(set|equ|equiv)\b|[A-Za-z_.$][\w.$]*\s*=[^=])'
match: not_contains
---

No assembler constant at the start of a line (a comment that mentions .set is fine): llvm-mc's WebAssembly writer stops on any constant symbol, even a .L one ("absolute addressing not supported!", ASM0019).
