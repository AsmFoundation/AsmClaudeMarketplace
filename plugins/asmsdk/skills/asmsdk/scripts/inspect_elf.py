#!/usr/bin/env python3
"""Summarize an AsmSdk output (ELF shared object, executable, object file or static archive).

Why this exists: whether a build "worked" is decided by facts inside the ELF file - its type,
SONAME, DT_NEEDED entries, interpreter, RUNPATH, exported and imported symbols, and whether the
stack is executable - not by the build's exit code. Reading those facts by eye from raw
`llvm-readobj` output is slow and error-prone, so this script runs `llvm-readobj` in its JSON
mode and prints one compact summary, or checks expectations and exits 1 when one fails (for CI
and for verifying a fix).

It needs `llvm-readobj`. The AsmSdk bundled toolchain package already contains one, and the
script finds it in the NuGet global packages folder by itself; `--readobj` or PATH work too.
Only the Python standard library is used (Python 3.8+).

Usage:
    inspect_elf.py <file> [<file> ...] [--json] [--readobj PATH]
                   [--expect-type shared|pie|static|object|archive]
                   [--expect-export NAME ...] [--expect-needed LIB ...]
                   [--expect-no-needed] [--expect-runpath VALUE] [--expect-nonexec-stack]

Exit codes: 0 = summarized and every expectation held; 1 = an expectation failed;
2 = usage error, missing file, or llvm-readobj not found or failed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

#: Exit code for a failed expectation: distinct from tool/usage errors (2) so CI can tell
#: "the artifact is wrong" apart from "the check could not run".
EXIT_EXPECTATION_FAILED = 1

#: Exit code for usage errors, missing inputs and tool failures.
EXIT_TOOL_ERROR = 2


class InspectError(Exception):
    """Raised when an input cannot be inspected (missing file, no llvm-readobj, tool failure).

    The message is meant for the user verbatim; callers print it and exit with
    EXIT_TOOL_ERROR rather than showing a traceback.
    """


def _global_packages_folders() -> List[str]:
    """Return the NuGet global-packages folders to search for the bundled toolchain.

    NUGET_PACKAGES wins because restore uses it when set (CI caches usually set it); the
    per-user default comes second. Both are returned when both exist, because a machine can
    hold toolchains restored under either.

    Returns:
        Existing folder paths, most specific first; possibly empty.
    """
    candidates = []
    env = os.environ.get("NUGET_PACKAGES")
    if env:
        candidates.append(env)
    candidates.append(os.path.join(os.path.expanduser("~"), ".nuget", "packages"))
    return [c for c in candidates if os.path.isdir(c)]


def _version_key(path: str) -> List[Any]:
    """Sort key that orders toolchain version folders numerically (0.10.0 after 0.9.0).

    Args:
        path: A path whose parent-of-parent folder name is a version, as in
            .../asmfoundation.toolchain.win-x64/<version>/tools/llvm-readobj.exe.

    Returns:
        A list of ints and strings comparable across versions; non-numeric parts (pre-release
        labels) sort as strings so the result is deterministic rather than exact SemVer.
    """
    version = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return [int(p) if p.isdigit() else p for p in version.replace("-", ".").split(".")]


def find_readobj(explicit: Optional[str]) -> str:
    """Locate the llvm-readobj executable to use.

    Search order: the explicit path, the newest AsmFoundation.Toolchain package in the NuGet
    global packages folders (the same binary the SDK ships, so its output format is known),
    then PATH (llvm-readobj, then versioned names such as llvm-readobj-18 from Linux distros).

    Args:
        explicit: Path given with --readobj, or None.

    Returns:
        The path or command name of a runnable llvm-readobj.

    Raises:
        InspectError: The explicit path does not exist, or no llvm-readobj was found.
    """
    if explicit:
        if not os.path.isfile(explicit):
            raise InspectError(f"--readobj: no such file: {explicit}")
        return explicit
    exe = "llvm-readobj.exe" if os.name == "nt" else "llvm-readobj"
    found: List[str] = []
    for root in _global_packages_folders():
        # Package folders are lower-case on disk (NuGet normalizes ids), one per host RID.
        found.extend(glob.glob(os.path.join(root, "asmfoundation.toolchain.*", "*", "tools", exe)))
    if found:
        return sorted(found, key=_version_key)[-1]
    for name in ["llvm-readobj"] + [f"llvm-readobj-{v}" for v in range(30, 13, -1)]:
        path = shutil.which(name)
        if path:
            return path
    raise InspectError(
        "llvm-readobj not found. Restore an AsmSdk project once (dotnet restore downloads "
        "AsmFoundation.Toolchain.<rid>, which contains it), install LLVM, or pass --readobj PATH.")


def run_readobj(readobj: str, path: str) -> List[Dict[str, Any]]:
    """Run llvm-readobj in JSON mode on one file and return its parsed document.

    Args:
        readobj: Path or command of llvm-readobj (see find_readobj).
        path: The ELF file or archive to read.

    Returns:
        One dictionary per ELF member: a single entry for a .so/.o/executable, one per object
        member for a static archive.

    Raises:
        InspectError: The file is missing, llvm-readobj fails (for example on a non-ELF file),
            or its output is not JSON.
    """
    if not os.path.isfile(path):
        raise InspectError(f"no such file: {path}")
    cmd = [readobj, "--elf-output-style=JSON", "--file-headers", "--program-headers",
           "--dynamic-table", "--dyn-syms", "--symbols", "--notes", path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise InspectError(f"llvm-readobj failed on {path}: {(proc.stderr or proc.stdout).strip()}")
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise InspectError(f"llvm-readobj produced no JSON for {path}: {exc}") from exc
    # A single file yields a list with one entry; normalize a bare object to a list too.
    return doc if isinstance(doc, list) else [doc]


def _read_interpreter(path: str, program_headers: List[Dict[str, Any]]) -> Optional[str]:
    """Read the PT_INTERP string straight from the file.

    llvm-readobj's JSON lists PT_INTERP's offset and size but not the path itself, so the
    bytes are read directly; this is the dynamic loader a Libc executable asks for.

    Args:
        path: The ELF file.
        program_headers: The "ProgramHeaders" list from llvm-readobj's JSON.

    Returns:
        The interpreter path, or None when the file has no PT_INTERP (static executables and
        shared libraries).
    """
    for entry in program_headers:
        ph = entry.get("ProgramHeader", entry)
        if ph.get("Type", {}).get("Name") == "PT_INTERP":
            with open(path, "rb") as f:
                f.seek(int(ph["Offset"]))
                return f.read(int(ph["FileSize"])).rstrip(b"\0").decode("utf-8", "replace")
    return None


def _symbol_fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one llvm-readobj JSON symbol into the fields this script reports.

    Args:
        entry: One element of "DynamicSymbols" or "Symbols" ({"Symbol": {...}}).

    Returns:
        name, binding, type, size, defined (False for undefined imports) and visibility.
    """
    sym = entry.get("Symbol", entry)
    section = sym.get("Section", {})
    other = sym.get("Other", {})
    flags = [f.get("Name", "") for f in other.get("Flags", [])] if isinstance(other, dict) else []
    return {
        "name": sym.get("Name", {}).get("Name", ""),
        "binding": sym.get("Binding", {}).get("Name", ""),
        "type": sym.get("Type", {}).get("Name", ""),
        "size": sym.get("Size", 0),
        # Undefined symbols live in section "Undefined" (index 0): they are imports.
        "defined": section.get("Name") not in ("Undefined", None) and section.get("Value", 0) != 0,
        "visibility": "hidden" if "STV_HIDDEN" in flags else ("protected" if "STV_PROTECTED" in flags else "default"),
    }


def summarize_elf(path: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Turn llvm-readobj's JSON for one ELF file (not an archive) into the reported summary.

    Args:
        path: The file that was read (used to read the interpreter string).
        doc: The single document llvm-readobj produced for it.

    Returns:
        A dictionary with: file, kind (shared/pie/static/object), soname, needed, runpath,
        interpreter, entry, flags, executable_stack (True/False/None when no PT_GNU_STACK),
        textrel, build_id, exports (defined dynamic symbols) and imports (undefined dynamic
        symbols). For a relocatable object, exports/imports come from the static symbol table.
    """
    header = doc.get("ElfHeader", {})
    elf_type = str(header.get("Type", ""))
    dynamic = doc.get("DynamicSection", []) or []
    flags: List[str] = []
    for entry in dynamic:
        if entry.get("Type") in ("FLAGS", "FLAGS_1"):
            flags.extend(entry.get("Flags", []))
    # ET_DYN is both a shared library and a PIE; DF_1_PIE tells them apart.
    if elf_type.startswith("SharedObject"):
        kind = "pie" if "PIE" in flags else "shared"
    elif elf_type.startswith("Executable"):
        kind = "static"
    elif elf_type.startswith("Relocatable"):
        kind = "object"
    else:
        kind = elf_type or "unknown"

    def dyn_values(tag: str, key: str) -> List[str]:
        """Collect one dynamic tag's values (NEEDED -> library names, RUNPATH -> paths)."""
        values: List[str] = []
        for entry in dynamic:
            if entry.get("Type") == tag:
                value = entry.get(key, entry.get("Name", entry.get("Library")))
                values.extend(value if isinstance(value, list) else [value])
        return [str(v) for v in values if v is not None]

    stack = None
    for entry in doc.get("ProgramHeaders", []) or []:
        ph = entry.get("ProgramHeader", entry)
        if ph.get("Type", {}).get("Name") == "PT_GNU_STACK":
            stack = any(f.get("Name") == "PF_X" for f in ph.get("Flags", {}).get("Flags", []))
    build_id = None
    for section in doc.get("NoteSections", []) or []:
        for note in section.get("NoteSection", section).get("Notes", []):
            if "Build ID" in note:
                build_id = note["Build ID"]

    # Shared objects and PIEs export through the dynamic symbol table; a relocatable object
    # has none, so its static symbol table stands in (globals = what a link can resolve).
    table = doc.get("DynamicSymbols") if kind != "object" else doc.get("Symbols")
    symbols = [_symbol_fields(s) for s in (table or [])]
    symbols = [s for s in symbols if s["name"] and s["binding"] in ("Global", "Weak")]
    return {
        "file": path,
        "kind": kind,
        "soname": (dyn_values("SONAME", "Name") or [None])[0],
        "needed": dyn_values("NEEDED", "Library"),
        "runpath": dyn_values("RUNPATH", "Path") + dyn_values("RPATH", "Path"),
        "interpreter": _read_interpreter(path, doc.get("ProgramHeaders", []) or []),
        "entry": header.get("Entry"),
        "flags": sorted(set(flags)),
        "executable_stack": stack,
        "textrel": any(e.get("Type") == "TEXTREL" for e in dynamic) or "TEXTREL" in flags,
        "build_id": build_id,
        "exports": [{k: s[k] for k in ("name", "type", "size", "binding")} for s in symbols if s["defined"] and s["visibility"] == "default"],
        "imports": sorted({s["name"] for s in symbols if not s["defined"]}),
    }


def summarize_archive(path: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a static library: its members and the global symbols each defines.

    Args:
        path: The archive that was read.
        docs: llvm-readobj's JSON documents, one per member ("lib.a(member.o)").

    Returns:
        A dictionary with file, kind="archive", members (name, defined globals, undefined
        references) and exports (all defined global symbols, the names a linker can resolve).
    """
    members = []
    exports: List[str] = []
    for doc in docs:
        name = doc.get("FileSummary", {}).get("File", "")
        # "C:/x/libfoo.a(bar.o)" -> "bar.o"; keep the raw name when the format is unexpected.
        member = name[name.rfind("(") + 1:-1] if name.endswith(")") and "(" in name else name
        symbols = [_symbol_fields(s) for s in doc.get("Symbols", []) or []]
        defined = sorted(s["name"] for s in symbols if s["defined"] and s["binding"] in ("Global", "Weak") and s["name"])
        undefined = sorted(s["name"] for s in symbols if not s["defined"] and s["name"])
        members.append({"member": member, "defines": defined, "references": undefined})
        exports.extend(defined)
    return {"file": path, "kind": "archive", "members": members, "exports": sorted(set(exports))}


def inspect(path: str, readobj: str) -> Dict[str, Any]:
    """Inspect one file and return its summary (ELF file or static archive).

    Args:
        path: File to inspect.
        readobj: llvm-readobj to run.

    Returns:
        The summary dictionary (see summarize_elf / summarize_archive).

    Raises:
        InspectError: The file cannot be read or is not ELF.
    """
    docs = run_readobj(readobj, path)
    with open(path, "rb") as f:
        magic = f.read(8)
    # "!<arch>\n" is the ar magic: every member gets its own document.
    if magic.startswith(b"!<arch>"):
        return summarize_archive(path, docs)
    return summarize_elf(path, docs[0])


def format_text(summary: Dict[str, Any]) -> str:
    """Render one summary as the human-readable report.

    Args:
        summary: A dictionary from inspect().

    Returns:
        Multi-line text, one fact per line, with absent facts omitted rather than printed as
        "None" so the report stays short.
    """
    lines = [f"file: {summary['file']}"]
    if summary["kind"] == "archive":
        lines.append(f"kind: static archive, {len(summary['members'])} member(s)")
        for m in summary["members"]:
            lines.append(f"  {m['member']}: defines {', '.join(m['defines']) or '-'}"
                         + (f"; references {', '.join(m['references'])}" if m["references"] else ""))
        return "\n".join(lines)
    kinds = {"shared": "shared object (ET_DYN)", "pie": "position-independent executable (ET_DYN, PIE)",
             "static": "static executable (ET_EXEC)", "object": "relocatable object (ET_REL)"}
    lines.append(f"kind: {kinds.get(summary['kind'], summary['kind'])}")
    for key, label in (("soname", "SONAME"), ("interpreter", "interpreter")):
        if summary.get(key):
            lines.append(f"{label}: {summary[key]}")
    # A relocatable object has no dynamic section: printing "NEEDED: (none)" for it would
    # suggest a freestanding link result that does not exist yet.
    if summary["kind"] != "object":
        lines.append(f"NEEDED: {', '.join(summary['needed']) or '(none)'}")
    if summary["runpath"]:
        lines.append(f"RUNPATH: {', '.join(summary['runpath'])}")
    if summary["kind"] in ("pie", "static"):
        lines.append(f"entry: {hex(summary['entry']) if isinstance(summary['entry'], int) else summary['entry']}")
    if summary["flags"]:
        lines.append(f"dynamic flags: {' '.join(summary['flags'])}")
    if summary["executable_stack"] is not None:
        lines.append("stack: " + ("EXECUTABLE (PT_GNU_STACK has PF_X)" if summary["executable_stack"] else "non-executable"))
    if summary["textrel"]:
        lines.append("TEXTREL: yes (text relocations: the code is not position-independent)")
    if summary["build_id"]:
        lines.append(f"build id: {summary['build_id']}")
    exports = summary["exports"]
    lines.append(f"exports ({len(exports)}): " + (", ".join(
        f"{e['name']} [{e['type'] or 'None'}, {e['size']} B]" for e in exports) or "(none)"))
    lines.append(f"imports ({len(summary['imports'])}): {', '.join(summary['imports']) or '(none)'}")
    return "\n".join(lines)


def check_expectations(summary: Dict[str, Any], args: argparse.Namespace) -> List[str]:
    """Compare a summary with the --expect-* options.

    Args:
        summary: A dictionary from inspect().
        args: Parsed command-line options.

    Returns:
        One message per failed expectation; empty when all held. Expectations that do not
        apply to the file's kind (for example --expect-needed on an archive) fail with a
        message saying so, because a silently skipped check would read as a pass.
    """
    failures: List[str] = []
    name = summary["file"]
    if args.expect_type and summary["kind"] != args.expect_type:
        failures.append(f"{name}: expected kind {args.expect_type}, found {summary['kind']}")
    export_names = {e["name"] if isinstance(e, dict) else e for e in summary.get("exports", [])}
    for symbol in args.expect_export or []:
        if symbol not in export_names:
            failures.append(f"{name}: expected export '{symbol}' is missing")
    needed = summary.get("needed")
    for lib in args.expect_needed or []:
        if needed is None:
            failures.append(f"{name}: --expect-needed does not apply to a {summary['kind']}")
        elif lib not in needed:
            failures.append(f"{name}: expected NEEDED '{lib}', found {needed or '(none)'}")
    if args.expect_no_needed and needed:
        failures.append(f"{name}: expected no NEEDED entries, found {needed}")
    if args.expect_runpath is not None and args.expect_runpath not in (summary.get("runpath") or []):
        failures.append(f"{name}: expected RUNPATH '{args.expect_runpath}', found {summary.get('runpath') or '(none)'}")
    if args.expect_nonexec_stack and summary.get("executable_stack") is not False:
        failures.append(f"{name}: expected a non-executable stack, found {summary.get('executable_stack')}")
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; None means sys.argv[1:].

    Returns:
        The process exit code: 0, EXIT_EXPECTATION_FAILED or EXIT_TOOL_ERROR.
    """
    parser = argparse.ArgumentParser(description="Summarize AsmSdk ELF outputs and check expectations.")
    parser.add_argument("files", nargs="+", help="ELF files or static archives to inspect")
    parser.add_argument("--json", action="store_true", help="print the summaries as JSON")
    parser.add_argument("--readobj", help="path of llvm-readobj (default: bundled toolchain, then PATH)")
    parser.add_argument("--expect-type", choices=["shared", "pie", "static", "object", "archive"])
    parser.add_argument("--expect-export", action="append", metavar="NAME", help="a symbol that must be exported (repeatable)")
    parser.add_argument("--expect-needed", action="append", metavar="LIB", help="a DT_NEEDED entry that must exist (repeatable)")
    parser.add_argument("--expect-no-needed", action="store_true", help="no DT_NEEDED entries at all (freestanding)")
    parser.add_argument("--expect-runpath", metavar="VALUE", help="a RUNPATH entry that must exist, e.g. '$ORIGIN'")
    parser.add_argument("--expect-nonexec-stack", action="store_true", help="PT_GNU_STACK must not be executable")
    args = parser.parse_args(argv)
    try:
        readobj = find_readobj(args.readobj)
        summaries = [inspect(path, readobj) for path in args.files]
    except InspectError as exc:
        print(f"inspect_elf: {exc}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    failures = [f for s in summaries for f in check_expectations(s, args)]
    if args.json:
        print(json.dumps(summaries if len(summaries) > 1 else summaries[0], indent=2))
    else:
        print("\n\n".join(format_text(s) for s in summaries))
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return EXIT_EXPECTATION_FAILED if failures else 0


if __name__ == "__main__":
    sys.exit(main())
