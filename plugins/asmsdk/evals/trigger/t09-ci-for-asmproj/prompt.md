---
max_turns: 5
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger, should-trigger]
---

Set up GitHub Actions for a repo of .asmproj projects: build on Windows, Linux and macOS, run the executables on Linux, and push the packages to nuget.org when I push a version tag.
