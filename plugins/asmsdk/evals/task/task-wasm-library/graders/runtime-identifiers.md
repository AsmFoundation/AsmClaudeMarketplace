---
type: regex
target:
  source: file
  path: Sum/Sum.asmproj
pattern: '<RuntimeIdentifiers>\s*(browser-wasm;wasi-wasm|wasi-wasm;browser-wasm)\s*</RuntimeIdentifiers>'
---

The project lists both WebAssembly RIDs: a project builds the RIDs it lists, and with none it stops with ASM0010.
