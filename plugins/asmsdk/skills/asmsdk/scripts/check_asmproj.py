#!/usr/bin/env python3
"""Lint AsmSdk projects and their NASM sources for the mistakes that break builds or outputs.

Why this exists: AsmFoundation.Sdk 0.3.0 builds one project for up to seven runtime
identifiers (win-x64, win-arm64, linux-x64, linux-arm64, linux-musl-x64, osx-x64, osx-arm64),
and many of its failure modes are silent (a stale build, a package without include files, a
Windows DLL that exports nothing) or surface far from their cause ("relocation R_X86_64_PC32
cannot be used against symbol", "unrecognised symbol type `function'" from macOS's NASM
output, ASM0080 after a link). A directive that is right on Linux can stop the macOS build,
and the reverse. Each check here encodes one such fact, measured against the 0.3.0 targets
and the bundled NASM 3.02 / LLVM 23.1.5, and reports the file, line and fix before anything
is built.

What it reads: every *.asmproj under the given path (or the given .asmproj), the projects they
reference, their *.asm / *.inc / *.s files, the nearest global.json and Directory.Build.props,
any *.slnx under the path, and (when the pinned SDK version is restored in the NuGet cache) the
SDK's own C library symbol lists. It never writes. It does not evaluate MSBuild: properties are
read as written, conditions are noted but not evaluated, so a property set only under a
condition is treated as set.

How it knows the platforms: the RIDs a project builds are its RuntimeIdentifiers (or
RuntimeIdentifier); a project that names none builds what its referencing projects ask for, so
it inherits the RIDs of the asm projects that reference it, and when nothing here references it
every RID is assumed and platform findings become warnings. Each source then builds the RIDs
the SDK would select it for (its extension and file-name qualifier, as AsmSelectSources picks
them), and each line the platforms its %ifdef WINDOWS / LINUX / MACOS guards leave it on. Source
checks are line-based heuristics over NASM syntax: treat a warning as "look here", an error as
"this will fail as written". GNU-syntax (.s) ARM64 files are counted for RID coverage, not linted.

WebAssembly (browser-wasm, wasi-wasm: the SDK release after 0.3.0): the project rules (no wasm
in 0.3.0, no browser program, no libc module, no define with a value, no pattern in a module's
ExportsFile) and, for each .s source a wasm RID selects, the measured traps of llvm-mc's wasm
parser and writer (ASMWASM001-ASMWASM016): assembler constants, data labels without a size,
PROTO or a function macro inside a function, untyped select, return_call where .NET links the
code, calls to functions whose type llvm-mc has not seen, a PROTO line whose C types lower to
another wasm signature than its FUNCTION's, a PROTO for no exported function, float operands
llvm-mc refuses (an integer, inf, a decimal it cannot prove exact) or rounds to f32 unannounced.

Usage:
    check_asmproj.py <path> [<path> ...] [--json] [--no-info]

Exit codes: 0 = no error-level finding; 1 = at least one error-level finding;
2 = usage error (no project found, unreadable path).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

#: The SDK version whose behavior these checks encode.
DOCUMENTED_SDK_VERSION = "0.3.0"

#: Settings 0.2.0 removed (the build fails with ASM0100-ASM0108), and what replaces each.
#: AsmDefine items, the eighth, are checked separately: they are items, not properties.
REMOVED_SETTINGS = {
    "AsmLibraryName": "AssemblyName (still lib<name>.so, lib<name>.a, <name>)",
    "AsmRuntime": "TargetFramework: freestanding (the default) or libc",
    "AsmDefineConstants": "DefineConstants (DEBUG or RELEASE, FREESTANDING or LIBC are appended for you)",
    "AsmDebugInfo": "DebugSymbols (DebugType=none turns DWARF off)",
    "AsmEntryPoint": "StartupObject",
    "AsmLinkFlags": "LinkerArg items, and ExportsFile for a version script",
    "AsmOutputKind": "OutputType",
}

#: Settings 0.3.0 removed without an error of their own: the SDK no longer reads them, so a
#: project that relied on them names no RID and stops with ASM0010.
REMOVED_IN_030 = {
    "AsmTargetRid": "RuntimeIdentifiers (win-x64;linux-x64;osx-arm64; ...) or one RuntimeIdentifier",
    "AsmFormat": "nothing: the RID decides the object format (win64, elf64, macho64)",
}

#: Generic MSBuild project type; an .slnx entry for an .asmproj needs it (MSB4025 otherwise).
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: Folders never scanned for sources: build outputs and tool state.
SKIP_DIRS = {"bin", "obj", ".git", ".vs", ".idea", "node_modules", "artifacts"}

#: The seven RIDs AsmSdk 0.3.0 builds: name -> (OS, CPU, musl). The same table as the SDK's
#: RuntimeTarget.All, which the source selection below mirrors.
RIDS: Dict[str, Tuple[str, str, bool]] = {
    "win-x64": ("Windows", "x64", False),
    "win-arm64": ("Windows", "arm64", False),
    "linux-x64": ("Linux", "x64", False),
    "linux-arm64": ("Linux", "arm64", False),
    "linux-musl-x64": ("Linux", "x64", True),
    "osx-x64": ("MacOS", "x64", False),
    "osx-arm64": ("MacOS", "arm64", False),
    # WebAssembly, the SDK release after 0.3.0 (0.3.0 stops these with ASM0011, ASMPRJ019):
    # LLVM's wasm assembly in .s files qualified for it, never NASM, never an unqualified file.
    "browser-wasm": ("Browser", "wasm", False),
    "wasi-wasm": ("WASI", "wasm", False),
}

#: The native RIDs: the seven 0.3.0 builds, and what a project with no known RID is judged for.
NATIVE_RIDS = [rid for rid, (_, cpu, _) in RIDS.items() if cpu != "wasm"]

#: The OS names used throughout (RIDS' first field), and the set of all three.
OSES = ("Windows", "Linux", "MacOS")
ALL_OSES: FrozenSet[str] = frozenset(OSES)

#: How a finding names a platform: the OS and NASM's output format for it.
OS_LABEL = {"Windows": "Windows (win64)", "Linux": "Linux (elf64)", "MacOS": "macOS (macho64)"}

#: File-name qualifiers that are not RIDs (x.linux.asm, x.unix.asm, x.arm64.s, ...).
FAMILY_QUALIFIERS = {"win", "linux", "linux-musl", "osx", "unix", "x64", "arm64", "browser", "wasi", "wasm"}

#: The SDK's defines that name an OS, for %ifdef guards: WINDOWS, LINUX and MACOS select one
#: OS; MUSL implies Linux; ARM64 is never defined while NASM assembles (x64 only).
OS_DEFINES: Dict[str, FrozenSet[str]] = {
    "WINDOWS": frozenset({"Windows"}), "LINUX": frozenset({"Linux"}), "MACOS": frozenset({"MacOS"}),
    "MUSL": frozenset({"Linux"}), "ARM64": frozenset(),
}

#: The SDK's defines that do not depend on the OS: a block under one of them is assembled on
#: every OS the file builds, so what is inside must suit all of them.
OS_NEUTRAL_DEFINES = {"X64", "DEBUG", "RELEASE", "FREESTANDING", "LIBC", "ASMSDK_EXECUTABLE", "ASMSDK_EXPORTS_FILE"}

#: NASM's output format names, for %ifidn __OUTPUT_FORMAT__ guards.
OUTPUT_FORMAT_OS = {"elf64": "Linux", "elf": "Linux", "win64": "Windows", "macho64": "MacOS"}

#: Words after `global name:` and the platforms whose NASM 3.02 output stops on them, measured
#: with the bundled NASM (elf64, win64, macho64): "unrecognised symbol type". win64 accepts and
#: ignores `function`; only macho64 knows `private_extern`.
REJECTED_SYMBOL_WORDS: Dict[str, FrozenSet[str]] = {
    "function": frozenset({"MacOS"}),
    "data": frozenset({"Windows", "MacOS"}),
    "object": frozenset({"Windows", "MacOS"}),
    "notype": frozenset({"Windows", "MacOS"}),
    "hidden": frozenset({"Windows", "MacOS"}),
    "internal": frozenset({"Windows", "MacOS"}),
    "protected": frozenset({"Windows", "MacOS"}),
    "private_extern": frozenset({"Linux", "Windows"}),
}

#: `wrt ..x` special symbols and the platforms whose NASM output does not define them
#: (measured: "symbol `..plt' not defined"). ..plt and ..got are ELF's, ..gotpcrel Mach-O's,
#: ..imagebase PE's.
REJECTED_WRT: Dict[str, FrozenSet[str]] = {
    "..plt": frozenset({"Windows", "MacOS"}),
    "..got": frozenset({"Windows", "MacOS"}),
    "..gotpcrel": frozenset({"Linux", "Windows"}),
    "..imagebase": frozenset({"Linux", "MacOS"}),
}

#: Section names a platform's NASM output rejects (measured): macho64 stops on both with
#: "unknown section name".
REJECTED_SECTIONS: Dict[str, FrozenSet[str]] = {
    ".note.gnu-stack": frozenset({"MacOS"}),
    ".drectve": frozenset({"MacOS"}),
}

#: asmsdk.inc's function macros: each writes every format's own directives, so the symbols
#: they define are exempt from the per-format directive checks.
ASMSDK_FUNCTION_MACROS = ("FUNCTION", "LOCAL_FUNCTION", "HIDDEN_FUNCTION")

#: What the SDK's Windows C library stand-in adds to ucrtbase.dll's exports: wrappers of its
#: own for the functions the UCRT headers define inline (stubs/winstdio-*).
WINDOWS_STDIO_WRAPPERS = frozenset(
    "printf fprintf sprintf snprintf vprintf vfprintf vsprintf vsnprintf sscanf atexit".split())

#: Functions the Linux C library stub defines (stubs/linux.symbols: the same 296 names in
#: 0.2.0 and 0.3.0, for glibc and musl alike). A libc executable that calls a function outside
#: this set fails with "undefined symbol" unless it is an AsmLibcSymbol item.
LIBC_STUB_FUNCTIONS = frozenset("""
__libc_start_main __cxa_finalize __cxa_atexit atexit exit _exit abort __stack_chk_fail __assert_fail
__errno_location __sched_cpucount malloc free calloc realloc reallocarray aligned_alloc posix_memalign
memalign valloc malloc_usable_size memcpy memmove memset memcmp memchr memrchr mempcpy strlen strnlen
strcmp strncmp strcasecmp strncasecmp strcpy strncpy stpcpy strcat strncat strchr strrchr strstr strdup
strndup strerror strerror_r strtok_r strspn strcspn strtol strtoul strtoll strtoull strtod strtof atoi
atol atoll printf fprintf sprintf snprintf dprintf vprintf vfprintf vsprintf vsnprintf vdprintf puts
fputs fputc putc putchar fwrite fread fopen fdopen fclose fflush fgets fgetc getc getchar getline perror
setvbuf fileno sscanf getenv secure_getenv setenv unsetenv qsort bsearch rand srand random srandom
getrandom getentropy clock_gettime clock_getres clock_nanosleep nanosleep usleep sleep gettimeofday time
localtime_r gmtime_r strftime pthread_create pthread_join pthread_detach pthread_self pthread_exit
pthread_equal pthread_kill pthread_sigmask pthread_once pthread_yield pthread_setname_np
pthread_getname_np pthread_attr_init pthread_attr_destroy pthread_attr_setstacksize
pthread_attr_setdetachstate pthread_attr_setaffinity_np pthread_setaffinity_np pthread_getaffinity_np
pthread_mutex_init pthread_mutex_destroy pthread_mutex_lock pthread_mutex_trylock pthread_mutex_unlock
pthread_mutexattr_init pthread_mutexattr_destroy pthread_mutexattr_settype pthread_cond_init
pthread_cond_destroy pthread_cond_wait pthread_cond_timedwait pthread_cond_signal pthread_cond_broadcast
pthread_rwlock_init pthread_rwlock_destroy pthread_rwlock_rdlock pthread_rwlock_wrlock
pthread_rwlock_unlock pthread_spin_init pthread_spin_destroy pthread_spin_lock pthread_spin_trylock
pthread_spin_unlock pthread_key_create pthread_key_delete pthread_getspecific pthread_setspecific
pthread_barrier_init pthread_barrier_destroy pthread_barrier_wait signal sigaction sigemptyset
sigfillset sigaddset sigdelset sigismember sigprocmask sigwaitinfo sigtimedwait sigwait raise kill
sched_yield sched_getaffinity sched_setaffinity sched_getcpu get_nprocs get_nprocs_conf sysconf
getpagesize uname prctl syscall open openat close read write pread pwrite readv writev lseek fstat stat
lstat fstatat ftruncate fsync fdatasync unlink unlinkat mkdir rmdir rename access dup dup2 dup3 pipe
pipe2 fcntl ioctl isatty mmap munmap mprotect madvise mremap msync mlock munlock memfd_create socket
socketpair bind listen accept accept4 connect shutdown send sendto sendmsg sendmmsg recv recvfrom
recvmsg recvmmsg setsockopt getsockopt getsockname getpeername getaddrinfo freeaddrinfo gai_strerror
inet_pton inet_ntop htons ntohs htonl ntohl epoll_create epoll_create1 epoll_ctl epoll_wait epoll_pwait
poll ppoll select pselect eventfd eventfd_read eventfd_write timerfd_create timerfd_settime
timerfd_gettime signalfd getpid getppid gettid fork vfork execve execvp waitpid wait getuid geteuid
getgid getegid getrlimit setrlimit getrusage dlopen dlsym dlclose dlerror dladdr dl_iterate_phdr
stdin stdout stderr environ
""".split())

#: Names that NASM parses as keywords or mnemonics where a label is expected; a symbol with one
#: of these names must be written with a "$" prefix ($wait, $rel).
KEYWORD_NAMES = {"rel", "abs", "wait", "syscall", "sysret", "wrt", "seg", "strict", "nosplit", "times",
                 "byte", "word", "dword", "qword", "tword", "oword", "yword", "zword", "ret", "nop"}

#: x86-64 register names (lower case); a memory operand that uses one has a base or index and
#: needs no RIP-relative decision.
REGISTERS = set(
    "rax rbx rcx rdx rsi rdi rbp rsp eax ebx ecx edx esi edi ebp esp ax bx cx dx si di bp sp "
    "al bl cl dl ah bh ch dh sil dil bpl spl rip eip".split()
    + [f"r{i}{s}" for i in range(8, 16) for s in ("", "d", "w", "b", "l")]
    + [f"{p}mm{i}" for p in ("x", "y", "z") for i in range(32)]
    + [f"k{i}" for i in range(8)] + [f"mm{i}" for i in range(8)] + [f"st{i}" for i in range(8)]
    + "cs ds es fs gs ss".split())

#: asmsdk.inc's register names for the calling convention (ARG1 is rcx on Windows, rdi
#: elsewhere): registers too, for the addressing checks.
ARG_REGISTER_MACROS = {f"arg{i}{s}" for i in range(1, 7) for s in ("", "d", "w", "b")}

#: NASM words that can appear inside operands without being symbol references.
OPERAND_KEYWORDS = {"rel", "abs", "wrt", "byte", "word", "dword", "qword", "tword", "oword", "yword",
                    "zword", "ptr", "strict", "nosplit", "seg", "near", "far", "short", "to"}

IDENT = r"[A-Za-z_.?$][\w.$#@~?]*"
DATA_DIRECTIVES = ("db", "dw", "dd", "dq", "dt", "do", "dy", "dz")
RES_DIRECTIVES = ("resb", "resw", "resd", "resq", "rest", "reso", "resy", "resz")

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def rid_specificity(rid: str, qualifier: str) -> int:
    """How closely a file-name qualifier fits a RID: the SDK's RuntimeTarget.Specificity.

    Args:
        rid: One of RIDS' names.
        qualifier: The qualifier of x.<qualifier>.asm, or "" for none.

    Returns:
        1 for no qualifier, 50 for the RID itself, 40 linux-musl (musl only), 30 for its OS
        family (win, linux, osx, browser, wasi), 20 unix (Linux and macOS only: the browser and
        WASI are not Unix), 10 its CPU (x64, arm64, wasm), 0 when the qualifier does not apply.
    """
    os_name, cpu, musl = RIDS[rid]
    q = qualifier.lower()
    if not q:
        return 1
    if q == rid:
        return 50
    return {
        "linux-musl": 40 if musl else 0,
        "win": 30 if os_name == "Windows" else 0,
        "linux": 30 if os_name == "Linux" else 0,
        "osx": 30 if os_name == "MacOS" else 0,
        "browser": 30 if os_name == "Browser" else 0,
        "wasi": 30 if os_name == "WASI" else 0,
        "unix": 20 if os_name in ("Linux", "MacOS") else 0,
        "x64": 10 if cpu == "x64" else 0,
        "arm64": 10 if cpu == "arm64" else 0,
        "wasm": 10 if cpu == "wasm" else 0,
    }.get(q, 0)


def split_source_name(path: str) -> Tuple[str, str, str]:
    """Split a source path the way the SDK's AsmSelectSources does.

    Args:
        path: An .asm or .s path.

    Returns:
        (key, qualifier, language): key is folder + name without qualifier and extension
        (case-folded: files of one key compete), qualifier is "" or a RID / family word, and
        language is "Nasm" (.asm, x64 only) or "Gnu" (.s, llvm-mc).
    """
    folder, name = os.path.split(path)
    stem, extension = os.path.splitext(name)
    language = "Gnu" if extension.lower() == ".s" else "Nasm"
    qualifier = ""
    dot = stem.rfind(".")
    if dot > 0 and (stem[dot + 1:].lower() in RIDS or stem[dot + 1:].lower() in FAMILY_QUALIFIERS):
        qualifier = stem[dot + 1:]
        stem = stem[:dot]
    return os.path.normcase(os.path.join(folder, stem)), qualifier, language


def source_score(path: str, rid: str) -> int:
    """The SDK's score of one source for one RID (0 = not built for it).

    Args:
        path: An .asm or .s path.
        rid: One of RIDS' names.

    Returns:
        0 when the file does not build the RID: NASM never builds ARM64 or WebAssembly, and an
        unqualified file builds only its own language's CPU (.asm x64, .s ARM64; no
        unqualified file builds wasm). Otherwise the qualifier's rid_specificity, the highest
        of a key winning.
    """
    _, qualifier, language = split_source_name(path)
    cpu = RIDS[rid][1]
    if language == "Nasm" and cpu != "x64":
        return 0
    if not qualifier and cpu == "wasm":
        return 0
    if not qualifier:
        return 1 if (language == "Nasm") == (cpu == "x64") else 0
    return rid_specificity(rid, qualifier)


def qualifier_is_arm64_only(qualifier: str) -> bool:
    """Whether a qualifier names only RIDs NASM cannot build (a NASM file with it is ASM0021).

    Args:
        qualifier: A file-name qualifier.

    Returns:
        True when every RID it applies to is ARM64 (arm64, linux-arm64, ...) or WebAssembly
        (wasm, browser, wasi-wasm, ...): NASM assembles x86-64 only.
    """
    applies = [rid for rid in RIDS if rid_specificity(rid, qualifier) > 0]
    return bool(applies) and all(RIDS[rid][1] in ("arm64", "wasm") for rid in applies)


def select_sources(sources: List[str], rid: str) -> Tuple[List[str], List[List[str]]]:
    """Pick the sources one RID builds, as AsmSelectSources does.

    Args:
        sources: Every .asm and .s source of the project.
        rid: One of RIDS' names.

    Returns:
        (selected, ties): the winning file of each key that applies, and the groups of files
        that tie for a key (ASM0020; none of a tied group is selected).
    """
    groups: Dict[str, List[Tuple[int, str]]] = {}
    for path in sources:
        score = source_score(path, rid)
        if score > 0:
            groups.setdefault(split_source_name(path)[0], []).append((score, path))
    selected, ties = [], []
    for candidates in groups.values():
        best = max(score for score, _ in candidates)
        winners = [path for score, path in candidates if score == best]
        if len(winners) > 1:
            ties.append(sorted(winners))
        else:
            selected.append(winners[0])
    return sorted(selected), ties


def _global_packages_folders() -> List[str]:
    """The NuGet global packages folders to search for the SDK package.

    Returns:
        NUGET_PACKAGES when set, then the default ~/.nuget/packages; existing folders only.
    """
    candidates = [os.environ.get("NUGET_PACKAGES", ""), os.path.join(os.path.expanduser("~"), ".nuget", "packages")]
    return [c for c in candidates if c and os.path.isdir(c)]


def read_symbol_list(path: str) -> Set[str]:
    """Read one of the SDK's stubs/*.symbols lists.

    Args:
        path: The list file.

    Returns:
        The names: several per line, "#" comments, "data <name> <size>" and "raw <name>" lines
        contributing their name.

    Raises:
        OSError: The file cannot be read (callers check that it exists).
    """
    names: Set[str] = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            words = line.split("#", 1)[0].split()
            if not words:
                continue
            if words[0] in ("data", "raw") and len(words) > 1:
                names.add(words[1])
            else:
                names.update(words)
    return names


def load_sdk_symbol_lists(version: str) -> Dict[str, Set[str]]:
    """The C library names the SDK links against per OS, from its package when it is restored.

    Linux's list is built in (LIBC_STUB_FUNCTIONS); macOS's and Windows' are too long to copy
    and differ by release, so they are read from <packages>/asmfoundation.sdk/<version>/stubs/
    when that version is in the NuGet cache. Without them, the undefined-symbol check skips
    those OSes rather than guessing.

    Args:
        version: The SDK version global.json pins.

    Returns:
        Keys present only for lists that were found: "MacOS" (libSystem, for libc),
        "WindowsLibc" (ucrtbase.dll + kernel32.dll + the SDK's stdio wrappers) and
        "WindowsKernel" (kernel32.dll, which every Windows output links).
    """
    lists: Dict[str, Set[str]] = {}
    for root in _global_packages_folders():
        stubs = os.path.join(root, "asmfoundation.sdk", version.lower(), "stubs")
        if not os.path.isdir(stubs):
            continue
        macos = os.path.join(stubs, "macos.symbols")
        ucrt = os.path.join(stubs, "ucrtbase.symbols")
        kernel = os.path.join(stubs, "kernel32.symbols")
        if os.path.isfile(macos):
            lists["MacOS"] = read_symbol_list(macos)
        if os.path.isfile(kernel):
            lists["WindowsKernel"] = read_symbol_list(kernel)
            if os.path.isfile(ucrt):
                lists["WindowsLibc"] = read_symbol_list(ucrt) | lists["WindowsKernel"] | set(WINDOWS_STDIO_WRAPPERS)
        break
    return lists


@dataclass
class Finding:
    """One problem found: where it is, how bad it is, what it means and how to fix it.

    severity is "error" (fails the build or produces a wrong output as written), "warning"
    (very likely wrong, or wrong under common settings) or "info" (a recommendation).
    """

    severity: str
    code: str
    path: str
    line: int
    message: str
    fix: str = ""


@dataclass
class Project:
    """What the linter knows about one .asmproj, read without evaluating MSBuild.

    props maps a property name to the list of (value, condition) pairs as written, in order,
    so checks can tell "set" from "set only under a condition". items maps an item type to a
    list of attribute dictionaries (Include, Remove, Condition, metadata).
    """

    path: str
    dir: str
    sdk: str
    props: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    items: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    prop_lines: Dict[str, int] = field(default_factory=dict)

    def prop(self, name: str) -> Optional[str]:
        """Return the last value written for a property (conditions ignored), or None.

        Args:
            name: Property name, matched case-insensitively as MSBuild does.

        Returns:
            The value text, stripped; None when the project never sets it.
        """
        for key, values in self.props.items():
            if key.lower() == name.lower() and values:
                return values[-1][0].strip()
        return None

    def prop_entries(self, name: str) -> List[Tuple[str, str]]:
        """Return every (value, condition) written for a property, case-insensitively.

        Checks that must see conditional assignments (an OS-specific property) use this
        instead of prop(), which keeps only the last value.

        Args:
            name: Property name.

        Returns:
            (value, condition) pairs in document order; condition is "" when unconditional.
        """
        return [v for k, vs in self.props.items() if k.lower() == name.lower() for v in vs]

    def item_entries(self, item_type: str) -> List[Dict[str, str]]:
        """Return every item of a type as written (attributes and metadata), case-insensitively.

        Args:
            item_type: The item type, such as LinkerArg or AsmDefine.

        Returns:
            The items' attribute dictionaries, in document order (Condition included).
        """
        return [i for k, vs in self.items.items() if k.lower() == item_type.lower() for i in vs]

    @property
    def kind(self) -> str:
        """The output kind the SDK computes from OutputType: SharedLibrary, StaticLibrary, Executable or Objects."""
        output_type = (self.prop("OutputType") or "Library").lower()
        return {"exe": "Executable", "winexe": "Executable", "staticlibrary": "StaticLibrary",
                "objects": "Objects"}.get(output_type, "SharedLibrary")

    @property
    def frameworks(self) -> List[str]:
        """The target frameworks the project builds: TargetFrameworks, else TargetFramework, else freestanding."""
        multi = self.prop("TargetFrameworks")
        if multi:
            return [f.strip().lower() for f in multi.split(";") if f.strip()]
        single = self.prop("TargetFramework")
        return [single.strip().lower()] if single else ["freestanding"]

    @property
    def runtime(self) -> str:
        """"Libc" when any build of the project targets libc (it links the C library), else "Freestanding"."""
        return "Libc" if "libc" in self.frameworks else "Freestanding"

    @property
    def libc_only(self) -> bool:
        """True when every build targets libc, so a freestanding project cannot reference it (NU1201)."""
        return all(f == "libc" for f in self.frameworks)

    @property
    def package_id(self) -> str:
        """The name NuGet gives the project: PackageId, else AssemblyName, else the project name (as in .NET)."""
        return self.prop("PackageId") or self.prop("AssemblyName") or os.path.splitext(os.path.basename(self.path))[0]

    @property
    def produces_static(self) -> bool:
        """True when a referencing project will link a static library from this one."""
        return self.kind == "StaticLibrary" or (self.prop("AsmProduceStaticLibrary") or "").lower() == "true"

    @property
    def pic_required(self) -> bool:
        """True when Linux's linker rejects non-PIC code here: shared libraries and libc executables (PIEs)."""
        return self.kind == "SharedLibrary" or (self.kind == "Executable" and self.runtime == "Libc")

    @property
    def declared_rids(self) -> List[str]:
        """The RIDs the project lists itself, lower-cased: RuntimeIdentifiers, else a lone RuntimeIdentifier.

        Conditions are ignored, as everywhere here. Empty when the project names none (it
        then builds what its referencing projects ask for, or stops with ASM0010).
        """
        listed = " ;".join(v for v, _ in self.prop_entries("RuntimeIdentifiers"))
        if not listed.strip():
            listed = " ;".join(v for v, _ in self.prop_entries("RuntimeIdentifier"))
        return list(dict.fromkeys(r.strip().lower() for r in listed.split(";") if r.strip() and "$(" not in r))


@dataclass
class SourceInfo:
    """Facts extracted from one NASM file (comments removed, line numbers kept).

    line_oses maps each code line to (OSes, uncertain, in_macro): the platforms its %ifdef
    WINDOWS / LINUX / MACOS (and %ifidn __OUTPUT_FORMAT__) guards leave it assembled on,
    whether a guard the linter cannot read is involved (platform findings then become
    warnings), and whether the line is inside a %macro body (assembled only where the macro
    is used, so the per-format checks skip it).
    """

    path: str
    lines: List[Tuple[int, str]]
    default_rel: bool = False
    has_gnu_stack: bool = False
    includes: List[Tuple[int, str]] = field(default_factory=list)
    externs: Set[str] = field(default_factory=set)
    globals: Dict[str, Tuple[int, str]] = field(default_factory=dict)
    #: Every declaration of each global, in source order, as (line, qualifiers): a symbol written
    #: once per OS (hidden on Linux, private_extern on macOS, a plain global on Windows) has one
    #: per guard, and only together do they say whether it is meant to be internal. `globals`
    #: keeps the last declaration only, which is all the symbol-resolution checks need.
    global_decls: Dict[str, List[Tuple[int, str]]] = field(default_factory=dict)
    labels: Set[str] = field(default_factory=set)
    constants: Set[str] = field(default_factory=set)
    macro_symbols: Set[str] = field(default_factory=set)
    extern_oses: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    uses_asmsdk_inc: bool = False
    manual_exports: bool = False
    line_oses: Dict[int, Tuple[FrozenSet[str], bool, bool]] = field(default_factory=dict)


def visibility(qualifiers: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a `global` declaration's qualifiers into the visibility NASM applies and one it ignores.

    NASM 3.02 reads the visibility keyword only right after the type: `function hidden (size)`
    and `data hidden 8` hide the symbol, while `function (size) hidden` and `data 8 hidden`
    are accepted without any warning and leave it exported (verified).

    Args:
        qualifiers: Everything after the colon of `global name:...`, lower-case.

    Returns:
        (effective, ignored): effective is "hidden", "internal", "protected" or None; ignored is
        the keyword NASM drops because it follows the size, or None.
    """
    effective = re.match(r"^\s*(?:function|data|object|func|notype)?\s*(hidden|internal|protected)\b", qualifiers)
    if effective:
        return effective.group(1), None
    trailing = re.search(r"\b(hidden|internal|protected)\b", qualifiers)
    return None, trailing.group(1) if trailing else None


def _strip_ns(tag: str) -> str:
    """Drop an XML namespace ("{ns}PropertyGroup" -> "PropertyGroup"); old-style projects carry one.

    Args:
        tag: An ElementTree tag, possibly namespace-qualified.

    Returns:
        The local element name.
    """
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _element_lines(path: str) -> Dict[str, int]:
    """Map each property element name to the first line it appears on, for reporting.

    ElementTree drops line numbers, so the raw text is scanned for "<Name>" or "<Name ".

    Args:
        path: The project file.

    Returns:
        Element name -> 1-based line number of its first occurrence.
    """
    lines: Dict[str, int] = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for number, text in enumerate(f, 1):
            for match in re.finditer(r"<([A-Za-z_][\w.]*)[\s>/]", text):
                lines.setdefault(match.group(1), number)
    return lines


def parse_msbuild_file(path: str) -> Project:
    """Read an MSBuild file's properties and items as written.

    Args:
        path: An .asmproj, Directory.Build.props or similar file.

    Returns:
        A Project with props, items and the Sdk attribute ("" when absent).

    Raises:
        ValueError: The file is not well-formed XML (the message names the file and position).
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path}: not well-formed XML: {exc}") from exc
    project = Project(path=os.path.abspath(path), dir=os.path.dirname(os.path.abspath(path)),
                      sdk=root.get("Sdk", ""), prop_lines=_element_lines(path))
    for group in root:
        tag = _strip_ns(group.tag)
        group_condition = group.get("Condition", "")
        if tag == "PropertyGroup":
            for prop in group:
                name = _strip_ns(prop.tag)
                condition = " and ".join(c for c in (group_condition, prop.get("Condition", "")) if c)
                project.props.setdefault(name, []).append(((prop.text or ""), condition))
        elif tag == "ItemGroup":
            for item in group:
                attrs = dict(item.attrib)
                attrs["Condition"] = " and ".join(c for c in (group_condition, item.get("Condition", "")) if c)
                for child in item:  # metadata written as child elements
                    attrs[_strip_ns(child.tag)] = child.text or ""
                project.items.setdefault(_strip_ns(item.tag), []).append(attrs)
    return project


def strip_comment(line: str) -> str:
    """Remove a NASM comment (from ';' outside quotes) and trailing whitespace.

    Args:
        line: One source line.

    Returns:
        The code part. Quotes (', ", `) are honored so "a;b" in a string survives.
    """
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == ";":
            return line[:i].rstrip()
    return line.rstrip()


def _strip_strings(text: str) -> str:
    """Blank out quoted strings so identifiers inside them are not mistaken for symbols.

    Args:
        text: Code with comments already removed.

    Returns:
        The same code with each quoted string replaced by an empty '' literal, so operand
        positions and commas stay where they were.
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", "''", text)


def condition_oses(directive: str, argument: str) -> Optional[FrozenSet[str]]:
    """The OSes on which a NASM conditional is true, when the linter can tell.

    Args:
        directive: The directive without "%" and without the "el" of %elif forms, lower-case:
            "ifdef", "ifndef", "ifidn", "ifidni", "ifnidn", "ifnidni", "if", ...
        argument: The rest of the line.

    Returns:
        The OSes for which the condition holds; None when it does not depend on what the
        linter knows (a user macro, an arithmetic %if), which makes the block uncertain.
    """
    words = argument.replace(",", " ").split()
    if directive in ("ifdef", "ifndef") and words:
        name = words[0]
        if name in OS_DEFINES:
            on = OS_DEFINES[name]
        elif name in OS_NEUTRAL_DEFINES:
            on = ALL_OSES
        else:
            return None
        return on if directive == "ifdef" else (ALL_OSES - on if name not in OS_NEUTRAL_DEFINES and name != "MUSL" else ALL_OSES)
    if directive in ("ifidn", "ifidni", "ifnidn", "ifnidni") and len(words) >= 2:
        sides = [w.strip().lower() for w in words[:2]]
        fmt = next((s for s in sides if s in OUTPUT_FORMAT_OS), None)
        other = next((s for s in sides if s.strip("?").strip("_") == "output_format" or "output_format" in s), None)
        if fmt and other:
            on = frozenset({OUTPUT_FORMAT_OS[fmt]})
            return on if directive in ("ifidn", "ifidni") else ALL_OSES - on
    return None


def parse_source(path: str) -> SourceInfo:
    """Extract the facts the source checks need from one NASM file.

    Args:
        path: An .asm or .inc file.

    Returns:
        A SourceInfo. Unreadable bytes are replaced rather than failing the whole lint.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read().splitlines()
    info = SourceInfo(path=path, lines=[])
    in_struc = False
    # The conditional-assembly state: the OSes the current line is assembled on, whether an
    # unreadable condition is involved, and one frame per open %if (the OSes before it, its
    # uncertainty, and the OSes its branches took so far: None once a branch was unreadable).
    active: FrozenSet[str] = ALL_OSES
    uncertain = False
    frames: List[Tuple[FrozenSet[str], bool, Optional[FrozenSet[str]]]] = []
    macro_depth = 0
    for number, text in enumerate(raw, 1):
        code = strip_comment(text)
        if not code.strip():
            continue
        stripped = code.strip()
        low = stripped.lower()
        directive = re.match(r"^%(el)?(if\w*|else|endif)\b(.*)$", low)
        if directive:
            elif_, word, rest = directive.group(1), directive.group(2), code.strip()[len(directive.group(0)) - len(directive.group(3)):]
            if word == "endif":
                if frames:
                    active, uncertain, _ = frames.pop()
            elif word == "else":
                if frames:
                    parent, parent_uncertain, taken = frames[-1]
                    active = parent - taken if taken is not None else parent
                    uncertain = parent_uncertain or taken is None
            elif elif_:
                if frames:
                    parent, parent_uncertain, taken = frames[-1]
                    on = condition_oses(word, rest)
                    if on is not None and taken is not None:
                        active, uncertain = parent & (on - taken), parent_uncertain
                        frames[-1] = (parent, parent_uncertain, taken | on)
                    else:
                        active = parent - taken if taken is not None else parent
                        uncertain = True
                        frames[-1] = (parent, parent_uncertain, None)
            else:
                on = condition_oses(word, rest)
                frames.append((active, uncertain, on))
                if on is not None:
                    active = active & on
                else:
                    uncertain = True
            info.lines.append((number, code))
            info.line_oses[number] = (active, uncertain, macro_depth > 0)
            continue
        if re.match(r"^%i?macro\b", low):
            macro_depth += 1
        elif re.match(r"^%endmacro\b", low):
            macro_depth = max(0, macro_depth - 1)
        info.lines.append((number, code))
        info.line_oses[number] = (active, uncertain, macro_depth > 0)
        if re.match(r"^\[?\s*default\s+rel\b", low):
            info.default_rel = True
        if re.match(r"^\[?\s*(section|segment)\s+\.note\.gnu-stack\b", low):
            info.has_gnu_stack = True
        if re.match(r"^\[?\s*(section|segment)\s+\.drectve\b", low):
            info.manual_exports = True
        m = re.match(r'^\s*%include\s+["<](.+?)[">]', code)
        if m:
            info.includes.append((number, m.group(1)))
            if os.path.basename(m.group(1)).lower() == "asmsdk.inc":
                info.uses_asmsdk_inc = True
            continue
        if re.match(r"^\s*struc\b", low):
            in_struc = True
        elif re.match(r"^\s*endstruc\b", low):
            in_struc = False
        # asmsdk.inc's FUNCTION, LOCAL_FUNCTION and HIDDEN_FUNCTION define the label and write
        # each format's directives themselves (exported, file-local, global but exported from
        # no image). NASM macro names are case-sensitive, as the SDK spells them.
        m = re.match(rf"^\s*({'|'.join(ASMSDK_FUNCTION_MACROS)})\s+({IDENT})", code)
        if m and macro_depth == 0:
            name = m.group(2).lstrip("$")
            info.labels.add(name)
            info.macro_symbols.add(name)
            if m.group(1) == "FUNCTION":
                info.globals[name] = (number, "function")
                info.global_decls.setdefault(name, []).append((number, "function"))
            elif m.group(1) == "HIDDEN_FUNCTION":
                info.globals[name] = (number, "function hidden")
                info.global_decls.setdefault(name, []).append((number, "function hidden"))
            continue
        m = re.match(r"^\s*\[?\s*extern\s+(.+?)\]?\s*$", code, re.IGNORECASE)
        if m:
            for name in m.group(1).split(","):
                symbol = name.split(":")[0].strip().lstrip("$")
                info.externs.add(symbol)
                # An extern under %ifdef WINDOWS (kernel32's ExitProcess) is an import on
                # Windows only: the undefined-symbol check must not judge it for Linux.
                info.extern_oses[symbol] = info.extern_oses.get(symbol, frozenset()) | active
            continue
        m = re.match(r"^\s*\[?\s*global\s+(.+?)\]?\s*$", code, re.IGNORECASE)
        if m:
            # "global a:function hidden, b" -> each name with its qualifiers.
            for part in re.split(r",(?![^()]*\))", m.group(1)):
                name, _, qualifiers = part.strip().partition(":")
                info.globals[name.strip().lstrip("$")] = (number, qualifiers.strip().lower())
                info.global_decls.setdefault(name.strip().lstrip("$"), []).append((number, qualifiers.strip().lower()))
            continue
        m = re.match(rf"^\s*({IDENT})\s*:", code)
        if m and not code.lstrip().startswith("%"):
            (info.constants if in_struc else info.labels).add(m.group(1).lstrip("$"))
            continue
        m = re.match(rf"^\s*({IDENT})\s+(\w+)\b", code)
        if m and not code.lstrip().startswith("%"):
            word = m.group(2).lower()
            if word == "equ":
                info.constants.add(m.group(1).lstrip("$"))
            elif word in DATA_DIRECTIVES + RES_DIRECTIVES or word == "times":
                (info.constants if in_struc else info.labels).add(m.group(1).lstrip("$"))
        m = re.match(rf"^\s*%(?:x?i?define|assign)\s+({IDENT})", code, re.IGNORECASE)
        if m:
            info.constants.add(m.group(1))
    return info


def _walk_files(folder: str, pattern: str) -> List[str]:
    """Find files by extension under a folder, skipping bin/, obj/ and tool folders.

    Args:
        folder: Root folder.
        pattern: Extension including the dot, such as ".asm".

    Returns:
        Absolute paths, sorted for stable output.
    """
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        found.extend(os.path.join(root, f) for f in files if f.lower().endswith(pattern))
    return sorted(os.path.abspath(p) for p in found)


def _resolve_item_paths(project: Project, include: str) -> List[str]:
    """Expand an item Include (relative path or glob, ';'-separated) against the project folder.

    Args:
        project: The project the item belongs to.
        include: The Include attribute; MSBuild properties ($(X)) are not evaluated, so parts
            that contain them are skipped.

    Returns:
        Absolute, normalized paths that exist (globs) or are named (plain paths).
    """
    paths = []
    for part in include.split(";"):
        part = part.strip().replace("\\", "/")
        if not part or "$(" in part or "@(" in part:
            continue
        full = os.path.normpath(os.path.join(project.dir, part))
        if any(ch in part for ch in "*?"):
            paths.extend(os.path.normpath(p) for p in glob.glob(full, recursive=True))
        else:
            paths.append(full)
    return paths


def project_sources(project: Project) -> Tuple[List[str], List[str]]:
    """Compute the project's NASM sources and include files the way the SDK's defaults do.

    Args:
        project: The project.

    Returns:
        (NASM sources, include files) as absolute paths: default globs (unless
        EnableDefaultAsmItems=false) plus explicit Include items, minus Remove items. GNU
        syntax sources (.s) are in project_all_sources.
    """
    sources, includes = [], []
    for path in project_all_sources(project):
        if path.lower().endswith(".asm"):
            sources.append(path)
    defaults = (project.prop("EnableDefaultAsmItems") or "true").lower() != "false"
    includes = _walk_files(project.dir, ".inc") if defaults else []
    for item in project.items.get("AsmInclude", []):
        includes.extend(_resolve_item_paths(project, item.get("Include", "")))
    return sources, list(dict.fromkeys(os.path.normpath(p) for p in includes))


def project_all_sources(project: Project) -> List[str]:
    """Every AsmSource of the project, NASM (.asm) and GNU syntax (.s), as the SDK collects them.

    Since 0.3.0 the default sources are **/*.asm and **/*.s.

    Args:
        project: The project.

    Returns:
        Absolute paths: default globs (unless EnableDefaultAsmItems=false), explicit Include
        items, minus Remove items, de-duplicated (a duplicate is ASM0024 in the SDK, reported
        separately).
    """
    defaults = (project.prop("EnableDefaultAsmItems") or "true").lower() != "false"
    sources = (_walk_files(project.dir, ".asm") + _walk_files(project.dir, ".s")) if defaults else []
    for item in project.items.get("AsmSource", []):
        sources.extend(_resolve_item_paths(project, item.get("Include", "")))
    removed = set()
    for item in project.items.get("AsmSource", []):
        removed.update(os.path.normcase(p) for p in _resolve_item_paths(project, item.get("Remove", "")))
    return [s for s in dict.fromkeys(os.path.normpath(p) for p in sources) if os.path.normcase(s) not in removed]


def include_dirs(project: Project, referenced: List[Project]) -> List[Tuple[str, str]]:
    """The include search order NASM will see, as (folder, origin) pairs.

    NASM 3.02 tries the working directory (the project folder) first, then each -I folder:
    include/, the project folder, AsmIncludeDirectory items, then referenced projects'
    public folders (include/ or their project folder). The SDK's own include folder
    (asmsdk.inc, asmsdk-gnu.inc) comes last; it is not on disk here, so asmsdk.inc is treated
    as found.

    Args:
        project: The project being assembled.
        referenced: The .asmproj projects it references (transitively flattened by caller).

    Returns:
        Ordered (absolute folder, origin) pairs; origin is "local", "item" or the project name.
    """
    dirs = [(project.dir, "local")]
    if os.path.isdir(os.path.join(project.dir, "include")):
        dirs.append((os.path.join(project.dir, "include"), "local"))
    for item in project.items.get("AsmIncludeDirectory", []):
        for path in _resolve_item_paths(project, item.get("Include", "")):
            dirs.append((path, "item"))
    for ref in referenced:
        inc = os.path.join(ref.dir, "include")
        dirs.append((inc if os.path.isdir(inc) else ref.dir, os.path.basename(ref.path)))
    return dirs


def describe_oses(oses: Iterable[str]) -> str:
    """Name a set of platforms for a message: "macOS (macho64) and Windows (win64)".

    Args:
        oses: OS names from OSES.

    Returns:
        The labels in OSES order, joined with commas and "and".
    """
    labels = [OS_LABEL[o] for o in OSES if o in set(oses)]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


#: The binary formats of WebAssembly's float constants, IEEE 754 binary32 and binary64:
#: (significand bits with the implicit one, the least exponent of a normal number, the greatest).
WASM_FLOAT_FORMATS: Dict[str, Tuple[int, int, int]] = {"f32": (24, -126, 127), "f64": (53, -1022, 1023)}

#: A hex float as llvm-mc 23.1.5's lexer reads one (0x1.ae147ap-2, -0X1P-2); the p exponent is
#: required. A leading + is no sign there: "Unexpected token in operand: +".
WASM_HEX_FLOAT = re.compile(r"^-?0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][+-]?\d+$")

#: A decimal float as the lexer reads one: a point or an exponent makes a real (1.0, .5, 5.,
#: 1e3, 1.25e-1); digits alone are an integer.
WASM_DECIMAL_FLOAT = re.compile(r"^-?(?:\d+\.\d*|\.\d+|\d+(?=[eE]))(?:[eE][+-]?\d+)?$")

#: An integer (decimal or hex), which a float operand refuses: "invalid operand for instruction".
WASM_INTEGER = re.compile(r"^-?(?:0[xX][0-9a-fA-F]+|\d+)$")

#: Exponents beyond this are outside every float's range by thousands of binary places; the
#: exact arithmetic below skips them rather than build 10**exponent for a pathological literal.
WASM_FLOAT_EXPONENT_LIMIT = 4000


def float_literal_value(text: str) -> Optional[Fraction]:
    """The exact value a decimal or hex float literal writes, before any rounding.

    Args:
        text: A literal WASM_DECIMAL_FLOAT or WASM_HEX_FLOAT matches.

    Returns:
        Its value as a fraction (0.1 is 1/10, not the double nearest it), or None when its
        exponent passes WASM_FLOAT_EXPONENT_LIMIT (the caller then judges nothing).
    """
    negative = text.startswith("-")
    body = text.lstrip("-").lower()
    hexadecimal = body.startswith("0x")
    mantissa, _, power_text = (body[2:].partition("p") if hexadecimal else body.partition("e"))
    power = int(power_text or "0")
    if abs(power) > WASM_FLOAT_EXPONENT_LIMIT:
        return None
    whole, _, fraction = mantissa.partition(".")
    if hexadecimal:
        # Each hex digit after the point is a sixteenth; the p exponent is a power of two.
        value = Fraction(int((whole + fraction) or "0", 16), 16 ** len(fraction)) * Fraction(2) ** power
    else:
        value = Fraction(int((whole + fraction) or "0")) * Fraction(10) ** (power - len(fraction))
    return -value if negative else value


def nearest_float(value: Fraction, kind: str) -> Optional[Fraction]:
    """The f32 or f64 nearest a value, ties to even, as IEEE 754 rounds.

    llvm-mc rounds an f32 operand this way from the double it read, without a word (measured:
    16777217.0 was stored as 16777216.0, 16777219.0 as 16777220.0, 0x1p-150 as zero and
    0x1p200 as infinity).

    Args:
        value: Any exact value.
        kind: "f32" or "f64".

    Returns:
        The nearest value the format holds (a subnormal, or zero, below its normal range), or
        None when the value rounds to infinity.
    """
    if value == 0:
        return Fraction(0)
    precision, least, greatest = WASM_FLOAT_FORMATS[kind]
    magnitude = abs(value)
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if Fraction(2) ** exponent > magnitude:
        exponent -= 1                       # now 2**exponent <= magnitude < 2**(exponent + 1)
    # The weight of the last significand bit: precision - 1 places below the leading one, and
    # never finer than the smallest subnormal's (the format's least exponent caps it).
    quantum = max(exponent, least) - (precision - 1)
    scaled = magnitude / Fraction(2) ** quantum
    whole, rest = divmod(scaled.numerator, scaled.denominator)
    if 2 * rest > scaled.denominator or (2 * rest == scaled.denominator and whole % 2 == 1):
        whole += 1                          # rounding up may carry into the next binade: still exact
    rounded = Fraction(whole) * Fraction(2) ** quantum
    if rounded >= Fraction(2) ** (greatest + 1):
        return None
    return rounded if value > 0 else -rounded


def wasm_float_lexes_as_octal(text: str) -> bool:
    """Whether llvm-mc's lexer splits a decimal float into an octal integer and another token.

    LLVM's AsmLexer reads a number that starts with 0 as a decimal float only when a point comes
    right after that 0 (0.5, 0.0e1); otherwise the 0 starts an octal integer (measured: 00.5,
    06., -01.0, 0e0 and 01e3 stop with "Expected ,, instead got: .5" and the like, 08.0 and 09.5
    with "Unexpected token in operand"). This runs before the value is parsed, so it decides
    first. Hex floats are not affected (0x01p0 assembles).

    Args:
        text: A literal WASM_DECIMAL_FLOAT or WASM_HEX_FLOAT matches.

    Returns:
        True for a decimal whose leading 0 no point follows.
    """
    body = text.lstrip("-")
    return not WASM_HEX_FLOAT.match(text) and body.startswith("0") and body[1:2] != "."


def llvm_mc_reads_float(text: str) -> bool:
    """Whether llvm-mc 23.1.5's WebAssembly parser takes a literal as a float operand.

    The parser asks LLVM's APFloat for a double and refuses any conversion APFloat reports
    inexact ("Cannot parse real"). A hex float converts exactly, so it passes when its value is
    a double. A decimal is worked out from its significant digits as an integer held in 63 bits,
    and only a conversion that never rounded counts as exact, so it passes when its value is a
    double AND those digits need 63 significant bits or fewer. Before that, the lexer reads a
    decimal that starts with a 0 no point follows (00.5, 06., 0e0) as an octal integer and the
    rest as another token. Measured: 0.5, 3.75, 1e3, 1.25e-1, 2^62 and 2^-27 written out in full
    (its digits are 5^27, 63 bits) pass; 0.1 and 0.42 (no double), 2^53 + 1, 2^-28 in full (5^28,
    65 bits) and the f32 nearest 0.42 in full (0.4199999868869781494140625: a double, 82 bits of
    digits) do not. On 9,000 random literals (three seeds), each as f32.const and as f64.const,
    every acceptance and every stored bit came out as this rule and nearest_float predict, and
    each of the 7,388 replacements wasm_float_literal gave for a refused one assembled to the
    nearest value.

    Args:
        text: A literal WASM_DECIMAL_FLOAT or WASM_HEX_FLOAT matches.

    Returns:
        True when the parser takes it (an f32 operand is then rounded from that double:
        nearest_float); False when assembling stops ("Cannot parse real", or for a leading 0 a
        token error such as "Expected ,, instead got: .5").
    """
    if wasm_float_lexes_as_octal(text):
        return False
    value = float_literal_value(text)
    if value is None or nearest_float(value, "f64") != value:
        return False
    if WASM_HEX_FLOAT.match(text):
        return True
    # APFloat drops the leading and trailing zeros: 0.4250 is the digits 425 at some exponent.
    digits = int(text.lstrip("-").lower().partition("e")[0].replace(".", "").strip("0") or "0")
    if digits == 0:
        return True
    # Significant bits: from the highest one to the lowest one (trailing zero bits cost nothing).
    lowest_one = (digits & -digits).bit_length() - 1
    return (digits >> lowest_one).bit_length() <= 63


def hex_float(magnitude: Fraction) -> str:
    """A positive binary value as a C99 hex float with no trailing zero digits.

    This is the form llvm-mc's WebAssembly printer writes (APFloat's convertToHexString), and
    one its parser reads exactly whenever the value is a double.

    Args:
        magnitude: A positive value whose denominator is a power of two.

    Returns:
        "0x1.<hex digits>p<exponent>" (0x1.ae147ap-2), or "0x1p<exponent>" for a power of two.
    """
    numerator, denominator = magnitude.numerator, magnitude.denominator
    top = numerator.bit_length() - 1                        # the leading one's place
    exponent = top - (denominator.bit_length() - 1)
    digits = (top + 3) // 4                                 # the bits after the leading one, in hex
    fraction = (numerator - (1 << top)) << (4 * digits - top)
    text = format(fraction, f"0{digits}x").rstrip("0") if digits else ""
    return f"0x1.{text}p{exponent}" if text else f"0x1p{exponent}"


def wasm_float_literal(value: Optional[Fraction], negative: bool) -> str:
    """A literal llvm-mc reads as exactly a given f32 or f64 value.

    Args:
        value: nearest_float's result: a value the format holds, or None for infinity.
        negative: Whether the value written was negative (it signs zero and infinity, which the
            value alone cannot).

    Returns:
        "infinity" (the name the parser knows: it refuses "inf"), a decimal of at most 9
        significant digits when one is read exactly (1.0, 0.25, 16777216.0), else the hex float
        (0x1.ae147ap-2); each with a minus when negative.
    """
    sign = "-" if negative else ""
    if value is None:
        return sign + "infinity"
    if value == 0:
        return sign + "0.0"
    magnitude = abs(value)
    places = magnitude.denominator.bit_length() - 1         # value = numerator / 2**places
    digits = str(magnitude.numerator * 5 ** places)         # = digits / 10**places, exactly
    if places:
        digits = digits.rjust(places + 1, "0")
        decimal = f"{digits[:-places]}.{digits[-places:]}"
    else:
        decimal = f"{digits}.0"
    if len(decimal.replace(".", "").strip("0")) <= 9 and llvm_mc_reads_float(decimal):
        return sign + decimal
    return sign + hex_float(magnitude)


class Linter:
    """Runs every check over a set of projects and collects Findings.

    One instance per run: it caches parsed projects and sources so a library referenced by
    several projects is read once, and it learns which RIDs a RID-less project inherits from
    the projects that reference it (index_referrers).
    """

    def __init__(self) -> None:
        self.findings: List[Finding] = []
        self._projects: Dict[str, Project] = {}
        self._sources: Dict[str, SourceInfo] = {}
        self._reported: Set[Tuple[str, str, int]] = set()
        self._referrer_rids: Dict[str, Set[str]] = {}
        self._symbol_lists: Optional[Dict[str, Set[str]]] = None

    # -- infrastructure ---------------------------------------------------------------------

    def add(self, severity: str, code: str, path: str, line: int, message: str, fix: str = "") -> None:
        """Record a finding once (the same code at the same place is reported once).

        Args:
            severity: "error", "warning" or "info".
            code: Stable identifier, such as "ASMPIC001".
            path: File the finding is about.
            line: 1-based line, or 0 for a whole-file finding.
            message: What is wrong and what it causes.
            fix: How to fix it.
        """
        key = (code, os.path.normcase(path), line)
        if key not in self._reported:
            self._reported.add(key)
            self.findings.append(Finding(severity, code, path, line, message, fix))

    def project(self, path: str) -> Optional[Project]:
        """Parse (once) and return a project; a broken file becomes a finding, not a crash.

        Args:
            path: An .asmproj path.

        Returns:
            The Project, or None when the file is missing or not well-formed.
        """
        key = os.path.normcase(os.path.abspath(path))
        if key not in self._projects:
            if not os.path.isfile(path):
                return None
            try:
                self._projects[key] = parse_msbuild_file(path)
            except ValueError as exc:
                self.add("error", "ASMPRJ000", path, 0, str(exc))
                return None
        return self._projects[key]

    def source(self, path: str) -> SourceInfo:
        """Parse (once) and return a NASM file; shared libraries' sources are read once per run.

        Args:
            path: An existing .asm or .inc file.

        Returns:
            Its SourceInfo.

        Raises:
            OSError: The file cannot be opened (callers check existence first).
        """
        key = os.path.normcase(path)
        if key not in self._sources:
            self._sources[key] = parse_source(path)
        return self._sources[key]

    def references(self, project: Project, seen: Optional[Set[str]] = None) -> List[Project]:
        """All .asmproj projects a project references, transitively (the .NET SDK flows them).

        Args:
            project: The referencing project.
            seen: Visited set for cycle safety (callers omit it).

        Returns:
            Referenced projects, direct ones first.
        """
        seen = seen if seen is not None else {os.path.normcase(project.path)}
        result = []
        for item in project.items.get("ProjectReference", []):
            for path in _resolve_item_paths(project, item.get("Include", "")):
                if not path.lower().endswith(".asmproj") or os.path.normcase(path) in seen:
                    continue
                seen.add(os.path.normcase(path))
                ref = self.project(path)
                if ref is None:
                    self.add("error", "ASMREF000", project.path, project.prop_lines.get("ProjectReference", 0),
                             f"ProjectReference to a missing project: {path}", "fix the path")
                    continue
                result.append(ref)
                result.extend(self.references(ref, seen))
        return result

    def index_referrers(self, projects: List[Project]) -> None:
        """Record, for every referenced project, the RIDs its referencing projects declare.

        A project that names no RID is built for what its referencing projects ask for, so
        its sources are judged for those RIDs. Must run before check_project.

        Args:
            projects: Every project of the run (their references are followed transitively).
        """
        for project in projects:
            declared = [r for r in project.declared_rids if r in RIDS]
            if not declared:
                continue
            for ref in self.references(project):
                self._referrer_rids.setdefault(os.path.normcase(ref.path), set()).update(declared)

    def effective_rids(self, project: Project) -> Tuple[List[str], bool]:
        """The RIDs a project's sources are judged for.

        Args:
            project: The project.

        Returns:
            (rids, assumed): its own known RIDs; else those of the projects that reference it;
            else all seven native RIDs with assumed=True (nothing here says which RIDs it
            builds, so platform-specific findings are warnings), plus the WebAssembly RIDs when
            the project holds a source qualified for them.
        """
        own = [r for r in project.declared_rids if r in RIDS]
        if own:
            return own, False
        inherited = self._referrer_rids.get(os.path.normcase(project.path))
        if inherited:
            return sorted(inherited), False
        wasm = [r for r in RIDS if RIDS[r][1] == "wasm"
                and any(source_score(s, r) > 0 for s in project_all_sources(project))]
        return NATIVE_RIDS + wasm, True

    def symbol_lists(self, project: Project) -> Dict[str, Set[str]]:
        """The SDK's macOS and Windows C library lists, read once per run (see load_sdk_symbol_lists).

        Args:
            project: A project whose global.json names the SDK version.

        Returns:
            The lists found (possibly none).
        """
        if self._symbol_lists is None:
            version = self._pinned_version(project) or DOCUMENTED_SDK_VERSION
            self._symbol_lists = load_sdk_symbol_lists(version)
        return self._symbol_lists

    def _pinned_version(self, project: Project) -> Optional[str]:
        """The AsmFoundation.Sdk version the nearest global.json (or the Sdk attribute) pins.

        Args:
            project: The project.

        Returns:
            The version, or None when none is readable.
        """
        if "/" in project.sdk:
            return project.sdk.split("/", 1)[1]
        folder = project.dir
        while True:
            candidate = os.path.join(folder, "global.json")
            if os.path.isfile(candidate):
                try:
                    with open(candidate, encoding="utf-8-sig") as f:
                        return ((json.load(f).get("msbuild-sdks") or {}).get("AsmFoundation.Sdk"))
                except (OSError, json.JSONDecodeError):
                    return None
            parent = os.path.dirname(folder)
            if parent == folder:
                return None
            folder = parent

    # -- repository-level checks --------------------------------------------------------------

    def check_global_json(self, project: Project) -> None:
        """global.json must name AsmFoundation.Sdk unless the Sdk attribute carries a version.

        The nearest global.json above the project is the one `dotnet` uses, so only that one
        is judged; a missing entry means MSB4236 before anything builds.

        Args:
            project: The project whose SDK resolution is checked.
        """
        if "/" in project.sdk:  # Sdk="AsmFoundation.Sdk/0.3.0" needs no global.json entry
            return
        folder = project.dir
        while True:
            candidate = os.path.join(folder, "global.json")
            if os.path.isfile(candidate):
                try:
                    with open(candidate, encoding="utf-8-sig") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError) as exc:
                    self.add("error", "ASMSLN001", candidate, 0, f"global.json is not valid JSON: {exc}")
                    return
                version = (data.get("msbuild-sdks") or {}).get("AsmFoundation.Sdk")
                if not version:
                    self.add("error", "ASMSLN001", candidate, 0,
                             "global.json has no msbuild-sdks entry for AsmFoundation.Sdk, so the SDK cannot resolve (MSB4236)",
                             f'"msbuild-sdks": {{ "AsmFoundation.Sdk": "{DOCUMENTED_SDK_VERSION}" }}')
                elif version != DOCUMENTED_SDK_VERSION:
                    self.add("info", "ASMSLN003", candidate, 0,
                             f"pins AsmFoundation.Sdk {version}; these checks encode {DOCUMENTED_SDK_VERSION}",
                             "check that release's docs/asmproj.md where behavior differs")
                return
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        self.add("error", "ASMSLN001", project.path, 1,
                 "no global.json above the project names AsmFoundation.Sdk, so the SDK cannot resolve (MSB4236)",
                 f'add global.json: {{ "msbuild-sdks": {{ "AsmFoundation.Sdk": "{DOCUMENTED_SDK_VERSION}" }} }}')

    def check_slnx(self, path: str) -> None:
        """Every .asmproj entry in a .slnx needs the generic MSBuild type GUID.

        Args:
            path: The .slnx file; a malformed file becomes a finding rather than an exception.
        """
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            self.add("error", "ASMSLN002", path, 0, f"not well-formed XML: {exc}")
            return
        lines = open(path, encoding="utf-8-sig", errors="replace").read().splitlines()
        for element in root.iter():
            if _strip_ns(element.tag) == "Project" and element.get("Path", "").lower().endswith(".asmproj"):
                if (element.get("Type") or "").strip("{}").upper() != ASMPROJ_TYPE_GUID:
                    line = next((i for i, l in enumerate(lines, 1) if element.get("Path") in l), 0)
                    self.add("error", "ASMSLN002", path, line,
                             f"{element.get('Path')} has no project type: dotnet build fails with MSB4025 \"ProjectType '' not found\"",
                             f'add Type="{ASMPROJ_TYPE_GUID}"')

    # -- project-level checks -----------------------------------------------------------------

    def check_project(self, project: Project) -> None:
        """Run the project-file checks and then the source checks for one project.

        Args:
            project: The parsed project; its references are parsed on demand.
        """
        p = project
        line = p.prop_lines.get
        rids, assumed = self.effective_rids(p)
        oses = {RIDS[r][0] for r in rids}
        toolchain = p.prop("AsmToolchain")
        if toolchain and toolchain not in ("Bundled", "System"):
            self.add("error", "ASMPRJ009", p.path, line("AsmToolchain", 0),
                     f"AsmToolchain='{toolchain}' fails with ASM0002", "use Bundled or System")
        output_type = p.prop("OutputType")
        if output_type and output_type.lower() not in ("library", "staticlibrary", "exe", "winexe", "objects"):
            self.add("warning", "ASMPRJ010", p.path, line("OutputType", 0),
                     f"OutputType='{output_type}' is not an AsmSdk kind; it builds a shared library",
                     "Library, StaticLibrary, Exe or Objects")
        # 0.1.0's own names: 0.2.0 and later fail the build with ASM0100-ASM0108, one error per setting.
        for name, replacement in REMOVED_SETTINGS.items():
            if p.prop_entries(name):
                self.add("error", "ASMPRJ013", p.path, line(name, 0),
                         f"{name} was removed in AsmFoundation.Sdk 0.2.0: the build fails with an ASM01xx error",
                         f"use {replacement}")
        if p.item_entries("AsmDefine"):
            self.add("error", "ASMPRJ013", p.path, line("AsmDefine", 0),
                     "AsmDefine items were removed in AsmFoundation.Sdk 0.2.0: the build fails with an ASM01xx error",
                     "list the symbols in DefineConstants (NAME or NAME=VALUE, semicolon-separated)")
        # 0.2.0's platform settings: 0.3.0 no longer reads them, so the project names no RID.
        for name, replacement in REMOVED_IN_030.items():
            if p.prop_entries(name):
                self.add("error", "ASMPRJ013", p.path, line(name, 0),
                         f"{name} was removed in AsmFoundation.Sdk 0.3.0 and is ignored: without RuntimeIdentifiers the build stops with ASM0010",
                         f"use {replacement}")
        self._check_runtime_identifiers(p)
        # Target frameworks are AsmSdk's two names only: a .NET name (netstandard2.0, the hidden
        # default of 0.1.0) or a typo stops the build with ASM0003.
        for framework in p.frameworks:
            if "$(" not in framework and framework not in ("freestanding", "libc"):
                self.add("error", "ASMPRJ018", p.path, line("TargetFrameworks", line("TargetFramework", 0)),
                         f"TargetFramework '{framework}' is not an AsmSdk target framework: the build stops with ASM0003",
                         "freestanding (no C library; the default) or libc (the platform's C library), or TargetFrameworks=freestanding;libc")
        if p.libc_only and p.kind in ("StaticLibrary", "Objects"):
            self.add("info", "ASMPRJ011", p.path, line("TargetFramework", 0),
                     f"TargetFramework=libc links nothing into {p.kind}, but it says the code needs the C library: "
                     "a freestanding project cannot reference this one (NU1201)",
                     "keep it when the code calls the C library; otherwise freestanding (or TargetFrameworks=freestanding;libc) lets every project use it")
        # On Linux and Windows the SDK's startup code initializes the C library; macOS's dyld
        # does that itself and calls StartupObject as main.
        if p.runtime == "Libc" and p.kind == "Executable" and p.prop("StartupObject") and oses & {"Linux", "Windows"}:
            self.add("warning", "ASMPRJ012", p.path, line("StartupObject", 0),
                     "StartupObject on a libc executable drops the SDK's startup code on Linux and Windows: "
                     "the C library is never initialized unless your entry does it (__libc_start_main on Linux)",
                     "remove StartupObject and define main")
        for item in p.item_entries("LinkerArg"):
            value, condition = item.get("Include", ""), item.get("Condition", "")
            if "$ORIGIN" in value and "IsOSPlatform" not in condition and "'$ORIGIN'" not in value:
                self.add("warning", "ASMPRJ006", p.path, line("LinkerArg", 0),
                         "$ORIGIN unquoted: Linux/macOS build machines run the link through /bin/sh, which expands it to nothing",
                         "add it per OS: -rpath $ORIGIN on Windows, -rpath '$ORIGIN' elsewhere (IsOSPlatform conditions on the LinkerArg items)")
        props_file = self._directory_build_props(p)
        flags = " ".join(v for v, _ in p.prop_entries("AsmFlags")) + " " + " ".join(
            v for v, _ in (props_file.prop_entries("AsmFlags") if props_file else []))
        if "-Xvc" in flags:
            self.add("info", "ASMPRJ008", p.path, line("AsmFlags", 0),
                     "AsmFlags -Xvc is redundant: since 0.3.0 the SDK passes -Xvc to NASM itself, so its messages are MSBuild errors and warnings with file and line",
                     "remove -Xvc from AsmFlags")
        link_flags = " ".join(i.get("Include", "") for i in p.item_entries("LinkerArg")) + " " + " ".join(
            i.get("Include", "") for i in (props_file.item_entries("LinkerArg") if props_file else []))
        # Only ELF links a shared library with undefined symbols; lld-link and ld64.lld refuse.
        if p.kind == "SharedLibrary" and "Linux" in oses and "-z defs" not in link_flags and "--no-undefined" not in link_flags:
            self.add("info", "ASMPRJ007", p.path, 0,
                     "a Linux shared library links with undefined symbols; a misspelled extern fails only when the library loads",
                     '<LinkerArg Include="-z defs" Condition="$(RuntimeIdentifier.StartsWith(\'linux-\'))" />')
        referenced = self.references(p)
        # NuGet names each project of a restore graph by its PackageId, which defaults to the
        # AssemblyName: two projects of one graph with the same name fail restore.
        names: Dict[str, List[Project]] = {}
        for member in [p] + referenced:
            names.setdefault(member.package_id.lower(), []).append(member)
        for same in names.values():
            if len(same) > 1:
                self.add("error", "ASMPRJ014", p.path, line("ProjectReference", 0),
                         f"{', '.join(os.path.basename(m.path) for m in same)} are all named '{same[0].package_id}' to NuGet "
                         "(PackageId defaults to AssemblyName): restore fails with \"Ambiguous project name\"",
                         "give each project its own <PackageId>; the file names still follow AssemblyName")
        for ref in referenced:
            if "freestanding" in p.frameworks and ref.libc_only and ref.kind != "Objects":
                self.add("error", "ASMREF003", p.path, line("ProjectReference", 0),
                         f"a freestanding build references {os.path.basename(ref.path)}, which targets only libc: restore fails with NU1201",
                         "make this project libc, or let the reference also build freestanding (TargetFrameworks=freestanding;libc)")
            # A Linux freestanding program links -static; Windows links a DLL's import library.
            if (p.kind == "Executable" and "freestanding" in p.frameworks and "Linux" in oses
                    and not ref.produces_static and ref.kind == "SharedLibrary"):
                self.add("error", "ASMREF001", p.path, line("ProjectReference", 0),
                         f"a freestanding Linux executable links -static, but {os.path.basename(ref.path)} produces only a .so: 'attempted static link of dynamic object'",
                         f"in {os.path.basename(ref.path)}: <AsmProduceStaticLibrary>true</AsmProduceStaticLibrary> or OutputType StaticLibrary")
        for item in p.items.get("AsmIncludeDirectory", []):
            for folder in _resolve_item_paths(p, item.get("Include", "")):
                inside = os.path.normcase(folder).startswith(os.path.normcase(p.dir) + os.sep)
                if inside or item.get("AsmOrigin"):
                    continue
                tracked = any(os.path.normcase(i).startswith(os.path.normcase(folder.rstrip("\\/")) + os.sep)
                              for i in project_sources(p)[1])
                if not tracked:
                    self.add("warning", "ASMPRJ002", p.path, line("AsmIncludeDirectory", 0),
                             f"include folder outside the project ({item.get('Include')}) is not a build dependency: editing its files leaves stale objects",
                             f'<AsmInclude Include="{item.get("Include").rstrip("/")}/**/*.inc" />')
        self._check_public_includes(p)
        self._check_wasm_project(p, rids)
        self.check_sources(p, referenced)

    def _check_runtime_identifiers(self, p: Project) -> None:
        """The 0.3.0 RID rules: a list to build, RIDs AsmSdk knows, no freestanding macOS program.

        Args:
            p: The project.
        """
        line = p.prop_lines.get
        declared = p.declared_rids
        where = line("RuntimeIdentifiers", line("RuntimeIdentifier", 0))
        if not declared:
            top_level = p.kind in ("SharedLibrary", "Executable")
            inherited = self._referrer_rids.get(os.path.normcase(p.path))
            if not inherited:
                self.add("warning" if top_level else "info", "ASMPRJ015", p.path, 0,
                         "names no RuntimeIdentifiers: built alone it stops with ASM0010; it builds only the RIDs a referencing project asks for "
                         "(a .NET app's RID, or RuntimeIdentifiers on the ProjectReference)",
                         "<RuntimeIdentifiers>win-x64;linux-x64;osx-arm64</RuntimeIdentifiers> (any of: " + ", ".join(RIDS) + ")"
                         + ("" if top_level else "; a static helper may omit them on purpose"))
        for rid in declared:
            if rid not in RIDS:
                self.add("error", "ASMPRJ016", p.path, where,
                         f"'{rid}' is not a RID AsmSdk builds: the build stops with ASM0011",
                         "use " + ", ".join(RIDS))
        if (p.kind == "Executable" and "freestanding" in p.frameworks
                and any(RIDS.get(r, ("",))[0] == "MacOS" for r in declared)):
            self.add("error", "ASMPRJ017", p.path, where,
                     "a freestanding executable for macOS: Apple supports no static executables, and the build stops with ASM0015",
                     "<TargetFramework>libc</TargetFramework> for a macOS program, or drop the osx RIDs")

    def _directory_build_props(self, project: Project) -> Optional[Project]:
        """The Directory.Build.props MSBuild imports for a project (the nearest one above it).

        Solution-wide asm settings (a LinkerArg -z defs) usually live there, so
        recommendations must look at it before suggesting them for every project.

        Args:
            project: The project whose folder starts the upward search.

        Returns:
            The parsed file, or None when there is none or it is not well-formed.
        """
        folder = project.dir
        while True:
            candidate = os.path.join(folder, "Directory.Build.props")
            if os.path.isfile(candidate):
                try:
                    return parse_msbuild_file(candidate)
                except ValueError:
                    return None
            parent = os.path.dirname(folder)
            if parent == folder:
                return None
            folder = parent

    def _check_public_includes(self, p: Project) -> None:
        """A library whose include files sit outside include/ packs none of them.

        A warning when the project is clearly meant to be packed (PackageId or
        GeneratePackageOnBuild), info otherwise, because a ProjectReference still works.

        Args:
            p: The project.
        """
        if p.kind == "Executable" or os.path.isdir(os.path.join(p.dir, "include")) or p.items.get("AsmPublicInclude"):
            return
        root_incs = [i for i in project_sources(p)[1] if os.path.dirname(i) == p.dir]
        if not root_incs:
            return
        packable = p.prop("PackageId") is not None or (p.prop("GeneratePackageOnBuild") or "").lower() == "true"
        self.add("warning" if packable else "info", "ASMPRJ003", p.path, 0,
                 f"no include/ folder: dotnet pack ships none of {', '.join(os.path.basename(i) for i in root_incs)}, so package consumers' %include fails"
                 " (a ProjectReference still works: it falls back to the project folder)",
                 "move public .inc files into include/, or declare AsmPublicInclude items")

    # -- source checks -----------------------------------------------------------------------

    def _check_source_selection(self, p: Project, rids: List[str], assumed: bool) -> Dict[str, FrozenSet[str]]:
        """Mirror the SDK's per-RID source selection, report its errors, and map each NASM source to its OSes.

        Args:
            p: The project.
            rids: The RIDs it is judged for (effective_rids).
            assumed: Whether those RIDs are assumed (then ASM0023 is not reported).

        Returns:
            NASM source path (normcase) -> the OSes it is assembled for; a source no RID
            selects maps to an empty set.
        """
        all_sources = project_all_sources(p)
        # An explicit AsmSource item for a file the default **/*.asm and **/*.s globs already
        # include makes it a source twice: ASM0024 (project_all_sources de-duplicates, so the
        # explicit items are compared with the globs here).
        if (p.prop("EnableDefaultAsmItems") or "true").lower() != "false":
            by_glob = {os.path.normcase(s) for s in _walk_files(p.dir, ".asm") + _walk_files(p.dir, ".s")}
            for item in p.items.get("AsmSource", []):
                for path in _resolve_item_paths(p, item.get("Include", "")):
                    if os.path.normcase(path) in by_glob:
                        self.add("error", "ASMSRC017", p.path, p.prop_lines.get("AsmSource", 0),
                                 f"{os.path.relpath(path, p.dir)} is an AsmSource twice, from the default **/*.asm and **/*.s globs and from this item: the build stops with ASM0024",
                                 "remove the explicit AsmSource item, or set EnableDefaultAsmItems=false and list every source yourself")
        for path in all_sources:
            _, qualifier, language = split_source_name(path)
            if language == "Nasm" and qualifier and qualifier_is_arm64_only(qualifier):
                self.add("error", "ASMSRC014", path, 0,
                         f"a NASM file (.asm) qualified for '{qualifier}', which names no x64 RID: NASM assembles x86-64 only, and the build stops with ASM0021",
                         f"write ARM64 code in GNU syntax, or WebAssembly in LLVM's wasm syntax, in a .s file (x.{qualifier}.s)")
        selected_by: Dict[str, Set[str]] = {}
        for rid in rids:
            selected, ties = select_sources(all_sources, rid)
            for group in ties:
                self.add("error", "ASMSRC015", group[0], 0,
                         f"for {rid}, {' and '.join(os.path.basename(g) for g in group)} apply equally: the build stops with ASM0020",
                         f"keep one, or qualify one more narrowly (name.{rid}{os.path.splitext(group[0])[1]})")
            if all_sources and not selected and not ties and not assumed:
                self.add("error", "ASMSRC016", p.path, p.prop_lines.get("RuntimeIdentifiers", 0),
                         f"no source of this project builds {rid}: the build stops with ASM0023"
                         + (" (NASM files build the x64 RIDs; ARM64 needs GNU-syntax .s files)" if RIDS[rid][1] == "arm64" else "")
                         + (" (no unqualified file builds WebAssembly: an unqualified .s is ARM64 code)" if RIDS[rid][1] == "wasm" else ""),
                         f"add a source for {rid} (for example name."
                         + ({"arm64": f"{rid}.s", "wasm": "wasm.s"}.get(RIDS[rid][1], f"{rid}.asm"))
                         + f"), or remove {rid} from RuntimeIdentifiers")
            for path in selected:
                selected_by.setdefault(os.path.normcase(path), set()).add(RIDS[rid][0])
        return {os.path.normcase(s): frozenset(selected_by.get(os.path.normcase(s), set()))
                for s in all_sources if s.lower().endswith(".asm")}

    def _defined_symbols(self, projects: List[Project]) -> Tuple[Set[str], Set[str]]:
        """The global symbols a set of projects' NASM sources define, and which of them are hidden.

        Args:
            projects: Projects whose sources to read.

        Returns:
            (defined, hidden): names with a global declaration (or asmsdk.inc macro) and a
            label; hidden = those whose visibility NASM actually applies.
        """
        defined: Set[str] = set()
        hidden: Set[str] = set()
        for ref in projects:
            for path in project_sources(ref)[0]:
                if os.path.isfile(path):
                    info = self.source(path)
                    for name, (_, qualifiers) in info.globals.items():
                        if name in info.labels:
                            defined.add(name)
                            # Only a visibility NASM actually applies makes PLT/GOT unnecessary.
                            # Any declaration counts, not only the last: a symbol hidden under
                            # %ifdef LINUX is followed by its macOS and Windows forms, which
                            # carry no ELF visibility but do not change Linux's.
                            decls = info.global_decls.get(name, [(0, qualifiers)])
                            if any(visibility(q)[0] for _, q in decls):
                                hidden.add(name)
        return defined, hidden

    def check_sources(self, p: Project, referenced: List[Project]) -> None:
        """Run the per-file NASM checks for one project's sources.

        Symbol resolution looks at this project and everything it references, because the
        linker sees all of their outputs; packages cannot be read, so with a PackageReference
        present an unresolved symbol is only a warning. Since 0.3.0 Linux shared libraries
        link -Bsymbolic: a call or data reference within the library (this project, and the
        static libraries and objects it links in) needs no PLT or GOT; only another library's
        symbols do.

        Args:
            p: The project.
            referenced: Its .asmproj references, transitively.
        """
        rids, assumed = self.effective_rids(p)
        file_oses = self._check_source_selection(p, rids, assumed)
        self._check_wasm_sources(p, rids)
        sources, includes = project_sources(p)
        dirs = include_dirs(p, referenced)
        project_files = sources + includes
        infos = {s: self.source(s) for s in project_files if os.path.isfile(s)}
        # Symbols defined anywhere in this project or the projects it references, and those
        # linked into this project's own image (its sources, plus static libraries and objects).
        defined, hidden = self._defined_symbols([p] + referenced)
        linked_in, _ = self._defined_symbols([p] + [r for r in referenced if r.produces_static or r.kind == "Objects"])
        libc_extra = {i.get("Include", "").strip() for i in p.items.get("AsmLibcSymbol", [])}
        has_packages = bool(p.items.get("PackageReference"))
        lists = self.symbol_lists(p)
        included_asm: Set[str] = set()
        entry_found = False
        entry = p.prop("StartupObject") or ("main" if p.runtime == "Libc" and p.kind == "Executable" else "_start")
        for path in sources:
            info = infos.get(path)
            if info is None:
                continue
            oses = file_oses.get(os.path.normcase(path), frozenset())
            local_incs = self._resolve_includes(p, info, dirs, included_asm)
            externs = set(info.externs)
            default_rel = info.default_rel
            for inc in local_incs:
                inc_info = self.source(inc)
                externs |= inc_info.externs
                default_rel = default_rel or inc_info.default_rel
            externs -= info.labels  # "extern x" plus a definition in the same file = a definition
            if entry in info.globals and entry in info.labels:
                entry_found = True
            if not oses:
                # Not built for any RID judged here (x.win.asm in a Linux-only project): nothing
                # it says reaches an assembler, so its directives are not judged.
                continue
            self._check_source_lines(p, info, externs, hidden, linked_in, default_rel, oses, assumed)
            if "Linux" in oses and not info.has_gnu_stack:
                self.add("info", "ASMSRC006", path, 0,
                         "no .note.GNU-stack section: the SDK links with -z noexecstack, but other linkers of this object or archive may mark the stack executable",
                         "%ifdef LINUX / section .note.GNU-stack noalloc noexec nowrite progbits / %endif")
            self._check_globals(p, info, oses, assumed)
            # Undefined references: externs no source here (or in references) defines, and no
            # C library list of an OS this file builds provides.
            for name in sorted(externs - defined):
                # Judge each extern only on the OSes its declaration is assembled for (externs
                # from include files count everywhere: their guards are the include's own).
                name_oses = oses & info.extern_oses.get(name, ALL_OSES)
                missing_on = self._missing_from_c_libraries(p, name, name_oses, lists, libc_extra)
                if not missing_on:
                    continue
                number = next((n for n, c in info.lines if re.search(rf"\bextern\b.*\b{re.escape(name)}\b", c)), 0)
                where = "" if missing_on == oses else f" on {describe_oses(missing_on)}"
                if p.kind == "Executable" and p.runtime == "Libc":
                    self.add("warning" if has_packages else "error", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project, its references or the C library list{where}: the link fails with 'undefined symbol: {name}'"
                             + (" unless a package defines it" if has_packages else ""),
                             f'a C library function: <AsmLibcSymbol Include="{name}" /> (on Windows it must be a ucrtbase.dll export); otherwise add the reference or package that defines it')
                elif p.kind == "Executable":
                    self.add("warning" if has_packages else "error", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project or its references{where}: the link fails with 'undefined symbol: {name}'"
                             + (" unless a package defines it" if has_packages else ""),
                             "add the ProjectReference or PackageReference that defines it, or fix the name")
                elif p.kind == "SharedLibrary" and not has_packages:
                    self.add("info", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project, its references"
                             + (" or the C library list" if p.runtime == "Libc" else "") + where
                             + ": a Linux shared library links anyway and fails at load time; Windows and macOS stop the link",
                             '<LinkerArg Include="-z defs" /> turns this into a link error on Linux too')
        for path in sorted(included_asm):
            if path in sources:
                info = infos.get(path) or self.source(path)
                defines_code = bool(info.globals) or bool(info.labels)
                self.add("error" if defines_code else "warning", "ASMSRC010", path, 0,
                         "this .asm is %include'd by another source and also assembled on its own"
                         + (": its symbols are linked twice ('duplicate symbol')" if defines_code else ""),
                         f'rename it to .inc, or <AsmSource Remove="{os.path.relpath(path, p.dir)}" />')
        if p.kind == "Executable" and sources and not entry_found:
            self.add("error", "ASMSRC011", p.path, 0,
                     f"no source defines '{entry}' (a global label, or FUNCTION {entry}): "
                     + ("the SDK's startup code calls main" if entry == "main" else f"the executable's entry point is {entry}"),
                     f"FUNCTION {entry} (asmsdk.inc), or global {entry} and the {entry}: label")

    # -- WebAssembly (the SDK release after 0.3.0) ------------------------------------------------

    #: The wasm type clang gives each C type on wasm32 (the SDK's ApiPrototype.WasmValueType):
    #: pointers and function pointers are i32 too, and void (a return only) has no value.
    WASM_C_TYPES = {"void": None, "int64_t": "i64", "uint64_t": "i64", "float": "f32", "double": "f64"}

    def _check_wasm_project(self, p: Project, rids: List[str]) -> None:
        """The project-level WebAssembly rules: what the SDK refuses before it assembles anything.

        Args:
            p: The project.
            rids: The RIDs it is judged for (effective_rids).
        """
        wasm = [r for r in rids if RIDS[r][1] == "wasm"]
        if not wasm:
            return
        line = p.prop_lines.get
        where = line("RuntimeIdentifiers", line("RuntimeIdentifier", 0))
        version = self._pinned_version(p)
        if version == "0.3.0":
            # Info, not an error: a build of AsmSdk's main packed into a local feed also says
            # 0.3.0 and builds wasm (the eval suite's build check uses one); nuget.org's 0.3.0
            # stops it. The linter cannot tell the two packages apart.
            self.add("info", "ASMPRJ019", p.path, where,
                     f"{', '.join(wasm)} with AsmFoundation.Sdk 0.3.0: nuget.org's 0.3.0 has no WebAssembly, and the build stops with ASM0011",
                     "an AsmFoundation.Sdk after 0.3.0 in global.json (a build of AsmSdk's main from a local feed also works)")
        if p.kind == "Executable" and "browser-wasm" in wasm:
            self.add("error", "ASMPRJ020", p.path, line("OutputType", where),
                     "a program (OutputType Exe) for browser-wasm: the browser starts no program, and the build stops with ASM0017",
                     "a Library for the browser (a module with exports), or the program for wasi-wasm only")
        if "libc" in p.frameworks and p.kind in ("SharedLibrary", "Executable"):
            self.add("error", "ASMPRJ021", p.path, line("TargetFramework", line("TargetFrameworks", where)),
                     "a libc WebAssembly module or WASI program: the bundled wasm-ld links no C library, and the build stops with ASM0016",
                     "freestanding (calling WASI or JavaScript imports), or a StaticLibrary for a .NET WebAssembly app, whose own build brings the C library")
        for define in re.split(r"[;,]", p.prop("DefineConstants") or ""):
            define = define.strip()
            if "=" in define and "$(" not in define:
                self.add("error", "ASMPRJ022", p.path, line("DefineConstants", 0),
                         f"the define '{define}' has a value, and a WebAssembly source receives defines as labels: the build stops with ASM0018",
                         "define the name alone and write the value in the source")
        exports = p.prop("ExportsFile")
        if exports and p.kind == "SharedLibrary":
            exports_path = os.path.join(p.dir, exports)
            try:
                with open(exports_path, encoding="utf-8", errors="replace") as f:
                    # Version scripts take C comments (and # lines): their * are not patterns.
                    script = re.sub(r"#[^\n]*", "", re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S))
                # Only the exported names matter: a version script's "local: *;" (everything
                # else stays hidden) is fine, and so are the node names (CRC32C_1.0).
                script = re.sub(r"\blocal\s*:[^}]*", "", script)
                patterns = [w for w in re.findall(r"[\w*?.$@]+", script) if "*" in w or "?" in w]
            except OSError:
                patterns = []
            if patterns:
                self.add("error", "ASMPRJ023", p.path, line("ExportsFile", 0),
                         f"{exports} exports {', '.join(sorted(set(patterns)))}, a pattern: a WebAssembly module exports exact names only, and the build stops with ASM0030",
                         "list each exported name (local: * may stay)")

    @staticmethod
    def _wasm_code(text: str) -> str:
        """A wasm source line without its string literals' contents and its comment.

        Args:
            text: The raw line.

        Returns:
            The code part: strings become "" (so a // inside .ascii is not a comment), and
            everything from // or # on is dropped.
        """
        code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
        for marker in ("//", "#"):
            cut = code.find(marker)
            if cut >= 0:
                code = code[:cut]
        return code.rstrip()

    def _wasm_lower(self, c_type: str) -> Optional[str]:
        """Lower one C type of a PROTO line to its wasm value type, as the SDK does.

        Args:
            c_type: The type as written, with qualifiers, pointers and possibly a parameter name.

        Returns:
            "i32", "i64", "f32", "f64", or None for void (no value).
        """
        if "*" in c_type or "(" in c_type:
            return "i32"
        words = [w for w in re.findall(r"[A-Za-z_]\w*", c_type) if w not in ("const", "volatile", "struct", "unsigned", "signed")]
        base = next((w for w in words if w in self.WASM_C_TYPES), words[0] if words else "int")
        return self.WASM_C_TYPES.get(base, "i32")

    def _wasm_proto_signature(self, proto: str) -> Optional[Tuple[str, str]]:
        """The wasm signature a PROTO line lowers to.

        Args:
            proto: The text after PROTO, e.g. "int32_t add(int32_t a, int32_t b)".

        Returns:
            (function name, "(i32,i32)->(i32)" without spaces), or None when the line cannot be
            split into a return type, a name and a parameter list.
        """
        match = re.match(r"^(.*?)\b([A-Za-z_]\w*)\s*\((.*)\)\s*;?\s*$", proto.strip())
        if not match:
            return None
        returns, name, params = match.groups()
        result = self._wasm_lower(returns) if returns.strip() else "i32"
        parameters: List[str] = []
        if params.strip() and params.strip() != "void":
            for param in params.split(","):
                lowered = self._wasm_lower(param)
                if lowered:
                    parameters.append(lowered)
        return name, f"({','.join(parameters)})->({result or ''})"

    def _check_wasm_sources(self, p: Project, rids: List[str]) -> None:
        """The measured traps of llvm-mc's WebAssembly parser and writer, per wasm source.

        Each check reports what the build would do with the line as written; every one was
        reproduced with LLVM 23.1.5 and the SDK's asmsdk-wasm.inc.

        Args:
            p: The project.
            rids: The RIDs it is judged for (effective_rids); only the .s files a wasm RID
                selects are read.
        """
        wasm = [r for r in rids if RIDS[r][1] == "wasm"]
        if not wasm:
            return
        all_sources = project_all_sources(p)
        selected = sorted({s for r in wasm for s in select_sources(all_sources, r)[0] if s.lower().endswith(".s")})
        linked_into_dotnet = p.kind in ("SharedLibrary", "StaticLibrary", "Objects")
        functions = ("FUNCTION", "LOCAL_FUNCTION", "HIDDEN_FUNCTION")
        for path in selected:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    raw = f.read().splitlines()
            except OSError:
                continue
            codes = [(n, self._wasm_code(t)) for n, t in enumerate(raw, 1)]
            sized = {m.group(2) for _, c in codes for m in [re.match(r"^\s*(ENDDATA|\.size)\s+([\w.$]+)", c)] if m}
            known: Set[str] = set()
            current: Optional[Tuple[str, int]] = None      # (function name, line) while inside one
            section = "text"
            data_labels: List[Tuple[int, str]] = []
            protos: Dict[str, Tuple[int, str]] = {}
            imports_wasi = False
            data_sections: List[int] = []
            aligned = False
            for number, code in codes:
                stripped = code.strip()
                if not stripped:
                    continue
                word = stripped.split()[0]
                upper = word.upper()
                if re.match(r"^\.(set|equ|equiv)\b", stripped) or re.match(r"^[A-Za-z_.$][\w.$]*\s*=[^=]", stripped):
                    self.add("error", "ASMWASM001", path, number,
                             "an assembler constant: llvm-mc's WebAssembly writer stops on any constant symbol, even a .L one "
                             "('absolute addressing not supported!'), and the build stops with ASM0019",
                             "write the number where it is used, or a macro that expands to i32.const N")
                if stripped == ".text":
                    self.add("warning", "ASMWASM003", path, number,
                             "a bare .text does nothing in llvm-mc's wasm parser: code after it stays in the current section",
                             "start each function with FUNCTION, which switches to its own section")
                m = re.match(r"^\.(int8|int16|int32|int64)\s+[^,]+,", stripped)
                if m or word == ".word":
                    self.add("error", "ASMWASM004", path, number,
                             (f".{m.group(1)} takes one value: the wasm parser stops at the comma ('Expected EOL')" if m
                              else ".word does not exist in llvm-mc's wasm parser"),
                             "a list in .byte, .short, .int or .quad")
                if stripped in (".bss", ".rodata"):
                    self.add("error", "ASMWASM005", path, number,
                             f"{stripped} is an unknown directive in llvm-mc's wasm parser",
                             "BSS or RODATA from asmsdk-wasm.inc (.section " + stripped + ',"",@)')
                if upper == "STRUCT":
                    self.add("error", "ASMWASM010", path, number,
                             "STRUCT is not read from WebAssembly sources yet: its offsets would be assembler constants, which wasm objects cannot hold",
                             "lay the structure out with explicit offsets in this source, and keep STRUCT lines in the native sources only if no PROTO here uses the struct")
                if upper == "PROTO" or upper in functions:
                    if current:
                        self.add("error", "ASMWASM006", path, number,
                                 f"{upper} inside {current[0]} (from line {current[1]}): the build stops with "
                                 f"'PROTO and the function macros go between functions: {current[0]} has no ENDFUNCTION yet'",
                                 f"close {current[0]} with ENDFUNCTION {current[0]} first; a PROTO line goes right above its FUNCTION")
                if upper == "PROTO":
                    lowered = self._wasm_proto_signature(stripped[len(word):])
                    # A PROTO inside a function is ASMWASM006 already: it pairs with nothing.
                    if lowered and not current:
                        protos[lowered[0]] = (number, lowered[1])
                    continue
                if upper in functions:
                    m = re.match(r"^\w+\s+([\w.$]+)\s*,\s*(\(.*)$", stripped)
                    if m:
                        name, signature = m.group(1), re.sub(r"\s+", "", m.group(2))
                        known.add(name)
                        current = (name, number)
                        section = "text"
                        if name in protos:
                            proto_line, proto_signature = protos.pop(name)
                            if proto_signature != signature:
                                self.add("error", "ASMWASM013", path, proto_line,
                                         f"PROTO {name} lowers to {proto_signature} but its {upper} declares {signature}: the build stops with ASM0132",
                                         "make them agree: pointers, bool and integers of 32 bits or fewer are i32, int64_t/uint64_t i64, float f32, double f64")
                            # A binding needs a function the image offers: a LOCAL_FUNCTION never
                            # leaves its file, and a module exports no HIDDEN_FUNCTION.
                            if upper == "LOCAL_FUNCTION" or (upper == "HIDDEN_FUNCTION" and p.kind == "SharedLibrary"):
                                self.add("error", "ASMWASM014", path, proto_line,
                                         f"PROTO {name} describes a {upper}, which no caller outside "
                                         + ("this file" if upper == "LOCAL_FUNCTION" else "the module") + " can reach: the build stops with ASM0131",
                                         f"declare {name} with FUNCTION, or drop the PROTO line")
                    continue
                if upper == "ENDFUNCTION":
                    closing = stripped.split()[1] if len(stripped.split()) > 1 else ""
                    if current and closing and closing != current[0]:
                        self.add("error", "ASMWASM007", path, number,
                                 f"ENDFUNCTION {closing} closes {current[0]} (line {current[1]})",
                                 f"ENDFUNCTION {current[0]}")
                    current = None
                    continue
                if upper in ("EXTERN_FUNCTION", "IMPORT_FUNCTION") or word == ".functype":
                    m = re.match(r"^\S+\s+(?:([\w.$]+)\s*,\s*)?([\w.$]+)\s*,\s*\(", stripped) if upper == "IMPORT_FUNCTION" \
                        else re.match(r"^\S+\s+([\w.$]+)", stripped)
                    if m:
                        known.add(m.group(m.lastindex))
                    if upper == "IMPORT_FUNCTION" and "wasi_snapshot_preview1" in stripped:
                        imports_wasi = True
                    continue
                if upper in ("DATA", "RODATA", "BSS") or re.match(r"^\.section\s+\.(data|rodata|bss)\b", stripped):
                    section = "data"
                    data_sections.append(number)
                    continue
                if word == ".p2align" or word == ".balign" or word == ".align":
                    aligned = True
                label = re.match(r"^([A-Za-z_$][\w.$]*):", stripped)
                if label and section == "data" and not label.group(1).startswith(".L"):
                    data_labels.append((number, label.group(1)))
                if stripped == "select":
                    self.add("error", "ASMWASM008", path, number,
                             "an untyped select: llvm-mc 23.1.5's type checker refuses it ('type mismatch, expected [i32] but got [i32, i32]' at ENDFUNCTION)",
                             "if i32 ... else ... end_if, leaving the chosen value")
                constant = re.match(r"^(f32\.const|f64\.const|v128\.const)\s+(\S.*)$", stripped)
                if constant:
                    self._check_wasm_float_operands(path, number, constant.group(1), constant.group(2))
                call = re.match(r"^(call|CALL|TAILCALL|return_call)\s+([\w.$]+)\s*$", stripped)
                if call:
                    if call.group(1) == "return_call" and linked_into_dotnet:
                        self.add("warning", "ASMWASM009", path, number,
                                 "return_call in a library: a .NET WebAssembly app that links it fails .NET 10's wasm-opt validation ('return_call* requires tail calls')",
                                 "TAILCALL (a call and a return), unless no .NET app will ever link this code")
                    if call.group(2) not in known:
                        self.add("error", "ASMWASM011", path, number,
                                 f"a call to {call.group(2)}, whose type llvm-mc has not seen here: assembling stops with 'missing .functype'",
                                 f"EXTERN_FUNCTION {call.group(2)}, (params) -> (results) above the call (a function further down, in another file or an archive), "
                                 "or IMPORT_FUNCTION for a host function")
            if current:
                self.add("error", "ASMWASM007", path, current[1],
                         f"{current[0]} has no ENDFUNCTION: the function never ends, and llvm-mc refuses the file",
                         f"ENDFUNCTION {current[0]} after its last instruction")
            for name, (number, _) in sorted(protos.items(), key=lambda item: item[1][0]):
                # A PROTO line no function macro of this file followed: a binding for nothing.
                self.add("error", "ASMWASM014", path, number,
                         f"PROTO {name} is followed by no FUNCTION {name} in this file: the build stops with ASM0131",
                         f"put the PROTO line right above FUNCTION {name}, or fix the name")
            for number, name in data_labels:
                if name not in sized:
                    self.add("error", "ASMWASM002", path, number,
                             f"the data label {name} has no size: llvm-mc's wasm writer stops ('data symbols must have a size set with .size'), and the build with ASM0019",
                             f"ENDDATA {name} after its last byte (a .L label needs none)")
            if imports_wasi and data_sections and not aligned:
                self.add("warning", "ASMWASM012", path, data_sections[0],
                         "WASI is imported, and no data here is aligned: llvm-mc aligns nothing by itself, and wasmtime refuses a misaligned "
                         "iovec or result pointer ('Pointer not aligned to 4')",
                         ".p2align 2 before the 32-bit values a WASI call is given")

    def _check_wasm_float_operands(self, path: str, number: int, instruction: str, operands: str) -> None:
        """ASMWASM015 and ASMWASM016: the float operands llvm-mc 23.1.5 refuses, and the f32
        operands it rounds without a word.

        llvm-mc reads every float operand as a double (llvm_mc_reads_float has the rule) and
        writes an f32 operand as that double rounded to f32. Each finding's fix is the whole
        instruction rewritten with literals that are read exactly, so it can be pasted as is.
        Anything that is not a number (a macro parameter such as \\value, nan, infinity) is
        left alone.

        Args:
            path: The source.
            number: The line.
            instruction: "f32.const", "f64.const" or "v128.const".
            operands: The text after it: one literal, or a v128.const's comma-separated lanes.
        """
        lanes = [lane.strip() for lane in operands.split(",")]
        if instruction == "v128.const":
            # Integer lanes make an integer vector, with nothing to check here. A float lane makes
            # f32x4 when there are four lanes and f64x2 when there are two; any other count is
            # llvm-mc's own error ("too few operands for instruction").
            if not any(WASM_DECIMAL_FLOAT.match(lane) or WASM_HEX_FLOAT.match(lane) for lane in lanes) or len(lanes) not in (2, 4):
                return
            kind = "f32" if len(lanes) == 4 else "f64"
        elif len(lanes) == 1:
            kind = instruction[:3]
        else:
            return
        integers: List[str] = []         # integer lanes: one reason names them all
        bit_patterns: List[str] = []     # the hex ones among them, which may be meant as bits
        refused: List[str] = []          # why each other refused lane stops assembling
        rounded: List[str] = []          # what each silently rounded lane becomes
        written: List[str] = []          # every lane as it should be written
        parse_rule = False               # a "Cannot parse real" refusal: the rule is worth stating
        suggested_hex = False            # a replacement is a hex float the user did not write
        for lane in lanes:
            negative = lane.startswith("-")
            if WASM_INTEGER.match(lane):
                is_hex = lane.lstrip("-")[:2].lower() == "0x"
                value = Fraction(int(lane, 16 if is_hex else 10))
                literal = wasm_float_literal(nearest_float(value, kind), negative)
                integers.append(lane)
                if is_hex:
                    bit_patterns.append(lane)
                suggested_hex |= literal.lstrip("-").startswith("0x")
                written.append(literal)
            elif re.match(r"^-?inf$", lane, re.IGNORECASE):
                # The parser knows the name infinity (any case) and nan; inf is an unknown word
                # ("invalid operand for instruction", or after a minus "Expected numeric constant").
                refused.append(f"{lane} is not a name the parser knows: it knows infinity ('invalid operand for instruction')")
                written.append(("-" if negative else "") + "infinity")
            elif WASM_DECIMAL_FLOAT.match(lane) or WASM_HEX_FLOAT.match(lane):
                value = float_literal_value(lane)
                if value is None:
                    written.append(lane)
                    continue
                stored = nearest_float(value, kind)
                literal = wasm_float_literal(stored, negative)
                if not llvm_mc_reads_float(lane):
                    # The order llvm_mc_reads_float decides in (the lexer, then the parser), so the
                    # reason named is the one that stops this literal: 06.1 is an octal start first.
                    if wasm_float_lexes_as_octal(lane):
                        refused.append(f"{lane} starts with a 0 that no point follows, which llvm-mc's lexer reads as an octal integer "
                                       f"(an error such as 'Expected ,, instead got: .5')")
                    else:
                        parse_rule = True
                        if nearest_float(value, "f64") != value:
                            why = f"no double is exactly {lane}"
                        else:
                            why = f"{lane} is a double, but its digits need more than 63 bits"
                        refused.append(f"{why} ('Cannot parse real'); {literal} is the {kind} nearest it")
                    suggested_hex |= literal.lstrip("-").startswith("0x")
                    written.append(literal)
                elif stored != value:
                    rounded.append(f"{lane} is stored as {literal}")
                    written.append(literal)
                else:
                    written.append(lane)
            else:
                written.append(lane)
        if integers:
            among = " among float lanes" if instruction == "v128.const" else ""
            subject = f"{integers[0]} is an integer" if len(integers) == 1 else f"{', '.join(integers)} are integers"
            bits = ""
            if bit_patterns:
                # A hex integer may be meant as the float's bits, which the value reading misses.
                wide = "i32" if kind == "f32" else "i64"
                bits = f"; if {', '.join(bit_patterns)} {'is' if len(bit_patterns) == 1 else 'are'} meant as bits, {wide}.const then {kind}.reinterpret_{wide}"
            refused.insert(0, f"{subject}{among}, which a float operand refuses ('invalid operand for instruction'){bits}")
        rewritten = f"{instruction} {', '.join(written)}"
        if refused:
            rule = (". llvm-mc reads a float operand as a double and stops on any it cannot prove exact: a decimal passes only when it is "
                    "a double whose significant digits fit in 63 bits (1.0, 0.5, 3.75, 1e3 do), a hex float when it is a double") if parse_rule else ""
            self.add("error", "ASMWASM015", path, number,
                     f"{instruction} {operands}: " + "; ".join(refused) + rule,
                     rewritten + (" (a hex float is read exactly, and is the form llvm-mc prints)" if suggested_hex else ""))
        elif rounded:
            self.add("warning", "ASMWASM016", path, number,
                     f"{instruction} {operands}: " + "; ".join(rounded) + ", the nearest f32: llvm-mc reads the double and rounds it "
                     "to f32 without a word",
                     f"{rewritten}, which says what is stored (f64.const when the extra precision matters)")

    def _missing_from_c_libraries(self, p: Project, name: str, oses: FrozenSet[str],
                                  lists: Dict[str, Set[str]], libc_extra: Set[str]) -> FrozenSet[str]:
        """The OSes on which an extern defined by no project here has no provider either.

        Linux freestanding code has none; Windows always links kernel32.dll (and, for libc,
        ucrtbase.dll and the SDK's stdio wrappers); macOS libc links libSystem. An OS whose list
        the linter could not read (the SDK package is not restored) is never reported.

        Args:
            p: The project.
            name: The undefined symbol.
            oses: The OSes the file builds.
            lists: load_sdk_symbol_lists' result.
            libc_extra: The project's AsmLibcSymbol names (added on every OS).

        Returns:
            The OSes that will fail to link it (empty when every OS provides it or cannot tell).
        """
        if name in libc_extra:
            return frozenset()
        missing = set()
        for os_name in oses:
            if os_name == "Linux":
                if not (p.runtime == "Libc" and name in LIBC_STUB_FUNCTIONS):
                    missing.add(os_name)
            elif os_name == "Windows":
                provider = lists.get("WindowsLibc" if p.runtime == "Libc" else "WindowsKernel")
                if provider is not None and name not in provider:
                    missing.add(os_name)
            elif os_name == "MacOS":
                if p.runtime != "Libc":
                    missing.add(os_name)
                elif "MacOS" in lists and name not in lists["MacOS"]:
                    missing.add(os_name)
        return frozenset(missing)

    def _check_globals(self, p: Project, info: SourceInfo, oses: FrozenSet[str], assumed: bool) -> None:
        """The `global` declarations: names, types, visibility, and what each format accepts.

        Args:
            p: The project (a Windows DLL exports only what it is told to).
            info: The file.
            oses: The OSes the file is assembled for.
            assumed: Whether the project's RIDs are assumed (findings become warnings).
        """
        path = info.path
        for name, (last_number, last_qualifiers) in info.globals.items():
            if name.lower() in KEYWORD_NAMES:
                self.add("error", "ASMSRC008", path, info.global_decls.get(name, [(last_number, last_qualifiers)])[0][0],
                         f"symbol '{name}' is a NASM keyword or mnemonic and does not parse as a label",
                         f"write it as ${name} in the definition and every reference")
                continue
            if name in info.macro_symbols:
                continue
            # Each declaration is judged for the OSes its guards leave it on: a symbol written
            # once per OS has a line per guard, and a mistake on any of them matters.
            decls = info.global_decls.get(name, [(last_number, last_qualifiers)])
            hidden_on, exported_on = self._symbol_visibility(info, decls, oses)
            # Meant to be internal: hidden somewhere, or an attempt NASM ignored ('data 8
            # hidden', ASMSRC013's finding), whose fix is to move the word, not to export it.
            meant_internal = bool(hidden_on) or any(visibility(q)[1] in ("hidden", "internal") for _, q in decls)
            for number, qualifiers in decls:
                line_on, uncertain, in_macro = info.line_oses.get(number, (ALL_OSES, False, False))
                if in_macro:
                    continue
                on = oses & line_on
                words = re.findall(r"[a-z_]+", qualifiers)
                for word in dict.fromkeys(words):
                    rejected = REJECTED_SYMBOL_WORDS.get(word, frozenset()) & on
                    if rejected:
                        self.add("warning" if uncertain or assumed else "error", "ASMSRC019", path, number,
                                 f"'global {name}:{qualifiers}': NASM's {describe_oses(rejected)} output stops at '{word}' (unrecognised symbol type)",
                                 "FUNCTION / HIDDEN_FUNCTION from asmsdk.inc write each format's own directives; or keep this line in %ifdef LINUX (or a name.linux.asm file)")
                if "Linux" in on:
                    ignored = visibility(qualifiers)[1]
                    if ignored:
                        self.add("warning", "ASMSRC013", path, number,
                                 f"'{ignored}' after the size is ignored by NASM (no warning): '{name}' stays exported",
                                 f"put the visibility first: global {name}:{qualifiers.split()[0] if qualifiers.split() else 'function'} {ignored} <size>")
                if on == frozenset({"Linux"}) and not re.search(r"\b(function|data|object)\b", qualifiers) and name in info.labels:
                    self.add("info", "ASMSRC007", path, number,
                             f"'global {name}' has no type: it is exported with type NONE and size 0",
                             f"global {name}:function ({name}.end - {name})  ; or :data <size>")
                # A Windows DLL exports only what a .drectve directive (FUNCTION) or the ExportsFile
                # names: a plain global is linkable but not exported, and .NET then fails with
                # EntryPointNotFoundException. A symbol hidden on Linux or private_extern on macOS
                # is meant to be internal, and there a plain global is exactly right; a line
                # win64's NASM stops on (ASMSRC019 above) exports nothing to judge.
                rejected_on_windows = any("Windows" in REJECTED_SYMBOL_WORDS.get(word, frozenset()) for word in words)
                if (p.kind == "SharedLibrary" and "Windows" in on and not p.prop("ExportsFile") and not info.manual_exports
                        and name in info.labels and not visibility(qualifiers)[0] and not meant_internal
                        and not rejected_on_windows):
                    is_data = any(re.search(r"\b(data|object)\b", q) for _, q in decls)
                    self.add("warning", "ASMSRC021", path, number,
                             f"'{name}' is not exported from the Windows DLL: a DLL exports only what a .drectve directive or the ExportsFile names",
                             f"an ExportsFile that lists it (FUNCTION is for functions)" if is_data else
                             f"FUNCTION {name} (asmsdk.inc writes the directive), or an ExportsFile that lists it; "
                             f"if it is internal, HIDDEN_FUNCTION {name} says so on every OS")
            # Internal on one OS and exported on another is a port that hid the symbol where it
            # was first written: the other library still exports it, and callers may bind to it.
            for os_name, number in sorted(exported_on.items()):
                if hidden_on and os_name not in hidden_on:
                    is_data = any(re.search(r"\b(data|object)\b", q) for _, q in decls)
                    fix = (f"global {name}:private_extern under %ifdef MACOS" if os_name == "MacOS" else
                           f"global {name}:{'data' if is_data else 'function'} hidden{' <size>' if is_data else ''} under %ifdef LINUX")
                    self.add("warning", "ASMSRC022", path, number,
                             f"'{name}' is internal on {describe_oses(frozenset(hidden_on))} but exported on {describe_oses(frozenset({os_name}))}",
                             fix + ("" if is_data else f"; or HIDDEN_FUNCTION {name}, which hides it on every OS"))

    @staticmethod
    def _symbol_visibility(info: SourceInfo, decls: List[Tuple[int, str]], oses: FrozenSet[str]) -> Tuple[Set[str], Dict[str, int]]:
        """Where a global's declarations hide it and where they leave it exported (Linux, macOS).

        ELF's hidden or internal visibility hides a symbol on Linux, and private_extern hides it
        on macOS; each output format rejects the other's word, so a declaration a format stops on
        (ASMSRC019's finding) says nothing about that format. Windows is left out: there a plain
        global is internal already, and only a directive or the ExportsFile exports it.

        Args:
            info: The file (its guards decide which OSes assemble each declaration).
            decls: The symbol's declarations, as (line, lower-case qualifiers).
            oses: The OSes the project builds this file for.

        Returns:
            (OSes where a declaration hides the symbol, OS -> line of a declaration that leaves it
            exported there). Lines inside a %macro body count for neither: they are assembled
            only where the macro is used.
        """
        hidden_on: Set[str] = set()
        exported_on: Dict[str, int] = {}
        for number, qualifiers in decls:
            line_on, _, in_macro = info.line_oses.get(number, (ALL_OSES, False, False))
            if in_macro:
                continue
            words = set(re.findall(r"[a-z_]+", qualifiers))
            for os_name in sorted((oses & line_on) & {"Linux", "MacOS"}):
                if any(os_name in REJECTED_SYMBOL_WORDS.get(word, frozenset()) for word in words):
                    continue
                hides = visibility(qualifiers)[0] in ("hidden", "internal") if os_name == "Linux" else "private_extern" in words
                if hides:
                    hidden_on.add(os_name)
                else:
                    exported_on.setdefault(os_name, number)
        return hidden_on, exported_on

    def _resolve_includes(self, p: Project, info: SourceInfo, dirs: List[Tuple[str, str]], included_asm: Set[str]) -> List[str]:
        """Resolve a file's %include lines the way NASM will, reporting ones that won't resolve.

        Args:
            p: The project.
            info: The including file.
            dirs: Include search folders (see include_dirs).
            included_asm: Receives every .asm file reached through %include.

        Returns:
            The included files found inside the project or its references (their externs and
            default rel apply to the including file).
        """
        found_files = []
        for number, name in info.includes:
            if os.path.basename(name).lower() in ("asmsdk.inc", "asmsdk-gnu.inc"):
                continue  # the SDK's own include folder is always on the path
            hit = None
            for folder, _ in dirs:
                candidate = os.path.normpath(os.path.join(folder, name))
                if os.path.isfile(candidate):
                    hit = candidate
                    break
            if hit:
                found_files.append(hit)
                if hit.lower().endswith(".asm"):
                    included_asm.add(hit)
                continue
            beside = os.path.normpath(os.path.join(os.path.dirname(info.path), name))
            if os.path.isfile(beside):
                rel = os.path.relpath(os.path.dirname(beside), p.dir).replace("\\", "/")
                self.add("error", "ASMSRC009", info.path, number,
                         f"'{name}' exists next to this file, but NASM never searches the including file's folder: 'unable to open include file'",
                         f'%include "{rel}/{name}", or <AsmIncludeDirectory Include="{rel}/" />')
            elif not p.items.get("PackageReference"):
                self.add("warning", "ASMSRC009", info.path, number,
                         f"'{name}' is not in the project folder, include/, AsmIncludeDirectory items or referenced projects"
                         " (fine if a build target generates it)",
                         "add the folder as AsmIncludeDirectory, the ProjectReference, or the package that ships it")
        return found_files

    def _check_source_lines(self, p: Project, info: SourceInfo, externs: Set[str], hidden: Set[str],
                            linked_in: Set[str], default_rel: bool, file_oses: FrozenSet[str], assumed: bool) -> None:
        """The instruction-level checks: sections, `wrt`, addressing, calls, data relocations, keyword labels.

        Each line is judged for the OSes it is assembled on (the file's OSes narrowed by its
        %ifdef guards), because what fails differs: Linux rejects absolute addresses in a .so or
        PIE at link time, macOS's NASM rejects 32-bit ones outright and the SDK's ASM0081 stops
        fixups in read-only segments, and Windows images accept 64-bit fixups but the SDK's
        ASM0080 stops 32-bit ones.

        Args:
            p: The project (its kind decides which outputs are linked or position-independent).
            info: The file.
            externs: Symbols this file references but does not define (own and included externs).
            hidden: Symbols defined hidden somewhere in the project (safe without PLT/GOT).
            linked_in: Symbols defined in this project's own image (its sources and the static
                libraries and objects it links): within a -Bsymbolic library, no PLT/GOT.
            default_rel: Whether `default rel` is in effect (this file or a local include).
            file_oses: The OSes the file is assembled for.
            assumed: Whether the project's RIDs are assumed (platform errors become warnings).
        """
        shared = p.kind == "SharedLibrary"
        linked = p.kind in ("SharedLibrary", "Executable")
        pic_linux = p.pic_required
        portable = p.kind in ("StaticLibrary", "Objects")
        section, writable = ".text", False
        for number, code in info.lines:
            line_on, uncertain, in_macro = info.line_oses.get(number, (ALL_OSES, False, False))
            oses = file_oses & line_on
            if not oses:
                continue
            severe = "warning" if uncertain or assumed else "error"
            low = code.strip().lower()
            m = re.match(r"^\[?\s*(?:section|segment)\s+(\S+)(.*)$", low)
            if m:
                section = m.group(1).rstrip("]")
                attrs = m.group(2)
                writable = section in (".data", ".bss", ".tdata", ".tbss") or bool(re.search(r"\bwrite\b", attrs)) and not re.search(r"\bnowrite\b", attrs)
                rejected = REJECTED_SECTIONS.get(section, frozenset()) & oses
                if rejected and not in_macro:
                    self.add(severe, "ASMSRC018", info.path, number,
                             f"section {m.group(1).rstrip(']')}: NASM's {describe_oses(rejected)} output stops here (unknown section name)",
                             "%ifdef LINUX / ... / %endif around it" if section == ".note.gnu-stack" else "%ifdef WINDOWS / ... / %endif around it")
                if section == ".data.rel.ro" and not re.search(r"\bwrite\b", attrs) and "Linux" in oses:
                    self.add("warning", "ASMSRC005", info.path, number,
                             "NASM does not know .data.rel.ro and makes it read-only: absolute addresses (dq label) in it fail to link in a .so or PIE",
                             "section .data.rel.ro progbits alloc noexec write align=8")
                continue
            if low.startswith("%") or low.startswith("["):
                continue
            # `wrt ..x` special symbols exist in one format each (..plt/..got ELF, ..gotpcrel
            # Mach-O, ..imagebase PE): NASM stops on the others.
            if not in_macro:
                for special in dict.fromkeys(re.findall(r"\bwrt\s+(\.\.\w+)", low)):
                    rejected = REJECTED_WRT.get(special, frozenset()) & oses
                    if rejected:
                        self.add(severe, "ASMSRC020", info.path, number,
                                 f"'wrt {special}': NASM's {describe_oses(rejected)} output has no {special} (\"symbol `{special}' not defined\")",
                                 "call f PLT (asmsdk.inc: wrt ..plt on Linux, nothing elsewhere); for data, %ifdef per OS (..got on Linux, ..gotpcrel on macOS)")
            label_m = re.match(rf"^\s*({IDENT})\s*:", code)
            if label_m and label_m.group(1).lower() in KEYWORD_NAMES:
                self.add("error", "ASMSRC008", info.path, number,
                         f"label '{label_m.group(1)}' is a NASM keyword or mnemonic: 'label, instruction or prefix expected'",
                         f"${label_m.group(1)}:")
            body = code[label_m.end():] if label_m else code
            # Strip the indentation first: operands are sliced off after the mnemonic's length,
            # which is only right when the text starts at the mnemonic.
            body_nostr = _strip_strings(body).strip()
            words = body_nostr.split()
            if not words:
                continue
            op = words[0].lower()
            # data directives with absolute addresses
            if op in ("dq", "dd") or (len(words) > 1 and words[1].lower() in ("dq", "dd") and re.match(IDENT, words[0])):
                directive = op if op in ("dq", "dd") else words[1].lower()
                operands = body_nostr.split(directive, 1)[1] if directive in body_nostr.lower() else ""
                for operand in operands.split(","):
                    ident = re.findall(IDENT, operand)
                    names = [t for t in ident if (t.lstrip("$") in info.labels or t.lstrip("$") in externs) and not re.search(r"\$\$?|-|\bwrt\b", operand)]
                    if not names:
                        continue
                    if directive == "dd":
                        # 32-bit absolute: Linux PIC rejects it, the SDK's ASM0080 stops a Windows
                        # image with one, and macOS's NASM refuses it.
                        bad = {o for o in oses if (o == "Linux" and pic_linux) or (o == "Windows" and linked) or o == "MacOS"}
                        if bad or portable:
                            self.add(severe if bad else "warning", "ASMPIC005", info.path, number,
                                     f"'dd {names[0]}' stores a 32-bit absolute address"
                                     + (f": it fails on {describe_oses(bad)}" if bad else ": position-independent outputs cannot relocate it"),
                                     f"store an offset instead: dd {names[0]} - <table label>")
                    elif not writable:
                        # 64-bit absolute in read-only data: Linux PIC rejects it, macOS's ASM0081
                        # stops a fixup in a read-only segment; Windows relocates it.
                        bad = {o for o in oses if (o == "Linux" and pic_linux) or (o == "MacOS" and linked)}
                        risky = portable and bool(oses & {"Linux", "MacOS"})
                        if bad or risky:
                            self.add(severe if bad else "warning", "ASMPIC005", info.path, number,
                                     f"'dq {names[0]}' in read-only {section}"
                                     + (f": fails on {describe_oses(bad)} (Linux: 'relocation R_X86_64_64 cannot be used against local symbol'; macOS: ASM0081)" if bad
                                        else ": a .so, a PIE or a macOS image cannot relocate it"),
                                     "use an offset table (dd label - table) in .rodata, or move the table to .data")
                    break
                continue
            if op in DATA_DIRECTIVES + RES_DIRECTIVES or op in ("times", "align", "alignb", "global", "extern", "bits", "default", "cpu", "struc", "endstruc", "istruc", "iend", "at", "equ"):
                continue
            operands = body_nostr[len(words[0]):]
            # memory operands
            for mem in re.findall(r"\[([^\]]*)\]", operands):
                mem_low = mem.lower()
                tokens = [t for t in re.findall(IDENT, mem) if t.lower() not in OPERAND_KEYWORDS and not t.startswith("..")]
                regs = [t for t in tokens if t.lower() in REGISTERS or t.lower() in ARG_REGISTER_MACROS]
                symbols = [t.lstrip("$") for t in tokens if t.lower() not in REGISTERS and t.lower() not in ARG_REGISTER_MACROS and t.lstrip("$") not in info.constants]
                symbols = [s for s in symbols if s in info.labels or s in externs]
                if not symbols:
                    continue
                explicit = re.match(r"^\s*(rel|abs)\b", mem_low) is not None or re.search(r"\b(qword|dword|word|byte)\s+(rel|abs)\b", mem_low)
                if not regs and not explicit and not default_rel:
                    bad = {o for o in oses if (o == "Linux" and pic_linux) or (o == "Windows" and linked) or o == "MacOS"}
                    reasons = []
                    if "Linux" in bad:
                        reasons.append("Linux: 'relocation R_X86_64_32S cannot be used against local symbol' in a .so or PIE")
                    if "MacOS" in bad:
                        reasons.append("macOS: NASM stops ('Mach-O 64-bit format does not support 32-bit absolute addresses')")
                    if "Windows" in bad:
                        reasons.append("Windows: the image needs a 32-bit fixup, and the SDK stops with ASM0080")
                    self.add(severe if bad else "warning", "ASMPIC001", info.path, number,
                             f"[{mem.strip()}] without default rel is absolute addressing: "
                             + ("; ".join(reasons) if reasons else "NASM 3 warns 'implicit DEFAULT ABS is deprecated' (an error with TreatWarningsAsErrors)"),
                             "put 'default rel' at the top of the file")
                # Another library's data, read directly from a Linux .so (no GOT).
                if shared and "Linux" in oses and "..got" not in mem_low:
                    for s in symbols:
                        if s in externs and s not in hidden and s not in linked_in:
                            self.add(severe, "ASMPIC003", info.path, number,
                                     f"[{mem.strip()}] reads '{s}' from another library directly: Linux fails with 'relocation R_X86_64_PC32 cannot be used against symbol '{s}''",
                                     f"%ifdef LINUX: mov rax, [rel {s} wrt ..got] then use [rax] (macOS: wrt ..gotpcrel)")
                            break
            # calls and jumps to another library's functions, from a Linux .so
            if shared and "Linux" in oses and op in ("call", "jmp"):
                target = re.match(rf"\s*({IDENT})\s*(.*)$", operands)
                if target:
                    name = target.group(1).lstrip("$")
                    tail = target.group(2)
                    through_plt = "..plt" in tail.lower() or re.search(r"\bPLT\b", tail) is not None
                    if name in externs and name not in hidden and name not in linked_in and not through_plt:
                        self.add(severe, "ASMPIC002", info.path, number,
                                 f"{op} {name}: a direct call to another library from a Linux .so: 'relocation R_X86_64_PC32 cannot be used against symbol '{name}''",
                                 f"{op} {name} PLT (asmsdk.inc: wrt ..plt on Linux, nothing elsewhere)")
            # absolute addresses as immediates
            if op in ("mov", "push", "cmp", "add", "sub"):
                parts = [x.strip() for x in operands.split(",")]
                if len(parts) >= 1:
                    src = parts[-1]
                    if re.fullmatch(IDENT, src) and (src.lstrip("$") in info.labels or src.lstrip("$") in externs) and src.lstrip("$") not in info.constants:
                        bad = {o for o in oses if (o == "Linux" and pic_linux) or (o == "MacOS" and linked)}
                        risky = portable and bool(oses & {"Linux", "MacOS"})
                        if bad or risky:
                            self.add(severe if bad else "warning", "ASMPIC004", info.path, number,
                                     f"'{op} ..., {src}' uses the absolute address of {src}"
                                     + (f": fails on {describe_oses(bad)} (Linux: 'relocation R_X86_64_64 (or _32) cannot be used'; macOS: ASM0081, a text relocation)" if bad
                                        else ": a .so, a PIE or a macOS image cannot relocate it"),
                                     f"lea <reg>, [rel {src}]" + (" ; or [rel ... wrt ..got] for another library's symbol" if src.lstrip("$") in externs else ""))


def discover(paths: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Find the .asmproj and .slnx files to check under the given paths.

    Args:
        paths: Files (.asmproj, .slnx) or folders.

    Returns:
        (project paths, solution paths), absolute and de-duplicated.

    Raises:
        FileNotFoundError: A given path does not exist.
    """
    projects, solutions = [], []
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if os.path.isfile(path):
            (projects if path.lower().endswith(".asmproj") else solutions if path.lower().endswith(".slnx") else []).append(os.path.abspath(path))
            continue
        projects.extend(_walk_files(path, ".asmproj"))
        solutions.extend(_walk_files(path, ".slnx"))
    return list(dict.fromkeys(projects)), list(dict.fromkeys(solutions))


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; None means sys.argv[1:].

    Returns:
        0 when no error-level finding exists, 1 when one does, 2 on usage errors.
    """
    parser = argparse.ArgumentParser(description="Lint AsmSdk projects and NASM sources for known footguns.")
    parser.add_argument("paths", nargs="+", help=".asmproj or .slnx files, or folders to search")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--no-info", action="store_true", help="hide info-level recommendations")
    args = parser.parse_args(argv)
    try:
        projects, solutions = discover(args.paths)
    except FileNotFoundError as exc:
        print(f"check_asmproj: no such path: {exc}", file=sys.stderr)
        return 2
    if not projects and not solutions:
        print("check_asmproj: no .asmproj or .slnx found", file=sys.stderr)
        return 2
    linter = Linter()
    for path in solutions:
        linter.check_slnx(path)
    parsed = [p for p in (linter.project(path) for path in projects) if p is not None]
    # RID-less projects inherit the RIDs of the projects that reference them, so every project
    # must be known before any is judged.
    linter.index_referrers(parsed)
    for project in parsed:
        linter.check_global_json(project)
        linter.check_project(project)
    findings = [f for f in linter.findings if not (args.no_info and f.severity == "info")]
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.path, f.line, f.code))
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        for f in findings:
            where = f"{f.path}:{f.line}" if f.line else f.path
            print(f"{where}: {f.severity} {f.code}: {f.message}" + (f"\n    fix: {f.fix}" if f.fix else ""))
        counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITY_ORDER}
        print(f"\n{len(projects)} project(s), {len(solutions)} solution(s): "
              f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info")
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
