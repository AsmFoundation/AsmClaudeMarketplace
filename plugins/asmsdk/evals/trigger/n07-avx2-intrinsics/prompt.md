---
max_turns: 5
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger, should-not-trigger]
---

Optimize this C function with AVX2 intrinsics: void add(float *a, const float *b, int n) { for (int i = 0; i < n; i++) a[i] += b[i]; }
