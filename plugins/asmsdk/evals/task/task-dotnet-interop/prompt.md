---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-dotnet-interop]
---

Create a new solution in the current directory, from scratch, with exactly these projects:

- `Calc.slnx`: the solution, listing both projects.
- `Calc.Native/Calc.Native.asmproj`: an x86-64 assembly shared library built with AsmFoundation.Sdk 0.1.0 (NASM syntax). Its source `Calc.Native/calc.asm` exports `int64_t calc_sum(const int64_t *values, int64_t count)`. The library file must be named `libcalc.so`.
- `Calc.App/Calc.App.csproj`: a .NET 10 console app whose `Calc.App/Program.cs` calls calc_sum through P/Invoke on the array {1, 2, 3, 4} and prints the result.

`dotnet build Calc.slnx` must work on a Windows, Linux or macOS machine that has only the .NET 10 SDK. Write every file that is needed to disk, in the current directory. You cannot run commands. Keep explanations short.
