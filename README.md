# AsmClaudeMarketplace

[![CI](https://github.com/AsmFoundation/AsmClaudeMarketplace/actions/workflows/ci.yml/badge.svg)](https://github.com/AsmFoundation/AsmClaudeMarketplace/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Claude Code plugins for the [AsmFoundation](https://github.com/AsmFoundation)
ecosystem,** one plugin per topic. Each plugin teaches Claude one AsmFoundation product or
practice well enough to work with it without guessing:

- every fact it states was measured against the real tools;
- every plugin ships an evaluation that compares Claude with and without it.

```text
/plugin marketplace add AsmFoundation/AsmClaudeMarketplace
/plugin install asmsdk@asmfoundation
```

The marketplace's name is `asmfoundation`, so its plugins install as
`<plugin>@asmfoundation`. Update with `/plugin marketplace update asmfoundation`.

## Plugins

| Plugin | Covers | Status |
|---|---|---|
| [`asmsdk`](plugins/asmsdk) | [AsmSdk](https://asmfoundation.github.io/AsmSdk/) (`AsmFoundation.Sdk`): `.asmproj` projects, NuGet packages of assembly code, .NET and Python interop, toolchain, CI and releases. Includes a complete property, item, target and error reference, the NASM rules that decide whether code links, and scripts to scaffold, lint and inspect | 0.1.1, for AsmSdk 0.1.0 |

See [ROADMAP.md](ROADMAP.md) for the plugins proposed next, and why.

## How the plugins are made

- **Measured, not argued.** A plugin states a behavior only after reproducing it with the
  product's real release. Each statement is marked *verified* when it was measured by
  building or running. Claims that could not be measured are worded as such.
- **Progressive disclosure.** Each skill keeps a short `SKILL.md` (the model, the recipes,
  the footguns) and puts depth in `references/`, which Claude reads only when a task needs
  it. Deterministic work goes into tested `scripts/`.
- **Evaluated.** Every plugin has a `claude plugin eval` suite with two kinds of case:
  - **trigger cases:** requests that should, and near misses that should not, load the
    skill;
  - **task cases:** run with and without the plugin, then graded on the files Claude wrote.

  Where a task produces something buildable, the result is also built and run with the
  real tools. The results are committed next to the suite.
- **One plugin per topic,** so that installing one product's knowledge does not load
  another's.

## Repository layout

```text
.claude-plugin/marketplace.json     the marketplace catalog
plugins/<name>/
  .claude-plugin/plugin.json        manifest (and icon.png)
  skills/<name>/SKILL.md            the skill; references/ and scripts/ beside it
  tests/                            unit tests for the scripts
  evals/                            claude plugin eval suite, build checks and committed results
```

## Developing

```sh
claude plugin validate .                                  # the marketplace
claude plugin validate plugins/asmsdk                     # one plugin
python -m unittest discover -s plugins/asmsdk/tests       # its scripts
claude --plugin-dir plugins/asmsdk                        # try it in a session
claude plugin eval plugins/asmsdk --tag trigger --ablation none --no-publish   # its trigger suite
```

CI runs the validation and the unit tests on every push. Running the evals costs model usage,
so they are run by hand before a release, and the results are committed (see each plugin's
`evals/README.md`). Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE).
