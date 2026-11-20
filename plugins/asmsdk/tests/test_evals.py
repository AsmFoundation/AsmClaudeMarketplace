"""Tests that keep the asmsdk evaluation suite consistent (evals/task, evals/controls, build_check.py).

Why these tests: a task case is judged twice, by regex graders over the files the agent wrote
and by build_check.py with the real SDK. Both judges are checked against the suite's controls,
answers known to be right (pass-<n>) or wrong (fail-<n>). `build_check.py --controls` runs the
SDK on them, which needs .NET, the SDK feed and Docker (see evals/README.md); these tests do
everything that needs none of that, so CI catches a grader, prompt or control that drifts:

- every regex and file_exists grader accepts every correct answer of its case: a grader that
  rejects a correct answer makes the plugin, or the base model, look worse than it is;
- each wrong answer fails exactly the graders FAIL_GRADERS lists, which also records what only
  the build check catches;
- the plugin's own linter reports nothing on the correct answers and something on each wrong one;
- each prompt and grader names the SDK version build_check.py builds with, and build_check.py has
  a branch for every case.

The graders are read with Python's re; the suite's patterns use only syntax that Python and
JavaScript share (no lookbehind, no inline flags), so the verdicts match claude plugin eval's.

Run: python -m unittest discover -s plugins/asmsdk/tests   (Python 3.8+, standard library only)
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from typing import Dict, List, Optional, Set, Tuple

TESTS = os.path.dirname(os.path.abspath(__file__))
# The linter and the helpers that run it come from the scripts' tests: one loaded copy of each
# script, and the same isolation from this machine's NuGet cache.
sys.path.insert(0, TESTS)
from test_scripts import check_asmproj, nuget_packages, run_json  # noqa: E402

EVALS = os.path.join(TESTS, "..", "evals")
TASKS = os.path.join(EVALS, "task")
CONTROLS = os.path.join(EVALS, "controls")


def load_build_check():
    """Import evals/build_check.py by path (evals/ is not a package).

    Returns:
        The loaded module; its constants (SDK_VERSION, HASH_PROJECT) are what the build check
        really uses, so the tests cannot drift from them.
    """
    spec = importlib.util.spec_from_file_location("build_check", os.path.join(EVALS, "build_check.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_check = load_build_check()

#: The task cases, by folder name.
CASES = sorted(d for d in os.listdir(TASKS) if os.path.isdir(os.path.join(TASKS, d)))

#: The graders each wrong answer fails; it passes all the others. An empty set means only
#: build_check.py catches that answer (a Tool project without RuntimeIdentifiers looks right
#: to every grader and stops with ASM0010), which is why the build check exists.
FAIL_GRADERS: Dict[Tuple[str, str], Set[str]] = {
    ("task-defines-keep-debug", "fail-1"): {"keeps-debug-defined"},
    ("task-dotnet-interop", "fail-1"): {"pinvoke-library-name", "argument-registers-per-os"},
    ("task-package-and-consume", "fail-1"): set(),
    ("task-port-to-every-os", "fail-1"): {"hash64-exported-everywhere", "mix64-internal-everywhere",
                                          "seed-private-extern-on-macos", "seed-hidden-on-linux",
                                          "argument-register-per-os"},
    ("task-port-to-every-os", "fail-2"): {"hash64-exported-everywhere", "mix64-internal-everywhere",
                                          "seed-private-extern-on-macos", "argument-register-per-os"},
}


def parse_grader(path: str) -> Dict[str, str]:
    """Read a grader's front matter, flattened to the keys this suite uses.

    The suite's YAML is simple: scalar keys, plus a `target:` mapping whose `path:` becomes the
    flat "path" (file_exists graders have it at the top). Single-quoted values are unquoted
    YAML's way ('' is a quote).

    Args:
        path: The grader's .md file.

    Returns:
        Key -> value (type, path, pattern, match, flags, tool, input_match).

    Raises:
        ValueError: The file has no front matter.
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise ValueError(f"{path}: no front matter")
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        # partition at the first colon only: patterns contain colons of their own.
        key, sep, value = line.strip().partition(":")
        value = value.strip()
        if not sep or not value:
            continue  # "target:" opens the nested mapping
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("''", "'")
        fields[key.strip()] = value
    return fields


def graders_of(case: str) -> Dict[str, Dict[str, str]]:
    """The graders of one task case.

    Args:
        case: The case folder name.

    Returns:
        Grader name (file name without .md) -> its parsed front matter.
    """
    folder = os.path.join(TASKS, case, "graders")
    return {name[:-3]: parse_grader(os.path.join(folder, name)) for name in sorted(os.listdir(folder)) if name.endswith(".md")}


def grade(fields: Dict[str, str], workspace: str) -> Optional[bool]:
    """Apply one file grader to a workspace the way claude plugin eval does.

    Args:
        fields: The grader's front matter.
        workspace: The folder the agent's files are in.

    Returns:
        Whether the grader passes; None for a grader of the transcript (tool_used), which a
        control does not have.
    """
    kind = fields.get("type")
    if kind == "file_exists":
        return os.path.isfile(os.path.join(workspace, fields["path"]))
    if kind == "regex":
        path = os.path.join(workspace, fields["path"])
        if not os.path.isfile(path):
            return False
        with open(path, encoding="utf-8") as f:
            text = f.read()
        flags = re.IGNORECASE if "i" in fields.get("flags", "") else 0
        found = re.search(fields["pattern"], text, flags) is not None
        return not found if fields.get("match") == "not_contains" else found
    return None


def controls_of(case: str) -> List[Tuple[str, str]]:
    """The controls of one case, as build_check.py --controls finds them.

    Args:
        case: The case folder name.

    Returns:
        (folder name, path) pairs such as ("pass-1", ...), in build_check.py's order.
    """
    return [(f"{arm}-{number}", path) for name, arm, number, path, _ in build_check.control_sources(CONTROLS) if name == case]


class EvalSuiteTests(unittest.TestCase):
    """The task cases, their graders, their controls and build_check.py agree with each other."""

    def test_every_case_has_controls_and_a_build_check(self) -> None:
        """Each case has a right and a wrong answer, a branch in build_check.py, and no control is orphaned."""
        with open(os.path.join(EVALS, "build_check.py"), encoding="utf-8") as f:
            source = f.read()
        for case in CASES:
            with self.subTest(case=case):
                names = [name for name, _ in controls_of(case)]
                self.assertTrue(any(n.startswith("pass-") for n in names), names)
                self.assertTrue(any(n.startswith("fail-") for n in names), names)
                self.assertIn(f'case == "{case}"', source)
        self.assertEqual(set(CASES), {d for d in os.listdir(CONTROLS) if os.path.isdir(os.path.join(CONTROLS, d))})

    def test_prompts_and_graders_name_the_built_sdk_version(self) -> None:
        """Prompts, graders and build_check.py name one SDK version, so a run builds what the task described."""
        version = build_check.SDK_VERSION
        for case in CASES:
            with self.subTest(case=case):
                with open(os.path.join(TASKS, case, "prompt.md"), encoding="utf-8") as f:
                    prompt = f.read()
                self.assertIn(f"AsmFoundation.Sdk {version}", prompt)
                self.assertEqual({version}, set(re.findall(r"AsmFoundation\.Sdk (\d+\.\d+\.\d+)", prompt)))
                for name, fields in graders_of(case).items():
                    pattern = fields.get("pattern", "")
                    # Only patterns about the SDK: a package's own version (Acme.Crc 1.2.0) is
                    # the task's, not the SDK's.
                    if "AsmFoundation" in pattern:
                        named = {m.replace("\\", "") for m in re.findall(r"\d+\\?\.\d+\\?\.\d+", pattern)}
                        self.assertLessEqual(named, {version}, f"{case}/{name}")

    def test_graders_accept_every_correct_answer(self) -> None:
        """Every file grader passes on every pass-<n> control of its case."""
        for case in CASES:
            graders = graders_of(case)
            for name, path in controls_of(case):
                if not name.startswith("pass-"):
                    continue
                for grader, fields in graders.items():
                    with self.subTest(case=case, control=name, grader=grader):
                        self.assertIn(grade(fields, path), (True, None))

    def test_wrong_answers_fail_the_listed_graders(self) -> None:
        """Each fail-<n> control fails exactly the graders FAIL_GRADERS names for it."""
        listed = set()
        for case in CASES:
            graders = graders_of(case)
            for name, path in controls_of(case):
                if not name.startswith("fail-"):
                    continue
                listed.add((case, name))
                with self.subTest(case=case, control=name):
                    failed = {g for g, fields in graders.items() if grade(fields, path) is False}
                    self.assertEqual(FAIL_GRADERS.get((case, name)), failed)
        self.assertEqual(set(FAIL_GRADERS), listed, "FAIL_GRADERS names a control that does not exist")

    def test_linter_agrees_with_the_controls(self) -> None:
        """check_asmproj.py finds nothing in a correct answer and at least one problem in each wrong one.

        Each control is linted as build_check.py builds it: with the global.json a task did not
        ask for, and with the project the port task's prompt shows.
        """
        with tempfile.TemporaryDirectory() as tmp, nuget_packages(None):
            for case in CASES:
                for name, path in controls_of(case):
                    workspace = os.path.join(tmp, case, name)
                    shutil.copytree(path, workspace)
                    if not os.path.isfile(os.path.join(workspace, "global.json")):
                        with open(os.path.join(workspace, "global.json"), "w", encoding="utf-8") as f:
                            json.dump({"msbuild-sdks": {"AsmFoundation.Sdk": build_check.SDK_VERSION}}, f)
                    if case == "task-port-to-every-os":
                        with open(os.path.join(workspace, "Hash", "Hash.asmproj"), "w", encoding="utf-8") as f:
                            f.write(build_check.HASH_PROJECT)
                    with self.subTest(case=case, control=name):
                        _, findings = run_json(check_asmproj, [workspace])
                        own = [f"{f['code']}: {f['message']}" for f in findings if f["severity"] in ("error", "warning")]
                        if name.startswith("pass-"):
                            self.assertEqual([], own)
                        else:
                            self.assertTrue(own, "the linter misses a wrong answer")


if __name__ == "__main__":
    unittest.main()
