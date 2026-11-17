---
type: regex
target:
  source: file
  path: Tool/Tool.asmproj
pattern: '<PackageReference\s+Include="Acme\.Crc"\s+Version="\[?1\.2\.0'
---

Tool references Acme.Crc 1.2.0 as a package.
