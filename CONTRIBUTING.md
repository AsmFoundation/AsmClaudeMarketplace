# Contributing

Thank you for helping. This repository holds Claude Code plugins, one per topic, for the
AsmFoundation's products and practices. The organization-wide rules (conduct, security
reports) are in the [AsmFoundation profile](https://github.com/AsmFoundation/.github).

## What a plugin needs

1. **A manifest:** `plugins/<name>/.claude-plugin/plugin.json`, with name, version,
   description, author, homepage, repository, license (Apache-2.0) and keywords, plus a
   square `icon.png`.
2. **An entry in `.claude-plugin/marketplace.json`.**
3. **A skill:** `plugins/<name>/skills/<name>/SKILL.md`:
   - **The `description`** decides when Claude loads the skill. Name the products, files,
     commands and error messages a user would mention. Say what the skill is not for, so
     that near misses stay silent.
   - **The body stays short:** under about 500 lines. Depth goes into `references/`, each
     file with a table of contents. Say in `SKILL.md` when to read each one.
   - **State only what was measured.** Mark statements that were measured by building or
     running as *verified*, and say which version they hold for.
4. **Scripts, when a task is deterministic:** `scripts/`, Python 3.8+ with the standard
   library only. Fully documented: every function's arguments, return value and
   exceptions. Unit tests go in `plugins/<name>/tests/`.
5. **An evaluation:** `plugins/<name>/evals/`, a `claude plugin eval` suite:
   - **Trigger cases:** at least 8 requests that should load the skill and 8 near misses
     that should not, each with a `tool_used: Skill` grader.
   - **Task cases:** run with and without the plugin. Prefer free graders (`regex`,
     `file_exists`) over judge models, so scores stay stable.
   - **A real-tools check:** when the task produces something buildable, build and run it
     with the real tools (see `plugins/asmsdk/evals/build_check.py`).
   - **Results:** commit them under `evals/benchmarks/<date>-<model>/`, with a README that
     says what was measured.

## Before opening a pull request

```sh
claude plugin validate .
claude plugin validate plugins/<name>
python -m unittest discover -s plugins/<name>/tests
```

When you change a skill's description or its recipes, run the plugin's evals and update the
committed results. Say in the pull request what changed in the numbers.

## Style

- Plain, direct English. Short sentences. One idea per bullet.
- Concrete over abstract: the exact error message, the exact property, the exact command.
- Explain why a rule exists, so the model can apply it to cases the text does not list.
