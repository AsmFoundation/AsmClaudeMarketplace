---
max_turns: 5
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger, should-trigger]
---

I have a folder of NASM .asm files that we currently build with a Makefile. I'd like them built by `dotnet build` as part of our .NET solution instead, producing libfast.so. How do I set that up?
