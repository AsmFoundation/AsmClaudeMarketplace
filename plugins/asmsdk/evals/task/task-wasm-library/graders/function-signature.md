---
type: regex
target:
  source: file
  path: Sum/sum.wasm.s
pattern: 'FUNCTION\s+sum_i32\s*,\s*\(\s*i32\s*,\s*i32\s*\)\s*->\s*\(\s*i32\s*\)'
---

asmsdk-wasm.inc's FUNCTION takes the wasm type: a pointer and an int32_t are both i32 on wasm32, and so is the result.
