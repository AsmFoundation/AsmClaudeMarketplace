"""Tests for the asmsdk skill's scripts (check_asmproj.py, new_asmproj.py, inspect_elf.py).

Why these tests: the scripts encode facts measured against AsmFoundation.Sdk 0.1.0, NASM 3.02
and ld.lld 23.1.5. Each linter check gets a fixture that must trigger it (so a regression in a
check is caught) and a clean project that must not (so false errors are caught). The fixtures
are generated into a temporary folder from the dictionaries below, which keeps them readable
next to the assertions. No .NET SDK, NASM or LLVM is needed: inspect_elf.py is tested on a
canned llvm-readobj JSON document.

Run: python -m unittest discover -s plugins/asmsdk/tests   (Python 3.8+, standard library only)
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from typing import Dict, List, Set

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "asmsdk", "scripts")


def load(name: str):
    """Import one script as a module by path (the scripts folder is not a package).

    Args:
        name: Script file name without .py.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class is created, so the
    # module must be registered before it executes.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_asmproj = load("check_asmproj")
new_asmproj = load("new_asmproj")
inspect_elf = load("inspect_elf")

NOTE = "section .note.GNU-stack noalloc noexec nowrite progbits\n"
GOOD_FN = "default rel\nsection .text\nglobal {n}:function ({n}.end - {n})\n{n}:\n    xor eax, eax\n    ret\n.end:\n" + NOTE


def proj(props: str = "", items: str = "") -> str:
    """An .asmproj with the given PropertyGroup and ItemGroup bodies.

    Args:
        props: XML placed inside the PropertyGroup.
        items: XML placed inside the ItemGroup.

    Returns:
        The project file's text.
    """
    return f'<Project Sdk="AsmFoundation.Sdk">\n  <PropertyGroup>{props}</PropertyGroup>\n  <ItemGroup>{items}</ItemGroup>\n</Project>\n'


#: Fixture tree: relative path -> content. One folder per scenario; the expected findings are
#: in EXPECTED below. The tree has its own global.json so ASMSLN001 never fires by accident.
FIXTURES: Dict[str, str] = {
    "global.json": '{ "msbuild-sdks": { "AsmFoundation.Sdk": "0.1.0" } }\n',
    # A correct shared library: must produce no error or warning.
    "good/Good.asmproj": proj("<AsmLibraryName>good</AsmLibraryName><AsmFlags>-Xvc</AsmFlags><AsmLinkFlags>-z defs</AsmLinkFlags>"),
    "good/include/good.inc": "%ifndef GOOD_INC\n%define GOOD_INC\nextern good_fn\n%endif\n",
    "good/good.asm": '%include "good.inc"\n' + GOOD_FN.format(n="good_fn"),
    # AsmDefineConstants that "appends" but loses DEBUG.
    "defines/Defines.asmproj": proj("<AsmDefineConstants>$(AsmDefineConstants);FOO</AsmDefineConstants>"),
    "defines/a.asm": GOOD_FN.format(n="d"),
    # An include folder outside the project, not tracked.
    "shared/shared.inc": "%define SHARED 1\n",
    "extinc/ExtInc.asmproj": proj(items='<AsmIncludeDirectory Include="../shared/" />'),
    "extinc/a.asm": '%include "shared.inc"\n' + GOOD_FN.format(n="e"),
    # The same, fixed with AsmInclude: must not warn.
    "extinc_ok/ExtIncOk.asmproj": proj(items='<AsmIncludeDirectory Include="../shared/" /><AsmInclude Include="../shared/**/*.inc" />'),
    "extinc_ok/a.asm": '%include "shared.inc"\n' + GOOD_FN.format(n="e2"),
    # An .asm included by another source.
    "dup/Dup.asmproj": proj(),
    "dup/helpers.asm": "default rel\nsection .text\nglobal helper:function\nhelper:\n    ret\n" + NOTE,
    "dup/main.asm": '%include "helpers.asm"\n' + GOOD_FN.format(n="m"),
    # A packable library whose include file is not in include/.
    "pack/Pack.asmproj": proj("<OutputType>StaticLibrary</OutputType><PackageId>Acme.Pack</PackageId>"),
    "pack/pack.inc": "extern pk\n",
    "pack/a.asm": GOOD_FN.format(n="pk"),
    # A freestanding executable referencing a shared-only library.
    "sharedlib/SharedLib.asmproj": proj(),
    "sharedlib/lib.asm": GOOD_FN.format(n="lib_value"),
    "exeshared/App.asmproj": proj("<OutputType>Exe</OutputType>", '<ProjectReference Include="../sharedlib/SharedLib.asmproj" />'),
    "exeshared/main.asm": "default rel\nextern lib_value\nsection .text\nglobal _start:function\n_start:\n    call lib_value\n    mov eax, 231\n    syscall\n" + NOTE,
    # A reference to an Objects project (0.1.0 bug).
    "objs/Objs.asmproj": proj("<OutputType>Objects</OutputType>"),
    "objs/o.asm": GOOD_FN.format(n="objs_value"),
    "objref/App.asmproj": proj("<OutputType>Exe</OutputType>", '<ProjectReference Include="../objs/Objs.asmproj" />'),
    "objref/main.asm": "default rel\nextern objs_value\nsection .text\nglobal _start:function\n_start:\n    call objs_value\n    mov eax, 231\n    syscall\n" + NOTE,
    # Unquoted $ORIGIN without an OS condition.
    "rpath/Rpath.asmproj": proj("<AsmLinkFlags>-rpath $ORIGIN</AsmLinkFlags>"),
    "rpath/a.asm": GOOD_FN.format(n="r"),
    # Every PIC mistake in one shared library.
    "pic/Pic.asmproj": proj(),
    "pic/helper.asm": "default rel\nsection .text\nglobal helper2:function\nhelper2:\n    ret\nsection .data\nglobal counter:data 4\ncounter: dd 0\n" + NOTE,
    "pic/pic.asm": ("extern helper2, counter\nsection .rodata\nmsg: db 'x', 0\ntable: dq t1\n"
                    "section .data.rel.ro\nptrs: dq t1\n"
                    "section .text\nglobal f:function\nf:\n    lea rax, [msg]\n    call helper2\n"
                    "    mov eax, [rel counter]\n    mov rax, msg\nt1:\n    ret\n" + NOTE),
    # A visibility written after the size (NASM ignores it), so the helper is still preemptible
    # and the direct call fails to link in a .so.
    "latehidden/LateHidden.asmproj": proj(),
    "latehidden/helper.asm": "default rel\nsection .text\nglobal h3:function (h3.end - h3) hidden\nh3:\n    ret\n.end:\n" + NOTE,
    "latehidden/a.asm": "default rel\nextern h3\nsection .text\nglobal f3:function\nf3:\n    call h3\n    ret\n" + NOTE,
    # The correct order: visibility before the size; the direct call is fine.
    "earlyhidden/EarlyHidden.asmproj": proj(),
    "earlyhidden/helper.asm": "default rel\nsection .text\nglobal h4:function hidden (h4.end - h4)\nh4:\n    ret\n.end:\n" + NOTE,
    "earlyhidden/a.asm": "default rel\nextern h4\nsection .text\nglobal f4:function\nf4:\n    call h4\n    ret\n" + NOTE,
    # A keyword used as a symbol name.
    "kw/Kw.asmproj": proj(),
    "kw/a.asm": "default rel\nsection .text\nglobal wait:function\nwait:\n    ret\n" + NOTE,
    # %include of a file that is only next to the including source.
    "subinc/SubInc.asmproj": proj(),
    "subinc/src/sub/a.asm": '%include "b.inc"\n' + GOOD_FN.format(n="s"),
    "subinc/src/sub/b.inc": "%define B 1\n",
    # A Libc executable calling a libc function the stub does not list.
    "libcexe/LibcExe.asmproj": proj("<OutputType>Exe</OutputType><AsmRuntime>Libc</AsmRuntime>"),
    "libcexe/main.asm": "default rel\nextern strsignal, printf\nsection .text\nglobal main:function\nmain:\n    push rbx\n    call strsignal wrt ..plt\n    call printf wrt ..plt\n    pop rbx\n    ret\n" + NOTE,
    # The same with AsmLibcSymbol: must not error.
    "libcexe_ok/LibcExeOk.asmproj": proj("<OutputType>Exe</OutputType><AsmRuntime>Libc</AsmRuntime>", '<AsmLibcSymbol Include="strsignal" />'),
    "libcexe_ok/main.asm": "default rel\nextern strsignal\nsection .text\nglobal main:function\nmain:\n    push rbx\n    call strsignal wrt ..plt\n    pop rbx\n    ret\n" + NOTE,
    # An executable without its entry symbol.
    "noentry/NoEntry.asmproj": proj("<OutputType>Exe</OutputType>"),
    "noentry/a.asm": GOOD_FN.format(n="not_start"),
    # A solution entry without the type GUID.
    "Bad.slnx": '<Solution>\n  <Project Path="good/Good.asmproj" />\n</Solution>\n',
}

#: Expected error- and warning-level codes per fixture path (info findings are not asserted:
#: they are recommendations whose presence depends on the project's settings).
EXPECTED: Dict[str, Set[str]] = {
    "good/Good.asmproj": set(),
    "defines/Defines.asmproj": {"ASMPRJ001"},
    "extinc/ExtInc.asmproj": {"ASMPRJ002"},
    "extinc_ok/ExtIncOk.asmproj": set(),
    "dup/Dup.asmproj": {"ASMSRC010"},
    "pack/Pack.asmproj": {"ASMPRJ003"},
    "exeshared/App.asmproj": {"ASMREF001"},
    "objref/App.asmproj": {"ASMREF002"},
    "rpath/Rpath.asmproj": {"ASMPRJ006"},
    "pic/Pic.asmproj": {"ASMPIC001", "ASMPIC002", "ASMPIC003", "ASMPIC004", "ASMPIC005", "ASMSRC005"},
    "latehidden/LateHidden.asmproj": {"ASMSRC013", "ASMPIC002"},
    "earlyhidden/EarlyHidden.asmproj": set(),
    "kw/Kw.asmproj": {"ASMSRC008"},
    "subinc/SubInc.asmproj": {"ASMSRC009"},
    "libcexe/LibcExe.asmproj": {"ASMSRC012"},
    "libcexe_ok/LibcExeOk.asmproj": set(),
    "noentry/NoEntry.asmproj": {"ASMSRC011"},
    "Bad.slnx": {"ASMSLN002"},
}


def write_tree(root: str, files: Dict[str, str]) -> None:
    """Write a fixture tree (LF line endings, as the scripts' outputs use).

    Args:
        root: Destination folder.
        files: Relative path -> content.
    """
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="\n", encoding="utf-8") as f:
            f.write(text)


def run_json(module, argv: List[str]):
    """Run a script's main() with --json and return (exit code, parsed stdout).

    Args:
        module: A loaded script module.
        argv: Arguments, without --json.

    Returns:
        (exit code, the JSON document the script printed).
    """
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = module.main(argv + ["--json"])
    return code, json.loads(out.getvalue())


class CheckAsmprojTests(unittest.TestCase):
    """Each fixture triggers exactly its expected error/warning codes, and no others."""

    @classmethod
    def setUpClass(cls) -> None:
        """Write the fixture tree once; every test reads it, none modifies it."""
        cls.tmp = tempfile.TemporaryDirectory()
        write_tree(cls.tmp.name, FIXTURES)

    @classmethod
    def tearDownClass(cls) -> None:
        """Delete the fixture tree."""
        cls.tmp.cleanup()

    def test_each_fixture(self) -> None:
        """Every fixture yields exactly its expected codes, and the exit code matches."""
        for rel, expected in EXPECTED.items():
            with self.subTest(fixture=rel):
                code, findings = run_json(check_asmproj, [os.path.join(self.tmp.name, rel)])
                own = [f for f in findings if f["severity"] in ("error", "warning")]
                self.assertEqual(expected, {f["code"] for f in own}, json.dumps(own, indent=1))
                has_error = any(f["severity"] == "error" for f in own)
                self.assertEqual(1 if has_error else 0, code)

    def test_missing_global_json(self) -> None:
        """A project with no global.json above it cannot resolve the SDK."""
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(tmp, {"p/P.asmproj": proj(), "p/a.asm": GOOD_FN.format(n="x")})
            # Only meaningful when no global.json exists in the temp folder's ancestors.
            if any(os.path.isfile(os.path.join(d, "global.json")) for d in _ancestors(tmp)):
                self.skipTest("a global.json exists above the temporary folder")
            _, findings = run_json(check_asmproj, [os.path.join(tmp, "p")])
            self.assertIn("ASMSLN001", {f["code"] for f in findings})

    def test_no_project_is_usage_error(self) -> None:
        """A folder with no project or solution is a usage error (exit 2), not a clean pass."""
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, check_asmproj.main([tmp]))


def _ancestors(path: str) -> List[str]:
    """The folder and all its parents, for the global.json skip check.

    Args:
        path: Starting folder.

    Returns:
        Absolute folders from path up to the filesystem root.
    """
    result, current = [], os.path.abspath(path)
    while True:
        result.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            return result
        current = parent


class NewAsmprojTests(unittest.TestCase):
    """Scaffolds are lint-clean, never overwrite, and register in the .slnx."""

    def test_every_kind_is_lint_clean(self) -> None:
        """All kinds and runtimes scaffold into one solution with no error or warning."""
        with tempfile.TemporaryDirectory() as tmp:
            cases = [["Lib", "--lib-name", "fastmath"], ["Static", "--kind", "static", "--package-id", "Acme.S"],
                     ["App", "--kind", "exe"], ["LApp", "--kind", "exe", "--runtime", "libc"],
                     ["LLib", "--runtime", "libc", "--package-id", "Acme.L", "--version", "2.0.0"],
                     ["Objs", "--kind", "objects"]]
            for case in cases:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, new_asmproj.main([os.path.join(tmp, case[0])] + case[1:]
                                                         + ["--sln", os.path.join(tmp, "App.slnx"), "--root", tmp]))
            _, findings = run_json(check_asmproj, [tmp])
            bad = [f for f in findings if f["severity"] in ("error", "warning")]
            self.assertEqual([], bad)
            with open(os.path.join(tmp, "App.slnx"), encoding="utf-8") as f:
                slnx = f.read()
            self.assertEqual(6, slnx.count(new_asmproj.ASMPROJ_TYPE_GUID))
            with open(os.path.join(tmp, "global.json"), encoding="utf-8") as f:
                self.assertEqual("0.1.0", json.load(f)["msbuild-sdks"]["AsmFoundation.Sdk"])

    def test_never_overwrites(self) -> None:
        """A second run keeps every file and leaves its content unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "Lib")
            with contextlib.redirect_stdout(io.StringIO()):
                new_asmproj.main([target, "--root", tmp])
            path = os.path.join(target, "Lib.asmproj")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<!-- edited by hand -->")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                new_asmproj.main([target, "--root", tmp])
            with open(path, encoding="utf-8") as f:
                self.assertEqual("<!-- edited by hand -->", f.read())
            self.assertIn("kept", out.getvalue())

    def test_existing_global_json_is_merged(self) -> None:
        """An existing global.json keeps its settings and gains only the msbuild-sdks entry."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "global.json"), "w", encoding="utf-8") as f:
                json.dump({"sdk": {"version": "10.0.100"}}, f)
            with contextlib.redirect_stdout(io.StringIO()):
                new_asmproj.main([os.path.join(tmp, "Lib"), "--root", tmp])
            with open(os.path.join(tmp, "global.json"), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual("10.0.100", data["sdk"]["version"])
            self.assertEqual("0.1.0", data["msbuild-sdks"]["AsmFoundation.Sdk"])


class InspectElfTests(unittest.TestCase):
    """Summaries and expectations from llvm-readobj's JSON, without running llvm-readobj."""

    DOC = {
        "ElfHeader": {"Type": "SharedObject (0x3)", "Entry": 0},
        "ProgramHeaders": [{"ProgramHeader": {"Type": {"Name": "PT_GNU_STACK"}, "Flags": {"Flags": [{"Name": "PF_R"}, {"Name": "PF_W"}]}}}],
        "DynamicSection": [{"Type": "NEEDED", "Library": "libc.so.6"}, {"Type": "SONAME", "Name": "libx.so"},
                           {"Type": "RUNPATH", "Path": ["$ORIGIN"]}, {"Type": "FLAGS_1", "Flags": ["NOW"]}],
        "DynamicSymbols": [
            {"Symbol": {"Name": {"Name": "x_add"}, "Size": 4, "Binding": {"Name": "Global"}, "Type": {"Name": "Function"}, "Section": {"Name": ".text", "Value": 5}}},
            {"Symbol": {"Name": {"Name": "strlen"}, "Size": 0, "Binding": {"Name": "Global"}, "Type": {"Name": "None"}, "Section": {"Name": "Undefined", "Value": 0}}},
        ],
        "NoteSections": [{"NoteSection": {"Notes": [{"Build ID": "abc"}]}}],
    }

    def test_summary(self) -> None:
        """Kind, SONAME, NEEDED, RUNPATH, stack, exports and imports come out of the JSON."""
        s = inspect_elf.summarize_elf("libx.so", self.DOC)
        self.assertEqual("shared", s["kind"])
        self.assertEqual("libx.so", s["soname"])
        self.assertEqual(["libc.so.6"], s["needed"])
        self.assertEqual(["$ORIGIN"], s["runpath"])
        self.assertIs(False, s["executable_stack"])
        self.assertEqual(["x_add"], [e["name"] for e in s["exports"]])
        self.assertEqual(["strlen"], s["imports"])

    def test_expectations(self) -> None:
        """Met expectations pass; a missing export and a wrong kind both fail."""
        s = inspect_elf.summarize_elf("libx.so", self.DOC)
        ok = inspect_elf.argparse.Namespace(expect_type="shared", expect_export=["x_add"], expect_needed=["libc.so.6"],
                                            expect_no_needed=False, expect_runpath="$ORIGIN", expect_nonexec_stack=True)
        self.assertEqual([], inspect_elf.check_expectations(s, ok))
        bad = inspect_elf.argparse.Namespace(expect_type="pie", expect_export=["missing"], expect_needed=None,
                                             expect_no_needed=True, expect_runpath=None, expect_nonexec_stack=False)
        self.assertEqual(3, len(inspect_elf.check_expectations(s, bad)))


if __name__ == "__main__":
    unittest.main()
