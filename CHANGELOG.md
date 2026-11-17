# Changelog

Changes to the marketplace and its plugins. Each plugin carries its own version in its
`plugin.json`. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## 2026-11-17

### Added

- **The `asmfoundation` marketplace,** with one plugin per topic.
- **`asmsdk` 0.1.0, for AsmFoundation.Sdk 0.1.0:**
  - a skill covering the whole SDK: the model, recipes, the NASM linking rules, diagnostics
    and verified footguns;
  - nine reference files;
  - three tested scripts: `new_asmproj.py` scaffolds, `check_asmproj.py` lints with 31
    checks, and `inspect_elf.py` inspects ELF outputs;
  - a `claude plugin eval` suite: 20 trigger cases and 4 task cases, plus a build check that
    builds and runs what each arm wrote. Results are committed in
    `plugins/asmsdk/evals/benchmarks/`.
- **ROADMAP.md,** the proposed next plugins.
