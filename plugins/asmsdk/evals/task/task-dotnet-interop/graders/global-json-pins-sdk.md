---
type: regex
target:
  source: file
  path: global.json
pattern: '"msbuild-sdks"\s*:\s*\{[^}]*"AsmFoundation\.Sdk"\s*:\s*"0\.3\.0"'
---

global.json names AsmFoundation.Sdk 0.3.0 under msbuild-sdks, so the SDK resolves.
