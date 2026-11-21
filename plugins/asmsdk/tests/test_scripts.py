"""Tests for the asmsdk skill's scripts (check_asmproj.py, new_asmproj.py, inspect_output.py).

Why these tests: the scripts encode facts measured against AsmFoundation.Sdk 0.3.0, NASM 3.02
and LLVM 23.1.5 (llvm-mc, lld, llvm-readobj). Each linter check gets a fixture that must
trigger it (so a regression in a check is caught) and a clean project that must not (so false
errors are caught); the 0.3.0 checks also get fixtures for each platform rule (what macOS's
and Windows' NASM output rejects, the RID rules, the source selection). The fixtures are
generated into a temporary folder from the dictionaries below, which keeps them readable next
to the assertions. No .NET SDK, NASM or LLVM is needed: inspect_output.py is tested on canned
llvm-readobj output (JSON for ELF, text for PE and Mach-O), and the per-OS C library lists on a
fake SDK package folder.

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
from typing import Dict, List, Optional, Set

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
inspect_output = load("inspect_output")

#: Linux-only sources (the RID the fixtures default to): ELF's own directives are right there.
NOTE = "section .note.GNU-stack noalloc noexec nowrite progbits\n"
GOOD_FN = "default rel\nsection .text\nglobal {n}:function ({n}.end - {n})\n{n}:\n    xor eax, eax\n    ret\n.end:\n" + NOTE

#: A source for every OS: asmsdk.inc's FUNCTION, the note only on Linux.
PORTABLE_FN = ('default rel\n%include "asmsdk.inc"\nsection .text\nFUNCTION {n}\n    xor eax, eax\n    RETURN\nENDFUNCTION\n'
               "%ifdef LINUX\n" + NOTE + "%endif\n")


def proj(props: str = "", items: str = "", rids: Optional[str] = "linux-x64") -> str:
    """An .asmproj with the given PropertyGroup and ItemGroup bodies.

    Args:
        props: XML placed inside the PropertyGroup.
        items: XML placed inside the ItemGroup.
        rids: RuntimeIdentifiers to declare (0.3.0 requires them); None for a project that
            names none.

    Returns:
        The project file's text.
    """
    rid_xml = f"<RuntimeIdentifiers>{rids}</RuntimeIdentifiers>" if rids else ""
    return f'<Project Sdk="AsmFoundation.Sdk">\n  <PropertyGroup>{rid_xml}{props}</PropertyGroup>\n  <ItemGroup>{items}</ItemGroup>\n</Project>\n'


#: Fixture tree: relative path -> content. One folder per scenario; the expected findings are
#: in EXPECTED below. The tree has its own global.json so ASMSLN001 never fires by accident.
FIXTURES: Dict[str, str] = {
    "global.json": '{ "msbuild-sdks": { "AsmFoundation.Sdk": "0.3.0" } }\n',
    # A correct shared library: must produce no error or warning.
    "good/Good.asmproj": proj("<AssemblyName>good</AssemblyName>", '<LinkerArg Include="-z defs" />'),
    "good/include/good.inc": "%ifndef GOOD_INC\n%define GOOD_INC\nextern good_fn\n%endif\n",
    "good/good.asm": '%include "good.inc"\n' + GOOD_FN.format(n="good_fn"),
    # DefineConstants: the SDK appends DEBUG/RELEASE and FREESTANDING/LIBC after the project
    # body, so setting it drops nothing.
    "defines/Defines.asmproj": proj("<DefineConstants>FOO;LEVEL=3</DefineConstants>"),
    "defines/a.asm": GOOD_FN.format(n="d"),
    # 0.1.0's own names: 0.2.0 and later fail the build with ASM0100-ASM0108.
    "oldnames/OldNames.asmproj": proj("<AsmLibraryName>old</AsmLibraryName><AsmRuntime>Libc</AsmRuntime>"
                                      "<AsmDefineConstants>FOO</AsmDefineConstants><AsmLinkFlags>-z defs</AsmLinkFlags>",
                                      '<AsmDefine Include="BAR" />'),
    "oldnames/a.asm": GOOD_FN.format(n="o"),
    # 0.2.0's platform settings: 0.3.0 ignores them, so the project names no RID.
    "removed030/Removed030.asmproj": proj("<AsmTargetRid>linux-x64</AsmTargetRid><AsmFormat>elf64</AsmFormat>"),
    "removed030/a.asm": GOOD_FN.format(n="r030"),
    # Two projects of one restore graph named alike: PackageId defaults to AssemblyName.
    "ambig/core/Core.asmproj": proj("<OutputType>StaticLibrary</OutputType><AssemblyName>engine</AssemblyName>"),
    "ambig/core/core.asm": GOOD_FN.format(n="core_fn"),
    "ambig/native/Native.asmproj": proj("<AssemblyName>engine</AssemblyName>", '<ProjectReference Include="../core/Core.asmproj" />'),
    "ambig/native/native.asm": GOOD_FN.format(n="native_fn"),
    # The same with a PackageId each: must not error.
    "ambig_ok/core/Core.asmproj": proj("<OutputType>StaticLibrary</OutputType><AssemblyName>engine2</AssemblyName><PackageId>Acme.Engine</PackageId>"),
    "ambig_ok/core/core.asm": GOOD_FN.format(n="core2_fn"),
    "ambig_ok/native/Native.asmproj": proj("<AssemblyName>engine2</AssemblyName><PackageId>Acme.Engine.Native</PackageId>",
                                           '<ProjectReference Include="../core/Core.asmproj" />'),
    "ambig_ok/native/native.asm": GOOD_FN.format(n="native2_fn"),
    # A freestanding project referencing a libc-only one (NU1201 at restore).
    "fsref/lib/LibcOnly.asmproj": proj("<OutputType>StaticLibrary</OutputType><TargetFramework>libc</TargetFramework>"),
    "fsref/lib/lib.asm": GOOD_FN.format(n="libc_only_fn"),
    "fsref/app/App.asmproj": proj("<OutputType>StaticLibrary</OutputType>", '<ProjectReference Include="../lib/LibcOnly.asmproj" />'),
    "fsref/app/app.asm": GOOD_FN.format(n="fs_app_fn"),
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
    # An explicit AsmSource item for a file the default glob already includes (ASM0024).
    "dupsrc/DupSrc.asmproj": proj(items='<AsmSource Include="a.asm" />'),
    "dupsrc/a.asm": GOOD_FN.format(n="dupsrc_fn"),
    # A packable library whose include file is not in include/.
    "pack/Pack.asmproj": proj("<OutputType>StaticLibrary</OutputType><PackageId>Acme.Pack</PackageId>"),
    "pack/pack.inc": "extern pk\n",
    "pack/a.asm": GOOD_FN.format(n="pk"),
    # A freestanding Linux executable referencing a shared-only library.
    "sharedlib/SharedLib.asmproj": proj(),
    "sharedlib/lib.asm": GOOD_FN.format(n="lib_value"),
    "exeshared/App.asmproj": proj("<OutputType>Exe</OutputType>", '<ProjectReference Include="../sharedlib/SharedLib.asmproj" />'),
    "exeshared/main.asm": "default rel\nextern lib_value\nsection .text\nglobal _start:function\n_start:\n    call lib_value\n    mov eax, 231\n    syscall\n" + NOTE,
    # A reference to an Objects project: broken in 0.1.0 and 0.2.0, fixed in 0.3.0.
    "objs/Objs.asmproj": proj("<OutputType>Objects</OutputType>"),
    "objs/o.asm": GOOD_FN.format(n="objs_value"),
    "objref/App.asmproj": proj("<OutputType>Exe</OutputType>", '<ProjectReference Include="../objs/Objs.asmproj" />'),
    "objref/main.asm": "default rel\nextern objs_value\nsection .text\nglobal _start:function\n_start:\n    call objs_value\n    mov eax, 231\n    syscall\n" + NOTE,
    # Unquoted $ORIGIN without an OS condition.
    "rpath/Rpath.asmproj": proj(items='<LinkerArg Include="-rpath $ORIGIN" />'),
    "rpath/a.asm": GOOD_FN.format(n="r"),
    # Every PIC mistake in one Linux shared library, with another library's function and data.
    "pic/Pic.asmproj": proj(),
    "pic/pic.asm": ("extern memcpy, stdout\nsection .rodata\nmsg: db 'x', 0\ntable: dq t1\n"
                    "section .data.rel.ro\nptrs: dq t1\n"
                    "section .text\nglobal f:function\nf:\n    lea rax, [msg]\n    call memcpy\n"
                    "    mov rax, [rel stdout]\n    mov rax, msg\nt1:\n    ret\n" + NOTE),
    # Calls and data within one library need no PLT or GOT: 0.3.0 links -Bsymbolic.
    "bsym/Bsym.asmproj": proj(),
    "bsym/helper.asm": "default rel\nsection .text\nglobal helper2:function\nhelper2:\n    ret\nsection .data\nglobal counter:data 4\ncounter: dd 0\n" + NOTE,
    "bsym/main.asm": "default rel\nextern helper2, counter\nsection .text\nglobal f2:function\nf2:\n    call helper2\n    mov eax, [rel counter]\n    ret\n" + NOTE,
    # A visibility written after the size (NASM ignores it), so the helper stays exported.
    "latehidden/LateHidden.asmproj": proj(),
    "latehidden/helper.asm": "default rel\nsection .text\nglobal h3:function (h3.end - h3) hidden\nh3:\n    ret\n.end:\n" + NOTE,
    "latehidden/a.asm": "default rel\nextern h3\nsection .text\nglobal f3:function\nf3:\n    call h3\n    ret\n" + NOTE,
    # The correct order: visibility before the size.
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
    # A Linux libc executable calling a C library function the stub does not list.
    "libcexe/LibcExe.asmproj": proj("<OutputType>Exe</OutputType><TargetFramework>libc</TargetFramework>"),
    "libcexe/main.asm": "default rel\nextern strsignal, printf\nsection .text\nglobal main:function\nmain:\n    push rbx\n    call strsignal wrt ..plt\n    call printf wrt ..plt\n    pop rbx\n    ret\n" + NOTE,
    # The same with AsmLibcSymbol: must not error.
    "libcexe_ok/LibcExeOk.asmproj": proj("<OutputType>Exe</OutputType><TargetFramework>libc</TargetFramework>", '<AsmLibcSymbol Include="strsignal" />'),
    "libcexe_ok/main.asm": "default rel\nextern strsignal\nsection .text\nglobal main:function\nmain:\n    push rbx\n    call strsignal wrt ..plt\n    pop rbx\n    ret\n" + NOTE,
    # An executable without its entry symbol.
    "noentry/NoEntry.asmproj": proj("<OutputType>Exe</OutputType>"),
    "noentry/a.asm": GOOD_FN.format(n="not_start"),
    # ELF's directives in a source that also builds Windows and macOS: each format's NASM
    # output stops on what it does not know, and a plain global is no DLL export.
    "multios/MultiOs.asmproj": proj(rids="win-x64;linux-x64;osx-x64"),
    "multios/m.asm": "default rel\nextern memcpy\nsection .text\nglobal m_copy:function\nm_copy:\n    call memcpy wrt ..plt\n    ret\n" + NOTE,
    # The same written with asmsdk.inc: clean on every OS.
    "multios_ok/MultiOsOk.asmproj": proj("<TargetFramework>libc</TargetFramework>", rids="win-x64;linux-x64;osx-x64"),
    "multios_ok/m.asm": ('default rel\n%include "asmsdk.inc"\nextern memcpy\nsection .text\nFUNCTION m2_copy, 3\n'
                         "    sub rsp, SHADOW_SPACE + 8\n    call memcpy PLT\n    add rsp, SHADOW_SPACE + 8\n    RETURN\nENDFUNCTION\n"
                         "%ifdef LINUX\n" + NOTE + "%endif\n"),
    # Windows-only imports under %ifdef WINDOWS are not judged for the Linux build.
    "guardext/GuardExt.asmproj": proj("<OutputType>Exe</OutputType>", rids="win-x64;linux-x64"),
    "guardext/main.asm": ('default rel\n%include "asmsdk.inc"\nsection .text\n%ifdef WINDOWS\nextern ExitProcess\nFUNCTION _start\n'
                          "    sub rsp, 40\n    xor ecx, ecx\n    call ExitProcess\nENDFUNCTION\n%else\nFUNCTION _start\n"
                          "    mov eax, 231\n    xor edi, edi\n    syscall\nENDFUNCTION\n%endif\n%ifdef LINUX\n" + NOTE + "%endif\n"),
    # A project that names no RID: built alone it stops with ASM0010, and every RID is
    # assumed, so ELF-only directives are warnings ("if built for macOS").
    "norids/NoRids.asmproj": proj(rids=None),
    "norids/a.asm": GOOD_FN.format(n="norids_fn"),
    # A RID-less static library takes the RIDs of the project that references it.
    "inherit/lib/Lib.asmproj": proj("<OutputType>StaticLibrary</OutputType>", rids=None),
    "inherit/lib/lib.asm": GOOD_FN.format(n="inherit_fn"),
    "inherit/app/App.asmproj": proj(items='<ProjectReference Include="../lib/Lib.asmproj" />'),
    "inherit/app/app.asm": GOOD_FN.format(n="inherit_app_fn"),
    # A RID AsmSdk does not build (ASM0011).
    "badrid/BadRid.asmproj": proj(rids="linux-x86"),
    "badrid/a.asm": PORTABLE_FN.format(n="badrid_fn"),
    # A freestanding program for macOS (ASM0015).
    "macexe/MacExe.asmproj": proj("<OutputType>Exe</OutputType>", rids="osx-arm64"),
    "macexe/main.s": "// a GNU-syntax source, so the RID has one\n",
    # A .NET target framework instead of AsmSdk's (ASM0003).
    "badfw/BadFw.asmproj": proj("<TargetFramework>netstandard2.0</TargetFramework>"),
    "badfw/a.asm": GOOD_FN.format(n="badfw_fn"),
    # A NASM file qualified for ARM64 only (ASM0021), and so no source for linux-x64 (ASM0023).
    "armnasm/ArmNasm.asmproj": proj(),
    "armnasm/k.arm64.asm": "default rel\nsection .text\n    ret\n",
    # Two files equally specific for linux-x64 (ASM0020).
    "tie/Tie.asmproj": proj(),
    "tie/a.linux.asm": GOOD_FN.format(n="tie_fn"),
    "tie/a.linux.s": "// GNU syntax, qualified for every Linux RID too\n",
    # NASM only, but an ARM64 RID listed (ASM0023).
    "armmissing/ArmMissing.asmproj": proj(rids="linux-x64;linux-arm64"),
    "armmissing/a.asm": GOOD_FN.format(n="armmissing_fn"),
    # Internals written once per OS: hidden on Linux, private_extern on macOS, a plain global
    # on Windows (where a DLL exports only what it is told to). Nothing to report.
    "visinternal/VisInternal.asmproj": proj(rids="win-x64;linux-x64;osx-x64"),
    "visinternal/v.asm": ('%include "asmsdk.inc"\ndefault rel\nsection .data\n%ifdef LINUX\nglobal vi_seed:data hidden 8\n'
                          "%elifdef MACOS\nglobal vi_seed:private_extern\n%else\nglobal vi_seed\n%endif\nvi_seed: dq 1\n"
                          "section .text\nHIDDEN_FUNCTION vi_mix, 1\n    mov rax, [rel vi_seed]\n    RETURN\nENDFUNCTION\n"
                          "FUNCTION vi_api, 1\n    sub rsp, SHADOW_SPACE + 8\n    call vi_mix\n    add rsp, SHADOW_SPACE + 8\n"
                          "    RETURN\nENDFUNCTION\n%ifdef LINUX\n" + NOTE + "%endif\n"),
    # The same ported halfway: hidden on Linux only, so libVisMixed.dylib exports both
    # internals (ASMSRC022); on Windows they are internal already, so no ASMSRC021.
    "vismixed/VisMixed.asmproj": proj(rids="win-x64;linux-x64;osx-x64"),
    "vismixed/v.asm": ("default rel\nsection .data\n%ifdef LINUX\nglobal vm_seed:data hidden 8\n%else\nglobal vm_seed\n%endif\n"
                       "vm_seed: dq 1\nsection .text\n%ifdef LINUX\nglobal vm_mix:function hidden\n%else\nglobal vm_mix\n%endif\n"
                       "vm_mix:\n    mov rax, rdi\n    ret\n%ifdef LINUX\n" + NOTE + "%endif\n"),
    # 'data 8 hidden' under a Linux guard: the declaration is not the last one of the name, and
    # is still checked (ASMSRC013); the attempt to hide it keeps ASMSRC021 quiet on Windows.
    "guardedlate/GuardedLate.asmproj": proj(rids="win-x64;linux-x64"),
    "guardedlate/g.asm": ("default rel\nsection .data\n%ifdef LINUX\nglobal gl_seed:data 8 hidden\n%else\nglobal gl_seed\n%endif\n"
                          "gl_seed: dq 1\n%ifdef LINUX\n" + NOTE + "%endif\n"),
    # Exported data that the DLL does not export: the fix is an ExportsFile, not FUNCTION.
    "dataexport/DataExport.asmproj": proj(rids="win-x64;linux-x64"),
    "dataexport/d.asm": ("default rel\nsection .data\n%ifdef LINUX\nglobal de_table:data 8\n%else\nglobal de_table\n%endif\n"
                         "de_table: dq 1\n%ifdef LINUX\n" + NOTE + "%endif\n"),
    # A solution entry without the type GUID.
    "Bad.slnx": '<Solution>\n  <Project Path="good/Good.asmproj" />\n</Solution>\n',
}

#: Expected error- and warning-level codes per fixture path (info findings are not asserted:
#: they are recommendations whose presence depends on the project's settings).
EXPECTED: Dict[str, Set[str]] = {
    "good/Good.asmproj": set(),
    "defines/Defines.asmproj": set(),
    "oldnames/OldNames.asmproj": {"ASMPRJ013"},
    "removed030/Removed030.asmproj": {"ASMPRJ013"},
    "ambig/native/Native.asmproj": {"ASMPRJ014"},
    "ambig_ok/native/Native.asmproj": set(),
    "fsref/app/App.asmproj": {"ASMREF003"},
    "extinc/ExtInc.asmproj": {"ASMPRJ002"},
    "extinc_ok/ExtIncOk.asmproj": set(),
    "dup/Dup.asmproj": {"ASMSRC010"},
    "dupsrc/DupSrc.asmproj": {"ASMSRC017"},
    "pack/Pack.asmproj": {"ASMPRJ003"},
    "exeshared/App.asmproj": {"ASMREF001"},
    "objref/App.asmproj": set(),
    "rpath/Rpath.asmproj": {"ASMPRJ006"},
    "pic/Pic.asmproj": {"ASMPIC001", "ASMPIC002", "ASMPIC003", "ASMPIC004", "ASMPIC005", "ASMSRC005"},
    "bsym/Bsym.asmproj": set(),
    "latehidden/LateHidden.asmproj": {"ASMSRC013"},
    "earlyhidden/EarlyHidden.asmproj": set(),
    "kw/Kw.asmproj": {"ASMSRC008"},
    "subinc/SubInc.asmproj": {"ASMSRC009"},
    "libcexe/LibcExe.asmproj": {"ASMSRC012"},
    "libcexe_ok/LibcExeOk.asmproj": set(),
    "noentry/NoEntry.asmproj": {"ASMSRC011"},
    "multios/MultiOs.asmproj": {"ASMSRC018", "ASMSRC019", "ASMSRC020", "ASMSRC021"},
    "multios_ok/MultiOsOk.asmproj": set(),
    "guardext/GuardExt.asmproj": set(),
    "norids/NoRids.asmproj": {"ASMPRJ015", "ASMSRC018", "ASMSRC019", "ASMSRC021"},
    "inherit": set(),
    "badrid/BadRid.asmproj": {"ASMPRJ016"},
    "macexe/MacExe.asmproj": {"ASMPRJ017"},
    "badfw/BadFw.asmproj": {"ASMPRJ018"},
    "armnasm/ArmNasm.asmproj": {"ASMSRC014", "ASMSRC016"},
    "tie/Tie.asmproj": {"ASMSRC015"},
    "armmissing/ArmMissing.asmproj": {"ASMSRC016"},
    "visinternal/VisInternal.asmproj": set(),
    "vismixed/VisMixed.asmproj": {"ASMSRC022"},
    "guardedlate/GuardedLate.asmproj": {"ASMSRC013"},
    "dataexport/DataExport.asmproj": {"ASMSRC021"},
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


@contextlib.contextmanager
def nuget_packages(folder: Optional[str]):
    """Point NUGET_PACKAGES at a folder for the duration of a test (None hides the real cache).

    The linter reads the SDK's macOS and Windows C library lists from the NuGet cache, so the
    fixture tests must not depend on what this machine has restored.

    Args:
        folder: The folder to use, or None for an empty one.

    Yields:
        Nothing; the previous value is restored afterwards.
    """
    previous = os.environ.get("NUGET_PACKAGES")
    with tempfile.TemporaryDirectory() as empty:
        os.environ["NUGET_PACKAGES"] = folder or empty
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("NUGET_PACKAGES", None)
            else:
                os.environ["NUGET_PACKAGES"] = previous


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
        with nuget_packages(None):
            for rel, expected in EXPECTED.items():
                with self.subTest(fixture=rel):
                    code, findings = run_json(check_asmproj, [os.path.join(self.tmp.name, rel)])
                    own = [f for f in findings if f["severity"] in ("error", "warning")]
                    self.assertEqual(expected, {f["code"] for f in own}, json.dumps(own, indent=1))
                    has_error = any(f["severity"] == "error" for f in own)
                    self.assertEqual(1 if has_error else 0, code)

    def test_platform_findings_name_the_platform(self) -> None:
        """A directive one format rejects is reported for that format, as an error when the RIDs are declared."""
        with nuget_packages(None):
            _, findings = run_json(check_asmproj, [os.path.join(self.tmp.name, "multios", "MultiOs.asmproj")])
        by_code = {f["code"]: f for f in findings}
        self.assertEqual("error", by_code["ASMSRC019"]["severity"])
        self.assertIn("macOS (macho64)", by_code["ASMSRC019"]["message"])
        self.assertIn("Windows (win64) and macOS (macho64)", by_code["ASMSRC020"]["message"])
        self.assertIn("ExportsFile", by_code["ASMSRC021"]["message"])

    def test_visibility_across_oses(self) -> None:
        """A symbol hidden on Linux but not on macOS is reported for macOS, with each kind's own fix.

        The fixes matter as much as the finding: FUNCTION would export an internal symbol on
        every OS, and no macro covers data, so neither may be suggested where it is wrong.
        """
        with nuget_packages(None):
            _, mixed = run_json(check_asmproj, [os.path.join(self.tmp.name, "vismixed", "VisMixed.asmproj")])
            _, data = run_json(check_asmproj, [os.path.join(self.tmp.name, "dataexport", "DataExport.asmproj")])
        found = {f["message"].split("'")[1]: f for f in mixed if f["code"] == "ASMSRC022"}
        self.assertEqual({"vm_seed", "vm_mix"}, set(found))
        self.assertIn("internal on Linux (elf64) but exported on macOS (macho64)", found["vm_mix"]["message"])
        self.assertIn("global vm_seed:private_extern", found["vm_seed"]["fix"])
        self.assertNotIn("HIDDEN_FUNCTION", found["vm_seed"]["fix"])
        self.assertIn("HIDDEN_FUNCTION vm_mix", found["vm_mix"]["fix"])
        export = next(f for f in data if f["code"] == "ASMSRC021")
        self.assertIn("ExportsFile", export["fix"])
        self.assertNotIn("FUNCTION de_table", export["fix"])

    def test_assumed_rids_downgrade_platform_findings(self) -> None:
        """Without RIDs (none declared, nothing references the project) platform findings are warnings."""
        with nuget_packages(None):
            _, findings = run_json(check_asmproj, [os.path.join(self.tmp.name, "norids", "NoRids.asmproj")])
        platform = [f for f in findings if f["code"] in ("ASMSRC018", "ASMSRC019")]
        self.assertTrue(platform)
        self.assertTrue(all(f["severity"] == "warning" for f in platform))

    def test_c_library_lists_from_the_sdk_package(self) -> None:
        """With the SDK package in the NuGet cache, each OS's C library list decides what links."""
        with tempfile.TemporaryDirectory() as tmp:
            stubs = os.path.join(tmp, "packages", "asmfoundation.sdk", "0.3.0", "stubs")
            write_tree(tmp, {
                "packages/asmfoundation.sdk/0.3.0/stubs/macos.symbols": "# macOS\nputs strlen\ndata __stdoutp 8\n",
                "packages/asmfoundation.sdk/0.3.0/stubs/ucrtbase.symbols": "puts\nstrlen\n",
                "packages/asmfoundation.sdk/0.3.0/stubs/kernel32.symbols": "ExitProcess\n",
                "w/global.json": '{ "msbuild-sdks": { "AsmFoundation.Sdk": "0.3.0" } }\n',
                "w/app/App.asmproj": proj("<OutputType>Exe</OutputType><TargetFramework>libc</TargetFramework>",
                                          rids="win-x64;linux-x64;osx-x64"),
                "w/app/main.asm": ('default rel\n%include "asmsdk.inc"\nextern puts, epoll_create\nsection .text\nFUNCTION main\n'
                                   "    sub rsp, SHADOW_SPACE + 8\n    call puts PLT\n    call epoll_create PLT\n"
                                   "    add rsp, SHADOW_SPACE + 8\n    RETURN\nENDFUNCTION\n"),
            })
            self.assertTrue(os.path.isdir(stubs))
            with nuget_packages(os.path.join(tmp, "packages")):
                code, findings = run_json(check_asmproj, [os.path.join(tmp, "w")])
        missing = [f for f in findings if f["code"] == "ASMSRC012"]
        # epoll_create is in Linux's list, not in macOS's or Windows'; puts is in all three.
        self.assertEqual(1, len(missing), json.dumps(findings, indent=1))
        self.assertIn("epoll_create", missing[0]["message"])
        self.assertIn("Windows (win64) and macOS (macho64)", missing[0]["message"])
        self.assertEqual(1, code)

    def test_source_selection_mirrors_the_sdk(self) -> None:
        """Qualifier scores, languages and ties follow the SDK's AsmSelectSources."""
        select = check_asmproj.select_sources
        files = ["/p/crc.asm", "/p/crc.linux.asm", "/p/crc.s", "/p/crc.win-arm64.s", "/p/io.unix.asm", "/p/io.asm"]
        self.assertEqual(["/p/crc.linux.asm", "/p/io.unix.asm"], [f.replace("\\", "/") for f in select(files, "linux-x64")[0]])
        self.assertEqual(["/p/crc.asm", "/p/io.asm"], [f.replace("\\", "/") for f in select(files, "win-x64")[0]])
        self.assertEqual(["/p/crc.s"], [f.replace("\\", "/") for f in select(files, "linux-arm64")[0]])
        self.assertEqual(["/p/crc.win-arm64.s"], [f.replace("\\", "/") for f in select(files, "win-arm64")[0]])
        _, ties = select(["/p/a.linux.asm", "/p/a.linux.s"], "linux-x64")
        self.assertEqual(1, len(ties))
        self.assertTrue(check_asmproj.qualifier_is_arm64_only("osx-arm64"))
        self.assertFalse(check_asmproj.qualifier_is_arm64_only("linux"))

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
    """Scaffolds are lint-clean on every RID, never overwrite, and register in the .slnx."""

    def test_every_kind_is_lint_clean(self) -> None:
        """All kinds and target frameworks, on their default RIDs, scaffold into one solution with no error or warning."""
        with tempfile.TemporaryDirectory() as tmp:
            cases = [["Lib", "--assembly-name", "fastmath"], ["Static", "--kind", "static", "--package-id", "Acme.S"],
                     ["App", "--kind", "exe"], ["LApp", "--kind", "exe", "--framework", "libc"],
                     ["LLib", "--framework", "libc", "--package-id", "Acme.L", "--version", "2.0.0"],
                     ["Objs", "--kind", "objects"]]
            for case in cases:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, new_asmproj.main([os.path.join(tmp, case[0])] + case[1:]
                                                         + ["--sln", os.path.join(tmp, "App.slnx"), "--root", tmp]))
            with nuget_packages(None):
                _, findings = run_json(check_asmproj, [tmp])
            bad = [f for f in findings if f["severity"] in ("error", "warning")]
            self.assertEqual([], bad)
            with open(os.path.join(tmp, "App.slnx"), encoding="utf-8") as f:
                slnx = f.read()
            self.assertEqual(6, slnx.count(new_asmproj.ASMPROJ_TYPE_GUID))
            with open(os.path.join(tmp, "global.json"), encoding="utf-8") as f:
                self.assertEqual("0.3.0", json.load(f)["msbuild-sdks"]["AsmFoundation.Sdk"])
            # Every RID by default: an x64 source and an ARM64 one per project.
            self.assertTrue(os.path.isfile(os.path.join(tmp, "Lib", "fastmath.asm")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "Lib", "fastmath.s")))
            with open(os.path.join(tmp, "App", "App.asmproj"), encoding="utf-8") as f:
                # A freestanding program cannot target macOS (ASM0015).
                self.assertIn("<RuntimeIdentifiers>win-x64;win-arm64;linux-x64;linux-arm64;linux-musl-x64</RuntimeIdentifiers>", f.read())

    def test_rids_option(self) -> None:
        """--rids sets the list in the SDK's order, and only the CPUs listed get a source."""
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, new_asmproj.main([os.path.join(tmp, "Lib"), "--rids", "linux-x64,win-x64", "--root", tmp]))
            with open(os.path.join(tmp, "Lib", "Lib.asmproj"), encoding="utf-8") as f:
                self.assertIn("<RuntimeIdentifiers>win-x64;linux-x64</RuntimeIdentifiers>", f.read())
            self.assertTrue(os.path.isfile(os.path.join(tmp, "Lib", "lib.asm")))
            self.assertFalse(os.path.isfile(os.path.join(tmp, "Lib", "lib.s")))

    def test_impossible_rids_are_refused(self) -> None:
        """An unknown RID, or a freestanding program for macOS, is a usage error (exit 2)."""
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(2, new_asmproj.main([os.path.join(tmp, "A"), "--rids", "linux-x86", "--root", tmp]))
                self.assertEqual(2, new_asmproj.main([os.path.join(tmp, "B"), "--kind", "exe", "--rids", "osx-arm64", "--root", tmp]))
            self.assertFalse(os.path.exists(os.path.join(tmp, "B", "B.asmproj")))

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
            self.assertEqual("0.3.0", data["msbuild-sdks"]["AsmFoundation.Sdk"])


#: llvm-readobj's text style for a PE DLL (abridged from a real AsmSdk win-x64 build).
PE_TEXT = """File: x.dll
Format: COFF-x86-64
Arch: x86_64
AddressSize: 64bit
ImageFileHeader {
  Machine: IMAGE_FILE_MACHINE_AMD64 (0x8664)
  Characteristics [ (0x2022)
    IMAGE_FILE_DLL (0x2000)
    IMAGE_FILE_EXECUTABLE_IMAGE (0x2)
  ]
}
ImageOptionalHeader {
  AddressOfEntryPoint: 0x0
  Characteristics [ (0x160)
    IMAGE_DLL_CHARACTERISTICS_DYNAMIC_BASE (0x40)
    IMAGE_DLL_CHARACTERISTICS_NX_COMPAT (0x100)
  ]
}
Export {
  Ordinal: 1
  Name: x_add
  RVA: 0x1000
}
Import {
  Name: ucrtbase.dll
  ImportLookupTableRVA: 0x20D8
  ImportAddressTableRVA: 0x2128
  Symbol: strlen (0)
}
"""

#: The same for a Mach-O dylib (an export, a private extern, an import).
MACHO_TEXT = """File: libx.dylib
Format: Mach-O 64-bit x86-64
Arch: x86_64
AddressSize: 64bit
MachHeader {
  Magic: Magic64 (0xFEEDFACF)
  FileType: DynamicLibrary (0x6)
  Flags [ (0x100085)
    MH_DYLDLINK (0x4)
    MH_NOUNDEFS (0x1)
  ]
}
NeededLibraries [
  /usr/lib/libSystem.B.dylib
  @rpath/libx.dylib
]
Symbols [
  Symbol {
    Name: _x_add (10)
    Extern
    Type: Section (0xE)
    Section: __text (0x1)
    RefType: UndefinedNonLazy (0x0)
    Flags [ (0x0)
    ]
    Value: 0x338
  }
  Symbol {
    Name: _x_helper (20)
    PrivateExtern
    Extern
    Type: Section (0xE)
    Section: __text (0x1)
    Flags [ (0x0)
    ]
    Value: 0x340
  }
  Symbol {
    Name: _strlen (30)
    Extern
    Type: Undef (0x0)
    Section:  (0x0)
    Flags [ (0x100)
      SymbolResolver (0x100)
    ]
    Value: 0x0
  }
]
"""

#: A COFF static library with one member: a defined function and an undefined reference.
COFF_ARCHIVE_TEXT = """File: lib.lib(a.o)
Format: COFF-x86-64
Arch: x86_64
AddressSize: 64bit
Symbols [
  Symbol {
    Name: .text
    Value: 0
    Section: .text (1)
    StorageClass: Static (0x3)
    AuxSymbolCount: 1
    AuxSectionDef {
      Length: 8
    }
  }
  Symbol {
    Name: a_fn
    Value: 0
    Section: .text (1)
    StorageClass: External (0x2)
    AuxSymbolCount: 0
  }
  Symbol {
    Name: memcpy
    Value: 0
    Section: IMAGE_SYM_UNDEFINED (0)
    StorageClass: External (0x2)
    AuxSymbolCount: 0
  }
]
"""


class InspectOutputTests(unittest.TestCase):
    """Summaries and expectations from llvm-readobj's output, without running llvm-readobj."""

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

    @staticmethod
    def expectations(**values) -> object:
        """An argparse namespace with every --expect-* option, unset unless given.

        Args:
            **values: The options to set (expect_type=..., expect_export=[...], ...).

        Returns:
            The namespace check_expectations reads.
        """
        defaults = dict(expect_type=None, expect_export=None, expect_needed=None, expect_no_needed=False,
                        expect_runpath=None, expect_nonexec_stack=False)
        defaults.update(values)
        return inspect_output.argparse.Namespace(**defaults)

    @contextlib.contextmanager
    def canned(self, text: str):
        """Make run_readobj_text return canned output, so no llvm-readobj is needed.

        Args:
            text: The output to return for every call.

        Yields:
            Nothing; the real function is restored afterwards.
        """
        real = inspect_output.run_readobj_text
        inspect_output.run_readobj_text = lambda readobj, path, options: text
        try:
            yield
        finally:
            inspect_output.run_readobj_text = real

    def test_summary(self) -> None:
        """Kind, SONAME, NEEDED, RUNPATH, stack, exports and imports come out of the ELF JSON."""
        s = inspect_output.summarize_elf("libx.so", self.DOC)
        self.assertEqual("shared", s["kind"])
        self.assertEqual("libx.so", s["soname"])
        self.assertEqual(["libc.so.6"], s["needed"])
        self.assertEqual(["$ORIGIN"], s["runpath"])
        self.assertIs(False, s["executable_stack"])
        self.assertEqual(["x_add"], [e["name"] for e in s["exports"]])
        self.assertEqual(["strlen"], s["imports"])

    def test_expectations(self) -> None:
        """Met expectations pass; a missing export and a wrong kind both fail."""
        s = inspect_output.summarize_elf("libx.so", self.DOC)
        ok = self.expectations(expect_type="shared", expect_export=["x_add"], expect_needed=["libc.so.6"],
                               expect_runpath="$ORIGIN", expect_nonexec_stack=True)
        self.assertEqual([], inspect_output.check_expectations(s, ok))
        bad = self.expectations(expect_type="pie", expect_export=["missing"], expect_no_needed=True)
        self.assertEqual(3, len(inspect_output.check_expectations(s, bad)))

    def test_pe_summary(self) -> None:
        """A DLL: its kind, DEP/ASLR flags, imported DLL and functions, and its exports."""
        with self.canned(PE_TEXT):
            s = inspect_output.summarize_pe("x.dll", "llvm-readobj")
        self.assertEqual(("PE", "dll"), (s["format"], s["kind"]))
        self.assertEqual(["ucrtbase.dll"], s["needed"])
        self.assertEqual(["strlen"], s["imports"])
        self.assertEqual(["x_add"], [e["name"] for e in s["exports"]])
        self.assertIn("NX_COMPAT", s["flags"])
        ok = self.expectations(expect_type="dll", expect_export=["x_add"], expect_needed=["UCRTBASE.DLL"], expect_nonexec_stack=True)
        self.assertEqual([], inspect_output.check_expectations(s, ok))
        self.assertEqual(1, len(inspect_output.check_expectations(s, self.expectations(expect_runpath="$ORIGIN"))))

    def test_macho_summary(self) -> None:
        """A dylib: install name apart from needed libraries, C names, private externs not exported."""
        with self.canned(MACHO_TEXT):
            s = inspect_output.summarize_macho("libx.dylib", "llvm-readobj")
        self.assertEqual(("MachO", "dylib"), (s["format"], s["kind"]))
        self.assertEqual("@rpath/libx.dylib", s["install_name"])
        self.assertEqual(["/usr/lib/libSystem.B.dylib"], s["needed"])
        self.assertEqual(["x_add"], [e["name"] for e in s["exports"]])
        self.assertEqual(["strlen"], s["imports"])
        self.assertEqual([], inspect_output.check_expectations(s, self.expectations(expect_type="dylib", expect_export=["x_add"])))

    def test_coff_archive_summary(self) -> None:
        """A .lib: each member's defined globals and references."""
        with self.canned(COFF_ARCHIVE_TEXT):
            s = inspect_output.summarize_text_archive("lib.lib", "llvm-readobj", "COFF")
        self.assertEqual("archive", s["kind"])
        self.assertEqual([{"member": "a.o", "defines": ["a_fn"], "references": ["memcpy"]}], s["members"])

    def test_file_format(self) -> None:
        """The Format line decides the reader: ELF, COFF or Mach-O."""
        for text, expected in (("Format: elf64-x86-64\n", "ELF"), ("Format: COFF-ARM64\n", "COFF"),
                               ("Format: Mach-O arm64\n", "MachO")):
            with self.canned(text):
                self.assertEqual(expected, inspect_output.file_format("llvm-readobj", "x"))


if __name__ == "__main__":
    unittest.main()
