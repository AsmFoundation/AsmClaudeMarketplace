---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
tags: [task, task-defines-keep-debug]
---

Our asm library project `Fast/Fast.asmproj` (AsmFoundation.Sdk 0.3.0) currently reads:

```xml
<Project Sdk="AsmFoundation.Sdk">
  <PropertyGroup>
    <AssemblyName>fast</AssemblyName>
    <RuntimeIdentifiers>linux-x64;win-x64</RuntimeIdentifiers>
  </PropertyGroup>
</Project>
```

and `Fast/fast.asm` uses `%ifdef DEBUG` blocks for extra checks in Debug builds. I need every build (Debug and Release, on both platforms) to also define the NASM symbol `USE_AVX2=1`, without changing anything else about how Debug and Release builds behave today. The project is not checked out here: write the complete updated project file to `Fast/Fast.asmproj` in the current directory. You cannot run commands. Keep explanations short.
