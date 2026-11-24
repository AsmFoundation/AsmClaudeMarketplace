---
type: file_exists
path: Sum/sum.wasm.s
---

The source is qualified for WebAssembly (`sum.wasm.s`, both RIDs): no unqualified file builds wasm (an unqualified `.s` is ARM64 code, and the build stops with ASM0023). Two per-RID files (`sum.browser.s`, `sum.wasi.s`) would build too but fail this grader; the build check is the judge there.
