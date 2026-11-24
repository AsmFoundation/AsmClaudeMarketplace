---
type: regex
target:
  source: file
  path: Sum/sum.wasm.s
pattern: 'PROTO\s+int32_t\s+sum_i32\s*\(\s*const\s+int32_t\s*\*\s*\w*\s*,\s*int32_t\b'
---

The PROTO line gives the C signature the bindings come from; it must lower to the FUNCTION's wasm type (ASM0132 otherwise), and it goes above the FUNCTION, never inside a function body.
