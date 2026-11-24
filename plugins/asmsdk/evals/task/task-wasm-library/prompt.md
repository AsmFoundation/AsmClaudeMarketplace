---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-wasm-library]
---

Our repository builds its assembly with AsmFoundation.Sdk 0.3.0, restored from a local feed that holds a build of AsmSdk's main branch, which already builds WebAssembly; `global.json` and the feed are in place. Add a library project `Sum` that builds for the browser and for WASI (`browser-wasm` and `wasi-wasm`) and exports one function, `int32_t sum_i32(const int32_t* values, int32_t count)`, which returns the sum of the `count` 32-bit integers at `values` (0 when `count` is 0). Declare it with a PROTO line, so that a .NET app referencing the project gets generated C# bindings. Write `Sum/Sum.asmproj` and the assembly source, named `sum` with whatever extension the SDK needs, in `Sum/` in the current directory. You cannot run commands. Keep explanations short.
