#!/usr/bin/env python3
"""Summarize an AsmSdk output of any RID: ELF, PE/COFF or Mach-O, a library, program, object or archive.

Why this exists: whether a build "worked" is decided by facts inside the output file, not by
the build's exit code. For ELF (the Linux RIDs): its type, SONAME, DT_NEEDED entries,
interpreter, RUNPATH, exported and imported symbols, and whether the stack is executable. For
PE (the Windows RIDs): DLL or program, the exports a .drectve directive or ExportsFile gave
it, the DLLs and functions it imports, ASLR and DEP. For Mach-O (the macOS RIDs): dylib or
program, its install name and needed libraries, its exported and imported symbols (with
Mach-O's leading underscore removed, so names match the C names). Reading those facts by eye
from raw `llvm-readobj` output is slow and error-prone, so this script runs `llvm-readobj` (in
its JSON mode for ELF, which has one, and in its LLVM text mode for PE and Mach-O, which do
not) and prints one compact summary, or checks expectations and exits 1 when one fails (for CI
and for verifying a fix).

It needs `llvm-readobj`. The AsmSdk bundled toolchain package already contains one, and the
script finds it in the NuGet global packages folder by itself; `--readobj` or PATH work too.
Only the Python standard library is used (Python 3.8+).

Usage:
    inspect_output.py <file> [<file> ...] [--json] [--readobj PATH]
                      [--expect-type shared|pie|static|object|archive|dll|exe|dylib|executable]
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
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

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


def run_readobj_text(readobj: str, path: str, options: List[str]) -> str:
    """Run llvm-readobj in its default (LLVM) text style.

    llvm-readobj writes JSON for ELF only, so PE/COFF and Mach-O facts are read from the text
    style, whose block layout ("Export {", "Import {", "Symbol {", "Name: ...") is stable
    across LLVM releases.

    Args:
        readobj: Path or command of llvm-readobj (see find_readobj).
        path: The file to read.
        options: llvm-readobj options, such as --file-headers or --coff-exports.

    Returns:
        The tool's standard output.

    Raises:
        InspectError: The file is missing, or llvm-readobj fails on it.
    """
    if not os.path.isfile(path):
        raise InspectError(f"no such file: {path}")
    proc = subprocess.run([readobj, *options, path], capture_output=True, text=True)
    if proc.returncode != 0:
        raise InspectError(f"llvm-readobj failed on {path}: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def file_format(readobj: str, path: str) -> str:
    """The object format of a file, or of an archive's first member, as llvm-readobj names it.

    Args:
        readobj: llvm-readobj to run.
        path: The file.

    Returns:
        "ELF", "COFF" (PE images, COFF objects and .lib archives) or "MachO".

    Raises:
        InspectError: llvm-readobj failed, or the format is none of the three.
    """
    text = run_readobj_text(readobj, path, ["--file-headers"])
    match = re.search(r"^Format: (\S+)", text, re.M)
    name = match.group(1).lower() if match else ""
    if name.startswith("elf"):
        return "ELF"
    if name.startswith("coff"):
        return "COFF"
    if name.startswith("mach-o"):
        return "MachO"
    raise InspectError(f"{path}: not an ELF, PE/COFF or Mach-O file (llvm-readobj says '{name or 'nothing'}')")


def _c_name(symbol: str, fmt: str) -> str:
    """A symbol's C name: Mach-O adds a leading underscore to every C symbol, the others do not.

    Args:
        symbol: The name as the file spells it.
        fmt: "ELF", "COFF" or "MachO".

    Returns:
        The name a C declaration or --expect-export uses.
    """
    return symbol[1:] if fmt == "MachO" and symbol.startswith("_") else symbol


def _symbol_blocks(text: str) -> List[Dict[str, Any]]:
    """Parse llvm-readobj's text "Symbol { ... }" blocks (COFF and Mach-O) into dictionaries.

    Args:
        text: llvm-readobj --symbols output for one file or archive member.

    Returns:
        One dictionary per symbol: name; for COFF section and storage_class; for Mach-O
        type and extern / private_extern (each a line of its own in the block).
    """
    symbols: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "Symbol {" and current is None:
            current, depth = {"extern": False, "private_extern": False}, 1
            continue
        if current is None:
            continue
        # Nested blocks (AuxSymbol..., Flags [...]) open and close inside a symbol; only the
        # symbol's own top-level lines carry its name, section, class and type.
        if stripped.endswith("{") or stripped.endswith("["):
            depth += 1
            continue
        if stripped in ("}", "]"):
            depth -= 1
            if depth == 0:
                symbols.append(current)
                current = None
            continue
        if depth != 1:
            continue
        if stripped.startswith("Name: "):
            current["name"] = re.sub(r"\s*\(\d+\)$", "", stripped[6:].strip())
        elif stripped.startswith("Section: "):
            current["section"] = stripped[9:].strip()
        elif stripped.startswith("StorageClass: "):
            current["storage_class"] = stripped[14:].split(" ")[0]
        elif stripped.startswith("Type: "):
            current["type"] = stripped[6:].split(" ")[0]
        elif stripped == "Extern":
            current["extern"] = True
        elif stripped == "PrivateExtern":
            current["private_extern"] = True
    return symbols


def _object_symbols(text: str, fmt: str, include_private: bool = False) -> Tuple[List[str], List[str]]:
    """The global symbols a COFF or Mach-O object (or image) defines and references.

    Args:
        text: llvm-readobj --symbols output.
        fmt: "COFF" or "MachO".
        include_private: Count Mach-O private_extern symbols (HIDDEN_FUNCTION) as defined:
            true for objects and archives, whose private externs a static link still resolves;
            false for images, which export none of them.

    Returns:
        (defined, referenced): C names, sorted. COFF: storage class External, defined unless
        its section is IMAGE_SYM_UNDEFINED. Mach-O: Extern with a section is defined (unless
        PrivateExtern and not include_private), Extern with type Undef is referenced.
    """
    defined, referenced = set(), set()
    for sym in _symbol_blocks(text):
        name = sym.get("name")
        if not name:
            continue
        if fmt == "COFF":
            if sym.get("storage_class") != "External":
                continue
            (referenced if (sym.get("section") or "").startswith("IMAGE_SYM_UNDEFINED") else defined).add(name)
        else:
            if not sym["extern"]:
                continue
            if sym.get("type") == "Undef":
                referenced.add(_c_name(name, fmt))
            elif include_private or not sym["private_extern"]:
                defined.add(_c_name(name, fmt))
    return sorted(defined), sorted(referenced)


def _no_elf_facts() -> Dict[str, Any]:
    """The ELF-only keys of a summary, empty for PE and Mach-O, so every summary has every key.

    Returns:
        soname, runpath, interpreter, textrel and build_id with empty values.
    """
    return {"soname": None, "runpath": [], "interpreter": None, "textrel": False, "build_id": None}


def summarize_pe(path: str, readobj: str) -> Dict[str, Any]:
    """Summarize a Windows image (DLL or program) from llvm-readobj's text style.

    Args:
        path: The .dll or .exe.
        readobj: llvm-readobj to run.

    Returns:
        file, format "PE", arch, kind "dll" or "exe", entry (the RVA as text; 0x0 for a DLL
        without DllMain), flags (DllCharacteristics: DYNAMIC_BASE, HIGH_ENTROPY_VA,
        NX_COMPAT), needed (the imported DLLs), exports (what a .drectve directive or the
        ExportsFile listed), imports (the imported functions) and executable_stack (False
        with NX_COMPAT, so --expect-nonexec-stack means DEP), plus the ELF-only keys left empty.

    Raises:
        InspectError: llvm-readobj fails on the file.
    """
    text = run_readobj_text(readobj, path, ["--file-headers", "--coff-exports", "--coff-imports"])
    exports: List[str] = []
    needed: List[str] = []
    imports: Set[str] = set()
    state: Optional[str] = None
    new_import = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "Export {":
            state = "export"
            continue
        if stripped in ("Import {", "DelayImport {"):
            state, new_import = "import", True
            continue
        if stripped == "}":
            state = None
            continue
        if state == "export" and stripped.startswith("Name: "):
            exports.append(stripped[6:].strip())
        elif state == "import":
            # The block's first Name is the DLL; each Symbol line is one imported function.
            if stripped.startswith("Name: ") and new_import:
                needed.append(stripped[6:].strip())
                new_import = False
            elif stripped.startswith("Symbol: "):
                imports.add(re.sub(r"\s*\(\d+\)$", "", stripped[8:].strip()))
    arch = re.search(r"^Arch: (\S+)", text, re.M)
    entry = re.search(r"AddressOfEntryPoint: (0x[0-9A-Fa-f]+)", text)
    flags = sorted(set(re.findall(r"IMAGE_DLL_CHARACTERISTICS_(\w+)", text)))
    summary = {
        "file": path, "format": "PE", "arch": arch.group(1) if arch else None,
        "kind": "dll" if "IMAGE_FILE_DLL" in text else "exe",
        "entry": entry.group(1) if entry else None, "flags": flags, "needed": needed,
        "exports": [{"name": n, "type": None, "size": None, "binding": "Global"} for n in exports],
        "imports": sorted(imports), "executable_stack": "NX_COMPAT" not in flags,
    }
    summary.update(_no_elf_facts())
    return summary


def summarize_macho(path: str, readobj: str) -> Dict[str, Any]:
    """Summarize a macOS image (dylib or program) or object from llvm-readobj's text style.

    Args:
        path: The .dylib, program or .o.
        readobj: llvm-readobj to run.

    Returns:
        file, format "MachO", arch, kind ("dylib", "executable" or "object"), install_name
        (the dylib's own @rpath name, which llvm-readobj lists among the needed libraries),
        needed (the other libraries, such as /usr/lib/libSystem.B.dylib), flags (the MH_ header
        flags), exports and imports (C names: the leading underscore removed) and
        executable_stack (True only with MH_ALLOW_STACK_EXECUTION), plus the ELF-only keys.

    Raises:
        InspectError: llvm-readobj fails on the file.
    """
    text = run_readobj_text(readobj, path, ["--file-headers", "--needed-libs", "--symbols"])
    file_type = re.search(r"FileType: (\w+)", text)
    type_name = file_type.group(1) if file_type else ""
    kind = {"DynamicLibrary": "dylib", "Execute": "executable", "Relocatable": "object",
            "Object": "object"}.get(type_name, type_name.lower() or "unknown")
    libraries: List[str] = []
    in_needed = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("NeededLibraries ["):
            in_needed = True
            continue
        if in_needed:
            if stripped == "]":
                in_needed = False
            elif stripped:
                libraries.append(stripped)
    own = [lib for lib in libraries if lib.startswith("@rpath/") and os.path.basename(lib) == os.path.basename(path)]
    header = text.split("Symbols [", 1)[0]
    flags = sorted(set(re.findall(r"\b(MH_\w+)", header)))
    defined, referenced = _object_symbols(text, "MachO", include_private=(kind == "object"))
    arch = re.search(r"^Arch: (\S+)", text, re.M)
    summary = {
        "file": path, "format": "MachO", "arch": arch.group(1) if arch else None, "kind": kind,
        "install_name": own[0] if own else None, "needed": [lib for lib in libraries if lib not in own],
        "entry": None, "flags": flags,
        "exports": [{"name": n, "type": None, "size": None, "binding": "Global"} for n in defined],
        "imports": referenced, "executable_stack": "MH_ALLOW_STACK_EXECUTION" in flags,
    }
    summary.update(_no_elf_facts())
    return summary


def summarize_text_archive(path: str, readobj: str, fmt: str) -> Dict[str, Any]:
    """Summarize a COFF (.lib) or Mach-O static library: its members and their global symbols.

    Args:
        path: The archive.
        readobj: llvm-readobj to run.
        fmt: "COFF" or "MachO", the members' format.

    Returns:
        The same shape as summarize_archive: file, format, kind="archive", members (name,
        defined globals, referenced symbols) and exports (every defined global).

    Raises:
        InspectError: llvm-readobj fails on the file.
    """
    text = run_readobj_text(readobj, path, ["--symbols"])
    members = []
    exports: Set[str] = set()
    # One "File: lib.lib(member.o)" header per member, followed by its symbols.
    for chunk in re.split(r"^File: ", text, flags=re.M)[1:]:
        name = chunk.splitlines()[0].strip()
        member = name[name.rfind("(") + 1:-1] if name.endswith(")") and "(" in name else name
        defined, referenced = _object_symbols(chunk, fmt, include_private=True)
        members.append({"member": member, "defines": defined, "references": referenced})
        exports.update(defined)
    return {"file": path, "format": "PE" if fmt == "COFF" else fmt, "kind": "archive",
            "members": members, "exports": sorted(exports)}


def summarize_coff_object(path: str, readobj: str) -> Dict[str, Any]:
    """Summarize one COFF object (the .o of a Windows RID).

    Args:
        path: The object file.
        readobj: llvm-readobj to run.

    Returns:
        file, format "PE", kind "object", exports (defined globals), imports (referenced
        symbols), needed None (an object needs nothing yet), plus the ELF-only keys.

    Raises:
        InspectError: llvm-readobj fails on the file.
    """
    text = run_readobj_text(readobj, path, ["--file-headers", "--symbols"])
    defined, referenced = _object_symbols(text, "COFF")
    arch = re.search(r"^Arch: (\S+)", text, re.M)
    summary = {
        "file": path, "format": "PE", "arch": arch.group(1) if arch else None, "kind": "object",
        "entry": None, "flags": [], "needed": None,
        "exports": [{"name": n, "type": None, "size": None, "binding": "Global"} for n in defined],
        "imports": referenced, "executable_stack": None,
    }
    summary.update(_no_elf_facts())
    return summary


def inspect(path: str, readobj: str) -> Dict[str, Any]:
    """Inspect one file and return its summary, whatever its format.

    Args:
        path: File to inspect.
        readobj: llvm-readobj to run.

    Returns:
        The summary dictionary (see summarize_elf, summarize_archive, summarize_pe,
        summarize_macho, summarize_text_archive and summarize_coff_object); every summary
        has "format": "ELF", "PE" or "MachO".

    Raises:
        InspectError: The file cannot be read or is none of the three formats.
    """
    fmt = file_format(readobj, path)
    with open(path, "rb") as f:
        magic = f.read(8)
    # "!<arch>\n" is the ar magic: the static libraries of every OS, .a and .lib alike.
    archive = magic.startswith(b"!<arch>")
    if fmt == "ELF":
        docs = run_readobj(readobj, path)
        summary = summarize_archive(path, docs) if archive else summarize_elf(path, docs[0])
        summary["format"] = "ELF"
        return summary
    if archive:
        return summarize_text_archive(path, readobj, fmt)
    if fmt == "MachO":
        return summarize_macho(path, readobj)
    # A PE image starts with the MZ stub; a COFF object starts with its machine type.
    return summarize_pe(path, readobj) if magic.startswith(b"MZ") else summarize_coff_object(path, readobj)


def _format_pe_macho(summary: Dict[str, Any]) -> List[str]:
    """The report lines of a PE or Mach-O summary (after the "file:" line).

    Args:
        summary: A dictionary from summarize_pe, summarize_macho or summarize_coff_object.

    Returns:
        One fact per line; absent facts are omitted, as in the ELF report.
    """
    kinds = {"dll": "DLL (PE)", "exe": "program (PE)", "dylib": "dynamic library (Mach-O)",
             "executable": "program (Mach-O)"}
    fmt = "COFF" if summary["format"] == "PE" else "Mach-O"
    lines = [f"kind: {kinds.get(summary['kind'], summary['kind'] + ' (' + fmt + ')')}"]
    if summary.get("arch"):
        lines.append(f"arch: {summary['arch']}")
    if summary.get("install_name"):
        lines.append(f"install name: {summary['install_name']}")
    if summary["kind"] != "object":
        label = "imported DLLs" if summary["format"] == "PE" else "needed libraries"
        lines.append(f"{label}: {', '.join(summary['needed']) or '(none)'}")
    if summary.get("entry") and summary["kind"] == "exe":
        lines.append(f"entry: {summary['entry']}")
    if summary.get("flags"):
        lines.append(("DllCharacteristics: " if summary["format"] == "PE" else "header flags: ") + " ".join(summary["flags"]))
    exports = summary["exports"]
    lines.append(f"exports ({len(exports)}): " + (", ".join(e["name"] for e in exports) or "(none)"))
    lines.append(f"imports ({len(summary['imports'])}): {', '.join(summary['imports']) or '(none)'}")
    return lines


def format_text(summary: Dict[str, Any]) -> str:
    """Render one summary as the human-readable report.

    Args:
        summary: A dictionary from inspect().

    Returns:
        Multi-line text, one fact per line, with absent facts omitted rather than printed as
        "None" so the report stays short.
    """
    lines = [f"file: {summary['file']}"]
    fmt = summary.get("format", "ELF")
    if summary["kind"] == "archive":
        lines.append(f"kind: static archive ({fmt}), {len(summary['members'])} member(s)")
        for m in summary["members"]:
            lines.append(f"  {m['member']}: defines {', '.join(m['defines']) or '-'}"
                         + (f"; references {', '.join(m['references'])}" if m["references"] else ""))
        return "\n".join(lines)
    if fmt in ("PE", "MachO"):
        return "\n".join(lines + _format_pe_macho(summary))
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
    # Windows compares DLL names without case (KERNEL32.dll, kernel32.dll).
    fold = (lambda x: x.lower()) if summary.get("format") == "PE" else (lambda x: x)
    for lib in args.expect_needed or []:
        if needed is None:
            failures.append(f"{name}: --expect-needed does not apply to a {summary['kind']}")
        elif fold(lib) not in {fold(n) for n in needed}:
            failures.append(f"{name}: expected needed library '{lib}', found {needed or '(none)'}")
    if args.expect_no_needed and needed:
        failures.append(f"{name}: expected no NEEDED entries, found {needed}")
    if args.expect_runpath is not None and summary.get("format", "ELF") != "ELF":
        failures.append(f"{name}: --expect-runpath applies to ELF only, not {summary.get('format')}")
    elif args.expect_runpath is not None and args.expect_runpath not in (summary.get("runpath") or []):
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
    parser = argparse.ArgumentParser(description="Summarize AsmSdk outputs (ELF, PE, Mach-O) and check expectations.")
    parser.add_argument("files", nargs="+", help="libraries, programs, objects or static archives of any RID")
    parser.add_argument("--json", action="store_true", help="print the summaries as JSON")
    parser.add_argument("--readobj", help="path of llvm-readobj (default: bundled toolchain, then PATH)")
    parser.add_argument("--expect-type", choices=["shared", "pie", "static", "object", "archive", "dll", "exe", "dylib", "executable"],
                        help="ELF: shared, pie, static; PE: dll, exe; Mach-O: dylib, executable; any: object, archive")
    parser.add_argument("--expect-export", action="append", metavar="NAME", help="a symbol that must be exported, by its C name (repeatable)")
    parser.add_argument("--expect-needed", action="append", metavar="LIB",
                        help="a needed library: ELF DT_NEEDED, PE imported DLL, Mach-O dylib (repeatable)")
    parser.add_argument("--expect-no-needed", action="store_true", help="no needed libraries at all (a Linux freestanding output)")
    parser.add_argument("--expect-runpath", metavar="VALUE", help="a RUNPATH entry that must exist, e.g. '$ORIGIN'")
    parser.add_argument("--expect-nonexec-stack", action="store_true",
                        help="ELF: PT_GNU_STACK without PF_X; PE: NX_COMPAT (DEP); Mach-O: no MH_ALLOW_STACK_EXECUTION")
    args = parser.parse_args(argv)
    try:
        readobj = find_readobj(args.readobj)
        summaries = [inspect(path, readobj) for path in args.files]
    except InspectError as exc:
        print(f"inspect_output: {exc}", file=sys.stderr)
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
