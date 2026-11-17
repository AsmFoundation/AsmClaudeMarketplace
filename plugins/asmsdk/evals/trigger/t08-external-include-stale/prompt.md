---
max_turns: 5
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger, should-trigger]
---

Our asm sources include macros from ../common/macros.inc through an AsmIncludeDirectory item, but when I change a macro the build says it's up to date and the binary doesn't change. How do I make it rebuild correctly?
