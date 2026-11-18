# Changelog

Changes to the marketplace and its plugins. Each plugin carries its own version in its
`plugin.json`. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## 2026-11-18

### Changed

- **`asmsdk` 0.1.1** points at the AsmSdk documentation site,
  <https://asmfoundation.github.io/AsmSdk/>: the skill names it as the page to check for
  newer SDK versions and to link users to, and the plugin and marketplace READMEs link it.
  The site's guides are written from the same verified facts as the skill.

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
    `plugins/asmsdk/evals/benchmarks/`:
    - triggering was 30/30 and 0/30 on Sonnet 5.5, and 10/10 and 0/10 on Opus 5.5;
    - task graders scored 1.00 with the plugin and 0.78 without;
    - 12 of 12 workspaces built with the real SDK, against 4 of 12.
- **ROADMAP.md,** the proposed next plugins.
