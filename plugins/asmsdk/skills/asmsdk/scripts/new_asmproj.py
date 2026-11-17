#!/usr/bin/env python3
"""Scaffold an AsmSdk (.asmproj) project that builds on the first `dotnet build`.

Why this exists: a working asm project needs several pieces that are easy to get subtly wrong
by hand - global.json's msbuild-sdks entry, the .slnx type GUID, a public include/ folder (or
packages ship no include files), `default rel`, `wrt ..plt`, symbol types and sizes, the
.note.GNU-stack section, a 16-byte aligned stack before libc calls. This script writes all of
them consistently for the chosen output kind and runtime.

Safety: it never overwrites an existing file. Existing files are reported as "kept". The only
files it edits in place are global.json (adding the msbuild-sdks entry when missing) and the
.slnx named with --sln (adding the project when it is not listed); both edits are additive.

Usage:
    new_asmproj.py <project-dir> [--name NAME] [--kind library|static|exe|objects]
                   [--runtime freestanding|libc] [--lib-name NAME] [--sln PATH.slnx]
                   [--package-id ID] [--version 1.0.0] [--sdk-version 0.1.0] [--root DIR]

Exit codes: 0 = done (some files may have been kept); 2 = usage error or a file could not be
written or parsed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

#: SDK version the skill documents; global.json gets it unless --sdk-version says otherwise.
DEFAULT_SDK_VERSION = "0.1.0"

#: The generic MSBuild ("Common Project System") project type. An .asmproj entry in a .slnx
#: without it fails with "MSB4025 ... ProjectType '' not found".
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: Output kinds accepted by --kind, mapped to the csproj-style OutputType the SDK reads.
KIND_TO_OUTPUT_TYPE = {"library": "Library", "static": "StaticLibrary", "exe": "Exe", "objects": "Objects"}

NOTE_GNU_STACK = "section .note.GNU-stack noalloc noexec nowrite progbits\n"


class ScaffoldError(Exception):
    """Raised for inputs the script cannot act on (bad names, unparsable global.json or .slnx).

    The message is shown to the user as is; main() turns it into exit code 2.
    """


def symbol_prefix(lib_name: str) -> str:
    """Derive the NASM symbol prefix from a library name ("hello-utils" -> "hello_utils").

    NASM has one global namespace per link, so every exported symbol gets the library's
    prefix; characters NASM does not accept in identifiers become underscores.

    Args:
        lib_name: The library base name (AsmLibraryName).

    Returns:
        A lower-case identifier that starts with a letter or underscore.
    """
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", lib_name).lower()
    return prefix if re.match(r"[A-Za-z_]", prefix) else "_" + prefix


def asmproj_text(kind: str, runtime: str, lib_name: Optional[str], package_id: Optional[str], version: Optional[str]) -> str:
    """Build the .asmproj XML for the requested kind, runtime and packaging.

    Only properties that differ from the SDK defaults are written, so the file shows the
    project's real decisions; comments say what each produces.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        runtime: "freestanding" or "libc".
        lib_name: AsmLibraryName, or None to keep the default (the project name).
        package_id: PackageId for dotnet pack, or None for a project that is not packed.
        version: Package version; used only with package_id.

    Returns:
        The project file's text.
    """
    props: List[str] = []
    if kind != "library":
        props.append(f"    <OutputType>{KIND_TO_OUTPUT_TYPE[kind]}</OutputType>")
    if runtime == "libc":
        props.append("    <AsmRuntime>Libc</AsmRuntime>   <!-- glibc 2.34+ at run time; DT_NEEDED libc.so.6 -->")
    if lib_name:
        output = {"library": f"lib{lib_name}.so", "static": f"lib{lib_name}.a", "exe": lib_name, "objects": "objects only"}[kind]
        props.append(f"    <AsmLibraryName>{lib_name}</AsmLibraryName>   <!-- bin/<Configuration>/{output} -->")
    if package_id and kind == "library":
        # A packed shared library also ships a .a, so asm consumers (and freestanding
        # executables, which link -static) can link it without a run-time dependency.
        props.append("    <AsmProduceStaticLibrary>true</AsmProduceStaticLibrary>")
    if package_id:
        props.append(f"    <PackageId>{package_id}</PackageId>")
        props.append(f"    <Version>{version or '1.0.0'}</Version>")
    body = "\n".join(props) if props else "    <!-- Library (lib<project>.so), Freestanding: the SDK defaults. -->"
    return f'<Project Sdk="AsmFoundation.Sdk">\n  <PropertyGroup>\n{body}\n  </PropertyGroup>\n</Project>\n'


def include_text(prefix: str, function: str) -> str:
    """Build the public include file: guard, extern declaration and a version constant.

    Args:
        prefix: Symbol prefix (see symbol_prefix).
        function: The exported function's full symbol name.

    Returns:
        The .inc file's text.
    """
    guard = prefix.upper() + "_INC"
    return (f"; {prefix}.inc - public interface: included by referencing projects and package consumers.\n"
            f"%ifndef {guard}\n%define {guard}\n\n"
            f"%define {prefix.upper()}_VERSION 0x00010000   ; major << 16 | minor\n\n"
            f"extern {function}\n\n%endif\n")


def source_text(kind: str, runtime: str, prefix: str) -> Tuple[str, str]:
    """Build the starter source for the kind and runtime, following every linking rule.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        runtime: "freestanding" or "libc".
        prefix: Symbol prefix (see symbol_prefix).

    Returns:
        (file name, text). Libraries export one function with type and size; executables
        start at _start (freestanding) or main (libc).
    """
    if kind == "exe" and runtime == "libc":
        return "main.asm", (
            "; main.asm - int main(int argc, char **argv) on glibc; started by the SDK's crt1.\n"
            "default rel\n\nextern printf\n\nsection .rodata\n"
            "format: db \"hello from assembly: %d argument(s)\", 10, 0\n\n"
            "section .text\n\nglobal main:function (main.end - main)\nmain:\n"
            "    push    rbx                     ; entered at rsp = 16k+8: one push aligns the calls\n"
            "    mov     esi, edi                ; printf's 2nd argument: argc\n"
            "    lea     rdi, [format]\n"
            "    xor     eax, eax                ; variadic call: al = vector registers used\n"
            "    call    printf wrt ..plt\n"
            "    xor     eax, eax                ; return 0; __libc_start_main passes it to exit()\n"
            "    pop     rbx\n    ret\n.end:\n\n" + NOTE_GNU_STACK)
    if kind == "exe":
        return "main.asm", (
            "; main.asm - a freestanding Linux x86-64 program: raw system calls, no libc.\n"
            "default rel\n\n%define SYS_WRITE 1\n%define SYS_EXIT_GROUP 231\n\n"
            "section .rodata\nmessage: db \"hello from assembly\", 10\nmessage_len equ $ - message\n\n"
            "section .text\n\n; _start: the kernel jumps here (rsp -> argc, argv..., envp...). Never returns.\n"
            "global _start:function\n_start:\n"
            "    mov     eax, SYS_WRITE\n    mov     edi, 1                  ; stdout\n"
            "    lea     rsi, [message]\n    mov     edx, message_len\n    syscall\n"
            "    mov     eax, SYS_EXIT_GROUP\n    xor     edi, edi                ; status 0\n    syscall\n\n"
            + NOTE_GNU_STACK)
    function = f"{prefix}_add"
    if runtime == "libc":
        return f"{prefix}.asm", (
            f"; {prefix}.asm - size_t {prefix}_length(const char *s): strlen through glibc's PLT.\n"
            f"default rel\n\n%include \"{prefix}.inc\"\n\nextern strlen\n\nsection .text\n\n"
            f"; int {function}(int a, int b)\nglobal {function}:function ({function}.end - {function})\n{function}:\n"
            f"    lea     eax, [rdi + rsi]\n    ret\n.end:\n\n"
            f"; size_t {prefix}_length(const char *s)\nglobal {prefix}_length:function ({prefix}_length.end - {prefix}_length)\n"
            f"{prefix}_length:\n    push    rbx                     ; align the stack to 16 for the call\n"
            f"    call    strlen wrt ..plt        ; a shared library must call libc through the PLT\n"
            f"    pop     rbx\n    ret\n.end:\n\n" + NOTE_GNU_STACK)
    return f"{prefix}.asm", (
        f"; {prefix}.asm - position-independent, so it links into a .so, a PIE or a static program.\n"
        f"default rel\n\n%include \"{prefix}.inc\"\n\nsection .text\n\n"
        f"; int {function}(int a, int b) - System V ABI: a in edi, b in esi, result in eax.\n"
        f"global {function}:function ({function}.end - {function})\n{function}:\n"
        f"    lea     eax, [rdi + rsi]\n    ret\n.end:\n\n"
        f"; int {prefix}_version(void)\nglobal {prefix}_version:function ({prefix}_version.end - {prefix}_version)\n"
        f"{prefix}_version:\n    mov     eax, {prefix.upper()}_VERSION\n    ret\n.end:\n\n" + NOTE_GNU_STACK)


def write_new(path: str, text: str, report: List[str]) -> None:
    """Write a file only if it does not exist yet.

    Args:
        path: Destination file.
        text: Content, written with LF line endings (NASM and MSBuild accept them on every OS,
            and they keep diffs identical across machines).
        report: Receives one "created"/"kept" line.

    Raises:
        ScaffoldError: The file could not be written.
    """
    if os.path.exists(path):
        report.append(f"kept     {path} (already exists)")
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="\n", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        raise ScaffoldError(f"cannot write {path}: {exc}") from exc
    report.append(f"created  {path}")


def find_global_json(start: str, root: str) -> Optional[str]:
    """Find the global.json that `dotnet` would use for a project folder.

    The .NET CLI uses the nearest global.json walking up from the working folder, so the
    search walks up from the project folder and stops at the filesystem root.

    Args:
        start: The project folder.
        root: The folder where a new global.json would be created; it is also searched.

    Returns:
        The path of the nearest existing global.json, or None.
    """
    folder = os.path.abspath(start)
    while True:
        candidate = os.path.join(folder, "global.json")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    candidate = os.path.join(os.path.abspath(root), "global.json")
    return candidate if os.path.isfile(candidate) else None


def ensure_global_json(project_dir: str, root: str, sdk_version: str, report: List[str]) -> None:
    """Make sure `dotnet` can resolve AsmFoundation.Sdk for the project.

    Creates <root>/global.json when none exists above the project; otherwise adds the
    msbuild-sdks entry to the existing file, keeping its other settings. A different pinned
    version is left alone and reported, because changing an SDK pin is a decision for the
    repository's owner, not for a scaffold.

    Args:
        project_dir: The project folder.
        root: Folder for a new global.json.
        sdk_version: The version to pin when adding the entry.
        report: Receives one line describing what happened.

    Raises:
        ScaffoldError: The existing global.json is not valid JSON, or cannot be written.
    """
    existing = find_global_json(project_dir, root)
    if existing is None:
        path = os.path.join(root, "global.json")
        write_new(path, json.dumps({"msbuild-sdks": {"AsmFoundation.Sdk": sdk_version}}, indent=2) + "\n", report)
        return
    try:
        with open(existing, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaffoldError(f"cannot read {existing}: {exc}") from exc
    sdks = data.setdefault("msbuild-sdks", {})
    pinned = sdks.get("AsmFoundation.Sdk")
    if pinned:
        note = "" if pinned == sdk_version else f" (pins {pinned}; this skill documents {DEFAULT_SDK_VERSION})"
        report.append(f"kept     {existing}{note}")
        return
    sdks["AsmFoundation.Sdk"] = sdk_version
    try:
        with open(existing, "w", newline="\n", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2) + "\n")
    except OSError as exc:
        raise ScaffoldError(f"cannot write {existing}: {exc}") from exc
    report.append(f"updated  {existing} (added msbuild-sdks AsmFoundation.Sdk {sdk_version})")


def ensure_in_slnx(slnx: str, project_file: str, report: List[str]) -> None:
    """Add the project to a .slnx solution with the generic MSBuild type GUID.

    A new .slnx is created when the file does not exist. An existing one is edited only by
    inserting one <Project> line before </Solution>, as text, so its formatting and comments
    survive (an XML round-trip would rewrite them). A classic .sln is not edited: its format
    needs project GUIDs and configuration maps, so the user is told what to add instead.

    Args:
        slnx: Path of the solution file.
        project_file: Path of the .asmproj to add.
        report: Receives one line describing what happened.

    Raises:
        ScaffoldError: The solution cannot be read, parsed or written.
    """
    rel = os.path.relpath(project_file, os.path.dirname(os.path.abspath(slnx)) or ".").replace("\\", "/")
    line = f'  <Project Path="{rel}" Type="{ASMPROJ_TYPE_GUID}" />'
    if slnx.lower().endswith(".sln"):
        # Verified with the .NET 10 SDK: `dotnet sln add` refuses .asmproj ("unknown project
        # type"), and an .sln entry without ProjectConfigurationPlatforms lines is silently
        # skipped by the build, so a half-written entry would be worse than none.
        report.append(f"manual   {slnx}: dotnet sln add refuses .asmproj; add Project(\"{{{ASMPROJ_TYPE_GUID}}}\") = ... "
                      f"plus its ProjectConfigurationPlatforms lines (without them the build skips it), or use a .slnx")
        return
    if not os.path.exists(slnx):
        write_new(slnx, f"<Solution>\n{line}\n</Solution>\n", report)
        return
    try:
        with open(slnx, encoding="utf-8-sig") as f:
            text = f.read()
        ET.fromstring(text)  # refuse to edit a file that is not well-formed XML
    except (OSError, ET.ParseError) as exc:
        raise ScaffoldError(f"cannot read {slnx}: {exc}") from exc
    if re.search(r'Path="' + re.escape(rel) + '"', text, re.IGNORECASE):
        report.append(f"kept     {slnx} (already lists {rel})")
        return
    index = text.rfind("</Solution>")
    if index < 0:
        raise ScaffoldError(f"{slnx} has no </Solution> element")
    # Insert at the start of the closing tag's line, so the new entry gets its own line with
    # the usual two-space indent even when </Solution> itself is indented.
    line_start = text.rfind("\n", 0, index) + 1
    text = text[:line_start] + line + "\n" + text[line_start:]
    try:
        with open(slnx, "w", newline="\n", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        raise ScaffoldError(f"cannot write {slnx}: {exc}") from exc
    report.append(f"updated  {slnx} (added {rel} with the generic MSBuild type)")


def scaffold(args: argparse.Namespace) -> List[str]:
    """Create the project, its include file and starter source, global.json and the .slnx entry.

    Args:
        args: Parsed command-line options (see main()).

    Returns:
        The report lines (created / kept / updated / manual), in order.

    Raises:
        ScaffoldError: An input is invalid or a file cannot be read or written.
    """
    project_dir = os.path.abspath(args.project_dir)
    name = args.name or os.path.basename(project_dir.rstrip("\\/"))
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.\-]*$", name):
        raise ScaffoldError(f"project name '{name}' is not a valid file and MSBuild project name")
    if args.lib_name and not re.match(r"^[A-Za-z0-9_.\-]+$", args.lib_name):
        raise ScaffoldError(f"--lib-name '{args.lib_name}' must use letters, digits, '.', '_' or '-'")
    report: List[str] = []
    project_file = os.path.join(project_dir, f"{name}.asmproj")
    write_new(project_file, asmproj_text(args.kind, args.runtime, args.lib_name, args.package_id, args.version), report)
    prefix = symbol_prefix(args.lib_name or name)
    file_name, source = source_text(args.kind, args.runtime, prefix)
    if args.kind != "exe":
        # Public include files live in include/: ProjectReference consumers get it on their -I
        # path, and dotnet pack ships it (a project without include/ packs no include files).
        write_new(os.path.join(project_dir, "include", f"{prefix}.inc"), include_text(prefix, f"{prefix}_add"), report)
    write_new(os.path.join(project_dir, file_name), source, report)
    ensure_global_json(project_dir, os.path.abspath(args.root), args.sdk_version, report)
    if args.sln:
        ensure_in_slnx(os.path.abspath(args.sln), project_file, report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; None means sys.argv[1:].

    Returns:
        0 on success, 2 on a ScaffoldError (printed to stderr).
    """
    parser = argparse.ArgumentParser(description="Scaffold an AsmSdk (.asmproj) project.")
    parser.add_argument("project_dir", help="folder of the new project (created if missing)")
    parser.add_argument("--name", help="project name (default: the folder name)")
    parser.add_argument("--kind", choices=sorted(KIND_TO_OUTPUT_TYPE), default="library")
    parser.add_argument("--runtime", choices=["freestanding", "libc"], default="freestanding")
    parser.add_argument("--lib-name", help="AsmLibraryName: lib<name>.so / .a, or the executable's name")
    parser.add_argument("--sln", help="a .slnx to create or add the project to (a .sln gets instructions)")
    parser.add_argument("--package-id", help="make the project packable with this PackageId")
    parser.add_argument("--version", help="package version (default 1.0.0; needs --package-id)")
    parser.add_argument("--sdk-version", default=DEFAULT_SDK_VERSION, help="AsmFoundation.Sdk version for global.json")
    parser.add_argument("--root", default=".", help="folder for a new global.json when none exists above the project (default: .)")
    args = parser.parse_args(argv)
    if args.version and not args.package_id:
        parser.error("--version needs --package-id")
    if args.runtime == "libc" and args.kind in ("static", "objects"):
        print("note: AsmRuntime=Libc has no effect on a static library or objects; the code that links "
              "them decides. The starter source still calls strlen through the PLT.", file=sys.stderr)
    try:
        report = scaffold(args)
    except ScaffoldError as exc:
        print(f"new_asmproj: {exc}", file=sys.stderr)
        return 2
    print("\n".join(report))
    try:
        shown = os.path.relpath(args.project_dir)
    except ValueError:
        # On Windows a path on another drive has no relative form; show it as given.
        shown = args.project_dir
    print("\nnext: dotnet build" + (f" {args.sln}" if args.sln else f" {shown}")
          + "   (check the output with scripts/inspect_elf.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
