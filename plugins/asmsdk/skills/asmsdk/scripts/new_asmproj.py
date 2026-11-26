#!/usr/bin/env python3
"""Scaffold an AsmSdk (.asmproj) project that builds every RID it lists on the first `dotnet build`.

Why this exists: a working AsmFoundation.Sdk 0.4.0 project needs several pieces that are easy
to get subtly wrong by hand - global.json's msbuild-sdks entry, RuntimeIdentifiers (without
them a project builds the build machine's RID alone, and a pack warns ASM0013), the .slnx type
GUID, a public include/ folder (or packages ship no include files), PROTO lines that agree on
every RID (or the C# bindings stop with ASM0133), and sources that assemble and link on every
OS: NASM for the x64 RIDs, whose platform layer (asmsdk.inc: FUNCTION, ARG1.., SHADOW_SPACE,
PLT; default rel; the Linux-only .note.GNU-stack section) ImplicitUsings puts in front of each
file, GNU syntax for the ARM64 RIDs (asmsdk-gnu.inc: FUNCTION, CALL, ADDRESS, RODATA), a 16-byte
aligned stack before calls, and C library calls that need no variadic arguments (Apple's ARM64
passes those on the stack). This script writes all of them consistently for the chosen output
kind, target framework (freestanding or libc) and RIDs.

Safety: it never overwrites an existing file. Existing files are reported as "kept". The only
files it edits in place are global.json (adding the msbuild-sdks entry when missing) and the
.slnx named with --sln (adding the project when it is not listed); both edits are additive.

Usage:
    new_asmproj.py <project-dir> [--name NAME] [--kind library|static|exe|objects]
                   [--framework freestanding|libc] [--rids RID;RID...] [--assembly-name NAME]
                   [--sln PATH.slnx] [--package-id ID] [--version 1.0.0] [--sdk-version 0.4.0]
                   [--root DIR]

WebAssembly (AsmFoundation.Sdk 0.4.0 and later): --rids browser-wasm;wasi-wasm writes
name.wasm.s (LLVM's WebAssembly assembly through asmsdk-wasm.inc); an exe for wasi-wasm writes
main.wasi.s, a WASI command.

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
DEFAULT_SDK_VERSION = "0.4.0"

#: The generic MSBuild ("Common Project System") project type. An .asmproj entry in a .slnx
#: without it fails with "MSB4025 ... ProjectType '' not found".
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: Output kinds accepted by --kind, mapped to the csproj-style OutputType the SDK reads.
KIND_TO_OUTPUT_TYPE = {"library": "Library", "static": "StaticLibrary", "exe": "Exe", "objects": "Objects"}

#: Every native RID AsmFoundation.Sdk 0.4.0 builds, in the order the SDK lists them.
ALL_RIDS = ["win-x64", "win-arm64", "linux-x64", "linux-arm64", "linux-musl-x64", "linux-musl-arm64", "osx-x64", "osx-arm64"]

#: The RIDs a freestanding program can have: macOS supports no static executables (ASM0015).
FREESTANDING_EXE_RIDS = [r for r in ALL_RIDS if not r.startswith("osx-")]

#: The WebAssembly RIDs, since AsmFoundation.Sdk 0.4.0 (0.3.0 stops them with ASM0011). Never a
#: default: a project lists them only when --rids asks, since their code is another language.
WASM_RIDS = ["browser-wasm", "wasi-wasm"]

#: Every RID --rids accepts, in the SDK's order.
KNOWN_RIDS = ALL_RIDS + WASM_RIDS

#: The line every starter source opens with: ImplicitUsings (on by default since 0.4.0) puts the
#: platform layer in front of the file, so the starters write no %include, no default rel and no
#: .note.GNU-stack section (which only Linux takes: macho64 stops on it).
IMPLICIT_NASM = "; The SDK puts its platform layer in front of this file (ImplicitUsings, on by default).\n"

#: The same for llvm-mc's GNU syntax.
IMPLICIT_GNU = "// The SDK puts its platform layer in front of this file (ImplicitUsings, on by default).\n"


def api_protos(kind: str, framework: str, prefix: str, rids: List[str]) -> Dict[str, str]:
    """The PROTO line of each exported function, when the project's API is one for every RID.

    A library or static library with PROTO lines gets C# bindings and a C header from them, and
    the SDK compares every RID's lines (ASM0133: one API for every RID). The native libc
    starters export {prefix}_length (strlen), which the WebAssembly starter cannot (no C
    library there), so a libc project that also lists a wasm RID gets no PROTO lines: one RID
    would declare a function another lacks.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys; programs and objects get none.
        framework: "freestanding" or "libc".
        prefix: Symbol prefix (see symbol_prefix).
        rids: The project's RIDs.

    Returns:
        Function name -> its PROTO line (without a newline); empty when none apply.
    """
    if kind not in ("library", "static"):
        return {}
    has_wasm = any(r in WASM_RIDS for r in rids)
    has_native = any(r not in WASM_RIDS for r in rids)
    if framework == "libc" and has_wasm and has_native:
        return {}
    protos = {f"{prefix}_add": f"PROTO int32_t {prefix}_add(int32_t a, int32_t b)"}
    if framework == "libc" and has_native:
        protos[f"{prefix}_length"] = f"PROTO size_t {prefix}_length(const char* s)"
    else:
        protos[f"{prefix}_version"] = f"PROTO int32_t {prefix}_version(void)"
    return protos


class ScaffoldError(Exception):
    """Raised for inputs the script cannot act on (bad names, unparsable global.json or .slnx).

    The message is shown to the user as is; main() turns it into exit code 2.
    """


def symbol_prefix(assembly_name: str) -> str:
    """Derive the symbol prefix from a library name ("hello-utils" -> "hello_utils").

    Assembly has one global namespace per link, so every exported symbol gets the library's
    prefix; characters NASM and llvm-mc do not accept in identifiers become underscores.

    Args:
        assembly_name: The library base name (AssemblyName).

    Returns:
        A lower-case identifier that starts with a letter or underscore.
    """
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", assembly_name).lower()
    return prefix if re.match(r"[A-Za-z_]", prefix) else "_" + prefix


def parse_rids(text: str) -> List[str]:
    """Split a --rids value ("win-x64;linux-x64" or "win-x64,linux-x64") into RIDs.

    Args:
        text: The option's value.

    Returns:
        The RIDs, lower-case, de-duplicated, in the SDK's order.

    Raises:
        ScaffoldError: A RID is not one AsmSdk builds (the build would stop with ASM0011).
    """
    rids = [r.strip().lower() for r in re.split(r"[;,]", text) if r.strip()]
    unknown = [r for r in rids if r not in KNOWN_RIDS]
    if unknown:
        raise ScaffoldError(f"--rids: {', '.join(unknown)} is not a RID AsmSdk builds; use {', '.join(KNOWN_RIDS)}")
    return [r for r in KNOWN_RIDS if r in rids]


def default_rids(kind: str, framework: str) -> List[str]:
    """The RIDs a new project lists when --rids is not given: every one its kind can build.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        framework: "freestanding" or "libc".

    Returns:
        All eight native RIDs, except for a freestanding program, which macOS cannot have.
    """
    return FREESTANDING_EXE_RIDS if kind == "exe" and framework == "freestanding" else list(ALL_RIDS)


def output_names(kind: str, name: str, rids: Optional[List[str]] = None) -> str:
    """Name a project's outputs per OS, for the project file's comment.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        name: The AssemblyName.
        rids: The project's RIDs; None or no WebAssembly RID means the native names only.

    Returns:
        A short list such as "name.dll, libname.so, libname.dylib", with WebAssembly's names
        (no lib prefix: name.wasm and name.a) when a wasm RID is listed, and only those when
        every RID is WebAssembly.
    """
    native = {
        "library": f"{name}.dll, lib{name}.so, lib{name}.dylib",
        "static": f"{name}.lib, lib{name}.a",
        "exe": f"{name}.exe, {name}",
        "objects": "objects only, in obj/",
    }[kind]
    wasm = {
        "library": f"{name}.wasm (the module) and {name}.a",
        "static": f"{name}.a",
        "exe": f"{name}.wasm (a WASI command)",
        "objects": "objects only, in obj/",
    }[kind]
    rids = rids or []
    if not any(r in WASM_RIDS for r in rids):
        return native
    if all(r in WASM_RIDS for r in rids):
        return wasm
    return f"{native}; WebAssembly: {wasm}"


def asmproj_text(kind: str, framework: str, rids: List[str], assembly_name: Optional[str],
                 package_id: Optional[str], version: Optional[str]) -> str:
    """Build the .asmproj XML for the requested kind, target framework, RIDs and packaging.

    Only properties that differ from the SDK defaults are written, plus RuntimeIdentifiers:
    without them a project builds the build machine's RID alone (and dotnet pack warns
    ASM0013), so a new project lists what it ships. Comments say what each produces.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        framework: The TargetFramework, "freestanding" or "libc".
        rids: The RuntimeIdentifiers (see parse_rids and default_rids).
        assembly_name: AssemblyName, or None to keep the default (the project name).
        package_id: PackageId for dotnet pack, or None for a project that is not packed.
        version: Package version; used only with package_id.

    Returns:
        The project file's text.
    """
    props: List[str] = []
    if kind != "library":
        props.append(f"    <OutputType>{KIND_TO_OUTPUT_TYPE[kind]}</OutputType>")
    if framework == "libc":
        props.append("    <TargetFramework>libc</TargetFramework>   <!-- the platform's C library: glibc or musl, libSystem, the UCRT -->")
    props.append(f"    <RuntimeIdentifiers>{';'.join(rids)}</RuntimeIdentifiers>   <!-- one build each: bin/<Configuration>/{framework}/<rid>/ -->")
    if assembly_name:
        props.append(f"    <AssemblyName>{assembly_name}</AssemblyName>   <!-- {output_names(kind, assembly_name, rids)} -->")
    if package_id and kind == "library":
        # A packed shared library also ships a static library, so asm consumers (and Linux
        # freestanding executables, which link -static) can link it without a run-time dependency.
        props.append("    <AsmProduceStaticLibrary>true</AsmProduceStaticLibrary>")
    if package_id:
        props.append(f"    <PackageId>{package_id}</PackageId>")
        props.append(f"    <Version>{version or '1.0.0'}</Version>")
    body = "\n".join(props)
    return f'<Project Sdk="AsmFoundation.Sdk">\n  <PropertyGroup>\n{body}\n  </PropertyGroup>\n</Project>\n'


def include_text(prefix: str, functions: List[str]) -> str:
    """Build the public NASM include file: guard, extern declarations and a version constant.

    Args:
        prefix: Symbol prefix (see symbol_prefix).
        functions: The exported functions' full symbol names.

    Returns:
        The .inc file's text. The library's own source includes it for the constant and
        defines <PREFIX>_IMPLEMENTATION first, so the externs are declared only to consumers.
    """
    guard = prefix.upper() + "_INC"
    externs = "".join(f"extern {f}\n" for f in functions)
    return (f"; {prefix}.inc - public interface: included by referencing projects and package consumers.\n"
            f"%ifndef {guard}\n%define {guard}\n\n"
            f"%define {prefix.upper()}_VERSION 0x00010000   ; major << 16 | minor\n\n"
            f"%ifndef {prefix.upper()}_IMPLEMENTATION\n{externs}%endif\n\n%endif\n")


def x64_source(kind: str, framework: str, prefix: str, protos: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """The NASM starter for the x64 RIDs: asmsdk.inc's macros, so one file serves every OS.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        framework: The TargetFramework, "freestanding" or "libc".
        prefix: Symbol prefix (see symbol_prefix).
        protos: The PROTO line of each export (see api_protos), written above its FUNCTION.

    Returns:
        (file name, text). Libraries export two functions; programs start at _start
        (freestanding: system calls on Linux, kernel32 on Windows) or main (libc).
    """
    protos = protos or {}
    head = IMPLICIT_NASM
    if kind == "exe" and framework == "libc":
        return "main.asm", (
            "; main.asm - the x64 RIDs: int main(void), called by the SDK's startup code (Linux,\n"
            "; Windows) or by dyld (macOS). puts takes one fixed argument, the same on every OS.\n"
            + head + "extern puts\n\n"
            "section .rodata\nmessage: db \"hello from assembly\", 0\n\n"
            "section .text\n\nFUNCTION main\n"
            "    sub     rsp, SHADOW_SPACE + 8   ; entered at rsp = 16n+8: align the call, plus Windows' shadow space\n"
            "    lea     ARG1, [message]\n"
            "    call    puts PLT                ; the C library: through the PLT on Linux\n"
            "    xor     eax, eax                ; return 0\n"
            "    add     rsp, SHADOW_SPACE + 8\n"
            "    RETURN\nENDFUNCTION\n")
    if kind == "exe":
        return "main.asm", (
            "; main.asm - the x64 RIDs: a program without a C library. Linux: system calls. Windows:\n"
            "; kernel32, which every Windows output links (Windows system call numbers change between\n"
            "; releases). macOS has no freestanding programs (ASM0015).\n"
            + head + "\n"
            "section .rodata\nmessage:        db \"hello from assembly\", 10\nmessage_len     equ $ - message\n\n"
            "section .text\n\n%ifdef WINDOWS\nextern GetStdHandle, WriteFile, ExitProcess\n\n"
            "; _start: the loader calls it like a function (rsp = 16n+8, 32 bytes of shadow space above).\n"
            "FUNCTION _start\n"
            "    sub     rsp, 56                 ; 16-aligned: shadow space, argument 5, the byte count\n"
            "    mov     ecx, -11                ; STD_OUTPUT_HANDLE\n"
            "    call    GetStdHandle\n"
            "    mov     rcx, rax                ; the handle\n"
            "    lea     rdx, [message]\n"
            "    mov     r8d, message_len\n"
            "    lea     r9, [rsp + 40]          ; DWORD *written\n"
            "    mov     qword [rsp + 32], 0     ; argument 5: no OVERLAPPED\n"
            "    call    WriteFile\n"
            "    xor     ecx, ecx                ; exit code 0\n"
            "    call    ExitProcess             ; never returns\n"
            "ENDFUNCTION\n%else\n"
            "; _start: the kernel jumps here (rsp -> argc, argv..., envp...). Never returns.\n"
            "FUNCTION _start\n"
            "    mov     eax, 1                  ; write\n"
            "    mov     edi, 1                  ; stdout\n"
            "    lea     rsi, [message]\n"
            "    mov     edx, message_len\n"
            "    syscall\n"
            "    mov     eax, 231                ; exit_group\n"
            "    xor     edi, edi                ; status 0\n"
            "    syscall\n"
            "ENDFUNCTION\n%endif\n")
    function = f"{prefix}_add"
    implementation = f"%define {prefix.upper()}_IMPLEMENTATION\n%include \"{prefix}.inc\"\n"
    add = (f"; int {function}(int a, int b)\n" + proto_line(protos, function) + f"FUNCTION {function}, 2\n"
           f"    lea     eax, [ARG1 + ARG2]      ; ecx + edx on Windows, edi + esi elsewhere\n"
           f"    RETURN\nENDFUNCTION\n\n")
    if framework == "libc":
        return f"{prefix}.asm", (
            f"; {prefix}.asm - the x64 RIDs: {prefix}_add, and {prefix}_length through the platform's C library.\n"
            + head + implementation + "extern strlen\n\nsection .text\n\n" + add
            + f"; size_t {prefix}_length(const char *s)\n" + proto_line(protos, f"{prefix}_length") + f"FUNCTION {prefix}_length, 1\n"
            f"    sub     rsp, SHADOW_SPACE + 8   ; align the call, plus Windows' shadow space; ARG1 passes through\n"
            f"    call    strlen PLT              ; another library: through the PLT on Linux\n"
            f"    add     rsp, SHADOW_SPACE + 8\n"
            f"    RETURN\nENDFUNCTION\n")
    return f"{prefix}.asm", (
        f"; {prefix}.asm - the x64 RIDs: position-independent, so it links into a shared library, a PIE\n"
        f"; or a static program on every OS.\n"
        + head + implementation + "\nsection .text\n\n" + add
        + f"; int {prefix}_version(void)\n" + proto_line(protos, f"{prefix}_version") + f"FUNCTION {prefix}_version\n"
        f"    mov     eax, {prefix.upper()}_VERSION\n    RETURN\nENDFUNCTION\n")


def arm64_source(kind: str, framework: str, prefix: str, protos: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """The GNU-syntax starter for the ARM64 RIDs: asmsdk-gnu.inc's macros (llvm-mc).

    AAPCS64 is the same calling convention on Linux, Windows and macOS (x0-x7, the result in
    x0), so only names, exports and addressing differ, which the macros handle.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys.
        framework: The TargetFramework, "freestanding" or "libc".
        prefix: Symbol prefix (see symbol_prefix).
        protos: The PROTO line of each export (see api_protos): the same lines as x64_source's.

    Returns:
        (file name, text), the same functions or entry point as x64_source.
    """
    protos = protos or {}
    head = IMPLICIT_GNU
    if kind == "exe" and framework == "libc":
        return "main.s", (
            "// main.s - the ARM64 RIDs: int main(void). puts takes one fixed argument: Apple's ARM64\n"
            "// passes variadic ones on the stack, so printf would be written per OS.\n"
            + head + "\nRODATA\nmessage: .asciz \"hello from assembly\"\n\n"
            "FUNCTION main\n"
            "    stp     x29, x30, [sp, #-16]!   // a call: keep the frame and the return address\n"
            "    mov     x29, sp\n"
            "    ADDRESS x0, message\n"
            "    CALL    puts\n"
            "    mov     w0, #0                  // return 0\n"
            "    ldp     x29, x30, [sp], #16\n"
            "    ret\nENDFUNCTION main\n")
    if kind == "exe":
        return "main.s", (
            "// main.s - the ARM64 RIDs: a program without a C library. Linux: system calls (the generic\n"
            "// table: write 64, exit_group 94). Windows: kernel32. macOS has none (ASM0015).\n"
            + head + "\nRODATA\nmessage: .ascii \"hello from assembly\\n\"\n.set message_len, . - message\n\n"
            ".ifdef WINDOWS\n"
            "FUNCTION _start\n"
            "    stp     x29, x30, [sp, #-32]!   // the frame, plus 16 bytes for DWORD written\n"
            "    mov     x29, sp\n"
            "    mov     w0, #-11                // STD_OUTPUT_HANDLE\n"
            "    CALL    GetStdHandle            // the handle comes back in x0, WriteFile's first argument\n"
            "    ADDRESS x1, message\n"
            "    mov     w2, #message_len\n"
            "    add     x3, sp, #16             // DWORD *written\n"
            "    mov     x4, #0                  // no OVERLAPPED\n"
            "    CALL    WriteFile\n"
            "    mov     w0, #0                  // exit code 0\n"
            "    CALL    ExitProcess             // never returns\n"
            "ENDFUNCTION _start\n"
            ".else\n"
            "FUNCTION _start\n"
            "    mov     x0, #1                  // stdout\n"
            "    ADDRESS x1, message\n"
            "    mov     x2, #message_len\n"
            "    mov     x8, #64                 // write\n"
            "    svc     #0\n"
            "    mov     x0, #0                  // status 0\n"
            "    mov     x8, #94                 // exit_group\n"
            "    svc     #0\n"
            "ENDFUNCTION _start\n"
            ".endif\n")
    add = (f"// int {prefix}_add(int a, int b)\n" + proto_line(protos, f"{prefix}_add")
           + f"FUNCTION {prefix}_add\n    add     w0, w0, w1\n    ret\nENDFUNCTION {prefix}_add\n\n")
    if framework == "libc":
        return f"{prefix}.s", (
            f"// {prefix}.s - the ARM64 RIDs: {prefix}_add, and {prefix}_length through the platform's C library.\n"
            + head + "\n" + add
            + f"// size_t {prefix}_length(const char *s)\n" + proto_line(protos, f"{prefix}_length") + f"FUNCTION {prefix}_length\n"
            f"    stp     x29, x30, [sp, #-16]!   // a call: keep the frame and the return address\n"
            f"    mov     x29, sp\n"
            f"    CALL    strlen                  // x0 passes through\n"
            f"    ldp     x29, x30, [sp], #16\n"
            f"    ret\nENDFUNCTION {prefix}_length\n")
    return f"{prefix}.s", (
        f"// {prefix}.s - the ARM64 RIDs, in GNU syntax for llvm-mc: the same exports as {prefix}.asm.\n"
        + head + "\n" + add
        + f"// int {prefix}_version(void)\n" + proto_line(protos, f"{prefix}_version") + f"FUNCTION {prefix}_version\n"
        f"    mov     w0, #0x10000            // {prefix.upper()}_VERSION: 1.0 as major << 16 | minor\n"
        f"    ret\nENDFUNCTION {prefix}_version\n")


def proto_line(protos: Dict[str, str], function: str) -> str:
    """The PROTO line written above a function's FUNCTION, or nothing when the project has none.

    Args:
        protos: Function name -> PROTO line (see api_protos).
        function: The exported function.

    Returns:
        The line with its newline, or "".
    """
    return protos[function] + "\n" if function in protos else ""


def wasm_source(kind: str, framework: str, prefix: str, with_proto: bool = True) -> Tuple[str, str]:
    """The WebAssembly starter for browser-wasm and wasi-wasm, through asmsdk-wasm.inc (llvm-mc).

    LLVM's WebAssembly assembly (AsmFoundation.Sdk 0.4.0 and later), a stack machine whose
    functions declare their type, with a PROTO line per export so the C# bindings come from it.
    It avoids the measured traps: no assembler constant (llvm-mc's wasm writer crashes on any),
    ENDDATA after every data label, ENDFUNCTION after every function, PROTO before its FUNCTION,
    and .p2align 2 before the data WASI is handed.

    Args:
        kind: One of KIND_TO_OUTPUT_TYPE's keys ("exe" is a WASI command; scaffold() refuses an
            exe for browser-wasm).
        framework: The TargetFramework; a libc library or program is refused by scaffold()
            (ASM0016), a libc static library or objects get the same freestanding code.
        prefix: Symbol prefix (see symbol_prefix).
        with_proto: Whether the library's functions get PROTO lines (see api_protos). False
            when the native starters export another API (a libc project's strlen wrapper): the
            SDK requires the same PROTO lines in every RID's source (ASM0133, "one API for every
            RID").

    Returns:
        (file name, text): {prefix}.wasm.s with {prefix}_add and {prefix}_version, or
        main.wasi.s with _start writing a line through WASI's fd_write.
    """
    if kind == "exe":
        return "main.wasi.s", (
            "// main.wasi.s - wasi-wasm: a WASI command (wasmtime, or dotnet run -r wasi-wasm). WASI is\n"
            "// imported, not called with syscall: fd_write prints, proc_exit ends the program.\n"
            "IMPORT_FUNCTION wasi_snapshot_preview1, fd_write, (i32, i32, i32, i32) -> (i32)\n"
            "IMPORT_FUNCTION wasi_snapshot_preview1, proc_exit, (i32) -> ()\n\n"
            "FUNCTION _start, () -> ()\n"
            "    i32.const 1                 // standard output\n"
            "    ADDRESS iov                 // one iovec: { message, length }\n"
            "    i32.const 1\n"
            "    ADDRESS written             // where fd_write stores the byte count\n"
            "    CALL fd_write\n"
            "    drop                        // the errno\n"
            "    i32.const 0                 // exit status 0\n"
            "    CALL proc_exit\n"
            "ENDFUNCTION _start\n\n"
            "    DATA\n"
            "    .p2align 2                  // WASI refuses misaligned pointers (wasmtime)\n"
            "iov:\n"
            "    .int message\n"
            "    .int .Lmessage_end - message\n"
            "ENDDATA iov\n"
            "written:\n"
            "    .int 0\n"
            "ENDDATA written\n\n"
            "    RODATA\n"
            "message:\n"
            "    .ascii \"hello from WebAssembly\\n\"\n"
            ".Lmessage_end:\n"
            "ENDDATA message\n")
    # A PROTO line here and none in the .asm/.s would be ASM0133: the note says how to add
    # them everywhere at once instead.
    proto_add = f"PROTO int32_t {prefix}_add(int32_t a, int32_t b)\n" if with_proto else ""
    proto_version = f"PROTO int32_t {prefix}_version(void)\n" if with_proto else ""
    note = ("" if with_proto else
            "// C# bindings: add a PROTO line before each FUNCTION here AND in every native source of this\n"
            "// project (the same lines: ASM0133 compares the RIDs), e.g. PROTO int32_t " + prefix + "_add(int32_t a, int32_t b)\n\n")
    return f"{prefix}.wasm.s", (
        f"// {prefix}.wasm.s - browser-wasm and wasi-wasm: the same exports as the native sources, in\n"
        f"// LLVM's WebAssembly assembly. A stack machine: parameters are locals 0..n-1, and the result\n"
        f"// is what the function leaves on the operand stack. No .set/.equ constants: llvm-mc's wasm\n"
        f"// writer crashes on them, so numbers are written where they are used.\n\n"
        + note + proto_add +
        f"FUNCTION {prefix}_add, (i32, i32) -> (i32)\n"
        f"    local.get 0\n"
        f"    local.get 1\n"
        f"    i32.add\n"
        f"ENDFUNCTION {prefix}_add\n\n"
        + proto_version +
        f"FUNCTION {prefix}_version, () -> (i32)\n"
        f"    i32.const 0x10000           // {prefix.upper()}_VERSION: 1.0 as major << 16 | minor\n"
        f"ENDFUNCTION {prefix}_version\n")


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
        # The script does not edit a classic .sln: an entry needs a project GUID and
        # ProjectConfigurationPlatforms lines (without them the build silently skips the
        # project), which the .NET CLI writes itself. Since AsmFoundation.Sdk 0.4.0 it takes an
        # .asmproj (the SDK names its type, DefaultProjectTypeGuid); 0.3.0 and older were refused.
        report.append(f"manual   {slnx}: run dotnet sln \"{slnx}\" add \"{project_file}\" (AsmFoundation.Sdk 0.4.0 or later: "
                      f"the CLI writes the entry and its configuration lines), or use a .slnx")
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
    """Create the project, its include file and starter sources, global.json and the .slnx entry.

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
    if args.assembly_name and not re.match(r"^[A-Za-z0-9_.\-]+$", args.assembly_name):
        raise ScaffoldError(f"--assembly-name '{args.assembly_name}' must use letters, digits, '.', '_' or '-'")
    rids = parse_rids(args.rids) if args.rids else default_rids(args.kind, args.framework)
    if not rids:
        raise ScaffoldError("--rids names no RID")
    if args.kind == "exe" and args.framework == "freestanding" and any(r.startswith("osx-") for r in rids):
        raise ScaffoldError("a freestanding program cannot target macOS (ASM0015: Apple supports no static executables); "
                            "use --framework libc, or drop the osx RIDs")
    wasm = [r for r in rids if r in WASM_RIDS]
    if args.kind == "exe" and "browser-wasm" in wasm:
        raise ScaffoldError("a program cannot target browser-wasm (ASM0017: the browser starts no program); "
                            "make a library for the browser, or the program for wasi-wasm")
    if args.framework == "libc" and wasm and args.kind in ("library", "exe"):
        raise ScaffoldError("a libc WebAssembly module or WASI program does not build (ASM0016: the bundled wasm-ld links "
                            "no C library); use --framework freestanding, or --kind static for a .NET WebAssembly app")
    if args.kind == "exe" and wasm and any(r not in WASM_RIDS for r in rids):
        raise ScaffoldError("a WASI program and a native program differ in everything but their name: scaffold them as two "
                            "projects (--rids wasi-wasm, and the native RIDs)")
    report: List[str] = []
    project_file = os.path.join(project_dir, f"{name}.asmproj")
    write_new(project_file, asmproj_text(args.kind, args.framework, rids, args.assembly_name, args.package_id, args.version), report)
    prefix = symbol_prefix(args.assembly_name or name)
    if args.kind != "exe" and any(r not in WASM_RIDS for r in rids):
        # Public include files live in include/: ProjectReference consumers get it on their -I
        # path, and dotnet pack ships it (a project without include/ packs no include files).
        second = f"{prefix}_length" if args.framework == "libc" else f"{prefix}_version"
        write_new(os.path.join(project_dir, "include", f"{prefix}.inc"), include_text(prefix, [f"{prefix}_add", second]), report)
    # NASM builds the x64 RIDs, llvm-mc's GNU syntax the ARM64 ones (ASM0023 for a RID no
    # source builds), so each CPU in the list gets its file.
    # One API for every RID: the same PROTO lines in each source, or none (see api_protos).
    protos = api_protos(args.kind, args.framework, prefix, rids)
    if any(r.endswith("-x64") for r in rids):
        file_name, source = x64_source(args.kind, args.framework, prefix, protos)
        write_new(os.path.join(project_dir, file_name), source, report)
    if any(r.endswith("-arm64") for r in rids):
        file_name, source = arm64_source(args.kind, args.framework, prefix, protos)
        write_new(os.path.join(project_dir, file_name), source, report)
    if wasm:
        # WebAssembly needs a source qualified for it (no unqualified file builds wasm: ASM0023).
        file_name, source = wasm_source(args.kind, args.framework, prefix,
                                        with_proto=bool(protos) or all(r in WASM_RIDS for r in rids))
        write_new(os.path.join(project_dir, file_name), source, report)
        if args.sdk_version in ("0.1.0", "0.2.0", "0.3.0"):
            report.append(f"manual   WebAssembly needs AsmFoundation.Sdk 0.4.0 or later ({args.sdk_version} stops a wasm RID "
                          "with ASM0011): pass --sdk-version 0.4.0")
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
    parser.add_argument("--framework", choices=["freestanding", "libc"], default="freestanding",
                        help="the TargetFramework: freestanding (no C library) or libc (the platform's C library)")
    parser.add_argument("--rids", help="RuntimeIdentifiers, ';' or ',' separated (default: every native RID the kind can build: "
                                       "all eight, or all but osx for a freestanding program); browser-wasm and wasi-wasm "
                                       "only when named")
    parser.add_argument("--assembly-name", help="AssemblyName: name.dll / libname.so / libname.dylib, or the program's name")
    parser.add_argument("--sln", help="a .slnx to create or add the project to (a .sln gets instructions)")
    parser.add_argument("--package-id", help="make the project packable with this PackageId")
    parser.add_argument("--version", help="package version (default 1.0.0; needs --package-id)")
    parser.add_argument("--sdk-version", default=DEFAULT_SDK_VERSION, help="AsmFoundation.Sdk version for global.json")
    parser.add_argument("--root", default=".", help="folder for a new global.json when none exists above the project (default: .)")
    args = parser.parse_args(argv)
    if args.version and not args.package_id:
        parser.error("--version needs --package-id")
    if args.framework == "libc" and args.kind in ("static", "objects"):
        print("note: TargetFramework=libc links nothing into a static library or objects, but it records that "
              "the code needs the C library: a freestanding project cannot reference it (NU1201). The native "
              "starter sources call strlen (the WebAssembly one calls nothing).", file=sys.stderr)
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
          + "   (one build per RID; check the outputs with scripts/inspect_output.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
