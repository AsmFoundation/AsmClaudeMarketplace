#!/usr/bin/env python3
"""Lint AsmSdk projects and their NASM sources for the mistakes that break builds or outputs.

Why this exists: AsmFoundation.Sdk 0.1.0 has failure modes that are silent (a stale build, a
package without include files, DEBUG quietly undefined) or that surface as linker messages far
from their cause ("relocation R_X86_64_PC32 cannot be used against symbol"). Each check here
encodes one of them, measured against the 0.1.0 targets and the bundled NASM 3.02 / ld.lld
23.1.5, and reports the file, line and fix before anything is built.

What it reads: every *.asmproj under the given path (or the given .asmproj), the projects they
reference, their *.asm / *.inc files, the nearest global.json and Directory.Build.props, and
any *.slnx under the path. It never writes. It does not evaluate MSBuild: properties are read
as written, conditions are noted but not evaluated, so a property set only under a condition
is treated as set. Source checks are line-based heuristics over NASM syntax, tuned to have no
false errors on the AsmSdk samples; treat a warning as "look here", an error as "this will
fail as written".

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
from typing import Dict, Iterable, List, Optional, Set, Tuple

#: The SDK version whose behavior these checks encode.
DOCUMENTED_SDK_VERSION = "0.1.0"

#: Generic MSBuild project type; an .slnx entry for an .asmproj needs it (MSB4025 otherwise).
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: Folders never scanned for sources: build outputs and tool state.
SKIP_DIRS = {"bin", "obj", ".git", ".vs", ".idea", "node_modules", "artifacts"}

#: Functions the 0.1.0 libc stub (stubs/libc.asm) defines. A Libc executable that calls a
#: function outside this set fails with "undefined symbol" unless it is an AsmLibcSymbol item.
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

#: NASM words that can appear inside operands without being symbol references.
OPERAND_KEYWORDS = {"rel", "abs", "wrt", "byte", "word", "dword", "qword", "tword", "oword", "yword",
                    "zword", "ptr", "strict", "nosplit", "seg", "near", "far", "short", "to"}

IDENT = r"[A-Za-z_.?$][\w.$#@~?]*"
DATA_DIRECTIVES = ("db", "dw", "dd", "dq", "dt", "do", "dy", "dz")
RES_DIRECTIVES = ("resb", "resw", "resd", "resq", "rest", "reso", "resy", "resz")

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


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

        Checks that must see conditional assignments (an OS-specific AsmLinkFlags) use this
        instead of prop(), which keeps only the last value.

        Args:
            name: Property name.

        Returns:
            (value, condition) pairs in document order; condition is "" when unconditional.
        """
        return [v for k, vs in self.props.items() if k.lower() == name.lower() for v in vs]

    @property
    def kind(self) -> str:
        """The AsmOutputKind the SDK will compute: SharedLibrary, StaticLibrary, Executable or Objects."""
        explicit = self.prop("AsmOutputKind")
        if explicit:
            return explicit
        output_type = (self.prop("OutputType") or "Library").lower()
        return {"exe": "Executable", "winexe": "Executable", "staticlibrary": "StaticLibrary",
                "objects": "Objects"}.get(output_type, "SharedLibrary")

    @property
    def runtime(self) -> str:
        """AsmRuntime as the SDK reads it: "Libc" or "Freestanding"."""
        return "Libc" if (self.prop("AsmRuntime") or "").lower() == "libc" else "Freestanding"

    @property
    def produces_static(self) -> bool:
        """True when a referencing project will link a .a from this one."""
        return self.kind == "StaticLibrary" or (self.prop("AsmProduceStaticLibrary") or "").lower() == "true"

    @property
    def pic_required(self) -> bool:
        """True when the linker will reject non-PIC code: shared libraries and Libc PIEs."""
        return self.kind == "SharedLibrary" or (self.kind == "Executable" and self.runtime == "Libc")


@dataclass
class SourceInfo:
    """Facts extracted from one NASM file (comments removed, line numbers kept)."""

    path: str
    lines: List[Tuple[int, str]]
    default_rel: bool = False
    has_gnu_stack: bool = False
    includes: List[Tuple[int, str]] = field(default_factory=list)
    externs: Set[str] = field(default_factory=set)
    globals: Dict[str, Tuple[int, str]] = field(default_factory=dict)
    labels: Set[str] = field(default_factory=set)
    constants: Set[str] = field(default_factory=set)


def visibility(qualifiers: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a `global` declaration's qualifiers into the visibility NASM applies and one it ignores.

    NASM 3.02 reads the visibility keyword only right after the type: `function hidden (size)`
    and `data hidden 8` hide the symbol, while `function (size) hidden` and `data 8 hidden`
    are accepted without any warning and leave it exported and preemptible (verified).

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
    for number, text in enumerate(raw, 1):
        code = strip_comment(text)
        if not code.strip():
            continue
        info.lines.append((number, code))
        low = code.strip().lower()
        if re.match(r"^\[?\s*default\s+rel\b", low):
            info.default_rel = True
        if re.match(r"^\[?\s*(section|segment)\s+\.note\.gnu-stack\b", low):
            info.has_gnu_stack = True
        m = re.match(r'^\s*%include\s+["<](.+?)[">]', code)
        if m:
            info.includes.append((number, m.group(1)))
            continue
        if re.match(r"^\s*struc\b", low):
            in_struc = True
        elif re.match(r"^\s*endstruc\b", low):
            in_struc = False
        m = re.match(r"^\s*\[?\s*extern\s+(.+?)\]?\s*$", code, re.IGNORECASE)
        if m:
            for name in m.group(1).split(","):
                info.externs.add(name.split(":")[0].strip().lstrip("$"))
            continue
        m = re.match(r"^\s*\[?\s*global\s+(.+?)\]?\s*$", code, re.IGNORECASE)
        if m:
            # "global a:function hidden, b" -> each name with its qualifiers.
            for part in re.split(r",(?![^()]*\))", m.group(1)):
                name, _, qualifiers = part.strip().partition(":")
                info.globals[name.strip().lstrip("$")] = (number, qualifiers.strip().lower())
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
    """Compute the project's AsmSource and AsmInclude files the way the SDK's defaults do.

    Args:
        project: The project.

    Returns:
        (sources, include files) as absolute paths: default globs (unless
        EnableDefaultAsmItems=false) plus explicit Include items, minus Remove items.
    """
    defaults = (project.prop("EnableDefaultAsmItems") or "true").lower() != "false"
    sources = _walk_files(project.dir, ".asm") if defaults else []
    includes = _walk_files(project.dir, ".inc") if defaults else []
    for item in project.items.get("AsmSource", []):
        sources.extend(_resolve_item_paths(project, item.get("Include", "")))
    for item in project.items.get("AsmInclude", []):
        includes.extend(_resolve_item_paths(project, item.get("Include", "")))
    removed = set()
    for item in project.items.get("AsmSource", []):
        removed.update(os.path.normcase(p) for p in _resolve_item_paths(project, item.get("Remove", "")))
    sources = [s for s in dict.fromkeys(os.path.normpath(p) for p in sources) if os.path.normcase(s) not in removed]
    return sources, list(dict.fromkeys(os.path.normpath(p) for p in includes))


def include_dirs(project: Project, referenced: List[Project]) -> List[Tuple[str, str]]:
    """The include search order NASM will see, as (folder, origin) pairs.

    NASM 3.02 tries the working directory (the project folder) first, then each -I folder:
    include/, the project folder, AsmIncludeDirectory items, then referenced projects'
    public folders (include/ or their project folder).

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


class Linter:
    """Runs every check over a set of projects and collects Findings.

    One instance per run: it caches parsed projects and sources so a library referenced by
    several projects is read once.
    """

    def __init__(self) -> None:
        self.findings: List[Finding] = []
        self._projects: Dict[str, Project] = {}
        self._sources: Dict[str, SourceInfo] = {}
        self._reported: Set[Tuple[str, str, int]] = set()

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

    # -- repository-level checks --------------------------------------------------------------

    def check_global_json(self, project: Project) -> None:
        """global.json must name AsmFoundation.Sdk unless the Sdk attribute carries a version.

        The nearest global.json above the project is the one `dotnet` uses, so only that one
        is judged; a missing entry means MSB4236 before anything builds.

        Args:
            project: The project whose SDK resolution is checked.
        """
        if "/" in project.sdk:  # Sdk="AsmFoundation.Sdk/0.1.0" needs no global.json entry
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
                             '"msbuild-sdks": { "AsmFoundation.Sdk": "0.1.0" }')
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
                 'add global.json: { "msbuild-sdks": { "AsmFoundation.Sdk": "0.1.0" } }')

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
        toolchain = p.prop("AsmToolchain")
        if toolchain and toolchain not in ("Bundled", "System"):
            self.add("error", "ASMPRJ009", p.path, line("AsmToolchain", 0),
                     f"AsmToolchain='{toolchain}' fails with ASM0002", "use Bundled or System")
        output_type = p.prop("OutputType")
        if output_type and output_type.lower() not in ("library", "staticlibrary", "exe", "winexe", "objects"):
            self.add("warning", "ASMPRJ010", p.path, line("OutputType", 0),
                     f"OutputType='{output_type}' is not an AsmSdk kind; it builds a shared library",
                     "Library, StaticLibrary, Exe or Objects")
        for value, _ in p.prop_entries("AsmDefineConstants"):
            if "DEBUG" not in value.upper().split(";") and "DEBUG" not in [v.split("=")[0].strip().upper() for v in value.split(";")]:
                keeps = "$(AsmDefineConstants)" in value
                self.add("warning", "ASMPRJ001", p.path, line("AsmDefineConstants", 0),
                         "setting AsmDefineConstants replaces the default DEBUG symbol"
                         + (" ($(AsmDefineConstants) is still empty in the project body, so this does not keep DEBUG)" if keeps else ""),
                         '<AsmDefine Include="NAME" /> items add symbols and keep DEBUG')
                break
        if p.runtime == "Libc" and p.kind in ("StaticLibrary", "Objects"):
            self.add("info", "ASMPRJ011", p.path, line("AsmRuntime", 0),
                     f"AsmRuntime=Libc has no effect on {p.kind}; the project that links this code decides")
        if p.runtime == "Libc" and p.kind == "Executable" and p.prop("AsmEntryPoint"):
            self.add("warning", "ASMPRJ012", p.path, line("AsmEntryPoint", 0),
                     "AsmEntryPoint on a Libc executable drops the SDK's crt1: glibc is never initialized unless your entry calls __libc_start_main",
                     "remove AsmEntryPoint and define main")
        for value, condition in p.prop_entries("AsmLinkFlags"):
            if "$ORIGIN" in value and "IsOSPlatform" not in condition and "'$ORIGIN'" not in value:
                self.add("warning", "ASMPRJ006", p.path, line("AsmLinkFlags", 0),
                         "$ORIGIN unquoted: Linux/macOS build machines run the link through /bin/sh, which expands it to nothing",
                         "set it per OS: -rpath $ORIGIN on Windows, -rpath '$ORIGIN' elsewhere (IsOSPlatform conditions)")
        props_file = self._directory_build_props(p)
        flags = " ".join(v for v, _ in p.prop_entries("AsmFlags")) + " " + " ".join(
            v for v, _ in (props_file.prop_entries("AsmFlags") if props_file else []))
        if "-Xvc" not in flags:
            self.add("info", "ASMPRJ008", p.path, 0,
                     "NASM messages are not MSBuild diagnostics in 0.1.0 (only MSB3073 is counted; -v:q hides NASM's line)",
                     "<AsmFlags>-Xvc</AsmFlags>, best in Directory.Build.props under Condition=\"'$(UsingAsmFoundationSdk)' == 'true'\"")
        link_flags = " ".join(v for v, _ in p.prop_entries("AsmLinkFlags")) + " " + " ".join(
            v for v, _ in (props_file.prop_entries("AsmLinkFlags") if props_file else []))
        if p.kind == "SharedLibrary" and "-z defs" not in link_flags and "--no-undefined" not in link_flags:
            self.add("info", "ASMPRJ007", p.path, 0,
                     "a shared library links with undefined symbols; a misspelled extern fails only when the library loads",
                     "<AsmLinkFlags>-z defs</AsmLinkFlags>")
        referenced = self.references(p)
        for ref in referenced:
            if ref.kind == "Objects":
                self.add("error", "ASMREF002", p.path, line("ProjectReference", 0),
                         f"reference to {os.path.basename(ref.path)} (OutputType=Objects): 0.1.0 passes its object paths relative to the wrong project, and the link fails with 'cannot open .../x.o'",
                         "make the referenced project a StaticLibrary")
            elif p.kind == "Executable" and p.runtime == "Freestanding" and not ref.produces_static and ref.kind == "SharedLibrary":
                self.add("error", "ASMREF001", p.path, line("ProjectReference", 0),
                         f"a freestanding executable links -static, but {os.path.basename(ref.path)} produces only a .so: 'attempted static link of dynamic object'",
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
        self.check_sources(p, referenced)

    def _directory_build_props(self, project: Project) -> Optional[Project]:
        """The Directory.Build.props MSBuild imports for a project (the nearest one above it).

        Solution-wide asm settings (AsmFlags -Xvc, AsmLinkFlags -z defs) usually live there, so
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

    def check_sources(self, p: Project, referenced: List[Project]) -> None:
        """Run the per-file NASM checks for one project's sources.

        Symbol resolution looks at this project and everything it references, because the
        linker sees all of their outputs; packages cannot be read, so with a PackageReference
        present an unresolved symbol is only a warning.

        Args:
            p: The project.
            referenced: Its .asmproj references, transitively.
        """
        sources, includes = project_sources(p)
        dirs = include_dirs(p, referenced)
        project_files = sources + includes
        infos = {s: self.source(s) for s in project_files if os.path.isfile(s)}
        # Symbols defined anywhere in this project or the projects it references.
        defined: Set[str] = set()
        hidden: Set[str] = set()
        for ref in [p] + referenced:
            for path in project_sources(ref)[0]:
                if os.path.isfile(path):
                    info = self.source(path)
                    for name, (_, qualifiers) in info.globals.items():
                        if name in info.labels:
                            defined.add(name)
                            # Only a visibility NASM actually applies makes PLT/GOT unnecessary.
                            if visibility(qualifiers)[0]:
                                hidden.add(name)
        libc_extra = {i.get("Include", "").strip() for i in p.items.get("AsmLibcSymbol", [])}
        has_packages = bool(p.items.get("PackageReference"))
        included_asm: Set[str] = set()
        entry_found = False
        entry = p.prop("AsmEntryPoint") or ("main" if p.runtime == "Libc" and p.kind == "Executable" else "_start")
        for path in sources:
            info = infos.get(path)
            if info is None:
                continue
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
            self._check_source_lines(p, info, externs, hidden, default_rel)
            if not info.has_gnu_stack:
                self.add("info", "ASMSRC006", path, 0,
                         "no .note.GNU-stack section: the SDK links with -z noexecstack, but other linkers of this object or archive may mark the stack executable",
                         "section .note.GNU-stack noalloc noexec nowrite progbits")
            for name, (number, qualifiers) in info.globals.items():
                ignored = visibility(qualifiers)[1]
                if ignored:
                    self.add("warning", "ASMSRC013", path, number,
                             f"'{ignored}' after the size is ignored by NASM (no warning): '{name}' stays exported and preemptible",
                             f"put the visibility first: global {name}:{qualifiers.split()[0] if qualifiers.split() else 'function'} {ignored} <size>")
                if name.lower() in KEYWORD_NAMES:
                    self.add("error", "ASMSRC008", path, number,
                             f"symbol '{name}' is a NASM keyword or mnemonic and does not parse as a label",
                             f"write it as ${name} in the definition and every reference")
                elif not re.search(r"\b(function|data|object|func)\b", qualifiers) and name in info.labels:
                    self.add("info", "ASMSRC007", path, number,
                             f"'global {name}' has no type: it is exported with type NONE and size 0",
                             f"global {name}:function ({name}.end - {name})  ; or :data <size>")
            # Undefined references: externs no source here (or in references) defines.
            for name in sorted(externs - defined):
                if p.runtime == "Libc" and (name in LIBC_STUB_FUNCTIONS or name in libc_extra):
                    continue
                number = next((n for n, c in info.lines if re.search(rf"\bextern\b.*\b{re.escape(name)}\b", c)), 0)
                if p.kind == "Executable" and p.runtime == "Libc":
                    self.add("warning" if has_packages else "error", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project, its references or the libc stub: the link fails with 'undefined symbol: {name}'"
                             + (" unless a package defines it" if has_packages else ""),
                             f'a libc function: <AsmLibcSymbol Include="{name}" />; otherwise add the reference or package that defines it')
                elif p.kind == "Executable":
                    self.add("warning" if has_packages else "error", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project or its references: the link fails with 'undefined symbol: {name}'"
                             + (" unless a package defines it" if has_packages else ""),
                             "add the ProjectReference or PackageReference that defines it, or fix the name")
                elif p.kind == "SharedLibrary" and not has_packages:
                    self.add("info", "ASMSRC012", path, number,
                             f"'{name}' is not defined in this project, its references"
                             + (" or the libc stub" if p.runtime == "Libc" else "")
                             + ": a shared library links anyway and fails at load time if nothing provides it",
                             "-z defs in AsmLinkFlags turns this into a link error")
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
                     f"no source defines 'global {entry}' with a label: "
                     + ("the SDK's crt1 calls main" if entry == "main" else f"the executable's entry point is {entry}"),
                     f"global {entry}:function, and the {entry}: label")

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

    def _check_source_lines(self, p: Project, info: SourceInfo, externs: Set[str], hidden: Set[str], default_rel: bool) -> None:
        """The instruction-level checks: addressing, calls, data relocations, keyword labels.

        Args:
            p: The project (its kind decides whether PIC is required).
            info: The file.
            externs: Symbols this file references but does not define (own and included externs).
            hidden: Symbols defined hidden somewhere in the project (safe without PLT/GOT).
            default_rel: Whether `default rel` is in effect (this file or a local include).
        """
        shared = p.kind == "SharedLibrary"
        pic = p.pic_required
        portable = p.kind in ("StaticLibrary", "Objects")
        section, writable = ".text", False
        for number, code in info.lines:
            low = code.strip().lower()
            m = re.match(r"^\[?\s*(?:section|segment)\s+(\S+)(.*)$", low)
            if m:
                section = m.group(1).rstrip("]")
                attrs = m.group(2)
                writable = section in (".data", ".bss", ".tdata", ".tbss") or bool(re.search(r"\bwrite\b", attrs)) and not re.search(r"\bnowrite\b", attrs)
                if section == ".data.rel.ro" and not re.search(r"\bwrite\b", attrs):
                    self.add("warning", "ASMSRC005", info.path, number,
                             "NASM does not know .data.rel.ro and makes it read-only: absolute addresses (dq label) in it fail to link in a .so or PIE",
                             "section .data.rel.ro progbits alloc noexec write align=8")
                continue
            if low.startswith("%") or low.startswith("["):
                continue
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
                    names = [t for t in ident if (t.lstrip("$") in info.labels or t.lstrip("$") in externs) and not re.search(r"\$\$?|-", operand)]
                    if names and (pic or portable):
                        if directive == "dd":
                            self.add("error" if pic else "warning", "ASMPIC005", info.path, number,
                                     f"'dd {names[0]}' stores a 32-bit absolute address: position-independent outputs cannot relocate it",
                                     f"store an offset instead: dd {names[0]} - <table label>")
                        elif not writable:
                            self.add("error" if pic else "warning", "ASMPIC005", info.path, number,
                                     f"'dq {names[0]}' in read-only {section}: 'relocation R_X86_64_64 cannot be used against local symbol' in a .so or PIE",
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
                regs = [t for t in tokens if t.lower() in REGISTERS]
                symbols = [t.lstrip("$") for t in tokens if t.lower() not in REGISTERS and t.lstrip("$") not in info.constants]
                symbols = [s for s in symbols if s in info.labels or s in externs]
                if not symbols:
                    continue
                explicit = re.match(r"^\s*(rel|abs)\b", mem_low) is not None or re.search(r"\b(qword|dword|word|byte)\s+(rel|abs)\b", mem_low)
                if not regs and not explicit and not default_rel:
                    self.add("error" if pic else "warning", "ASMPIC001", info.path, number,
                             f"[{mem.strip()}] without default rel is absolute addressing: "
                             + ("'relocation R_X86_64_32S cannot be used against local symbol' in a .so or PIE" if pic
                                else "NASM 3 warns 'implicit DEFAULT ABS is deprecated' (an error with TreatWarningsAsErrors)"),
                             "put 'default rel' at the top of the file")
                if shared and "..got" not in mem_low:
                    for s in symbols:
                        if s in externs and s not in hidden:
                            self.add("error", "ASMPIC003", info.path, number,
                                     f"[{mem.strip()}] reads '{s}' from another object or library directly: 'relocation R_X86_64_PC32 cannot be used against symbol '{s}''",
                                     f"mov rax, [rel {s} wrt ..got] then use [rax]; or define it 'global {s}:data hidden' in this library")
                            break
            # calls and jumps to other objects
            if shared and op in ("call", "jmp"):
                target = re.match(rf"\s*({IDENT})\s*(.*)$", operands)
                if target:
                    name = target.group(1).lstrip("$")
                    if name in externs and name not in hidden and "..plt" not in target.group(2).lower():
                        self.add("error", "ASMPIC002", info.path, number,
                                 f"{op} {name}: a direct call to another object or library: 'relocation R_X86_64_PC32 cannot be used against symbol '{name}''",
                                 f"{op} {name} wrt ..plt; or define it 'global {name}:function hidden' when it is this library's own helper")
            # absolute addresses as immediates
            if (pic or portable) and op in ("mov", "push", "cmp", "add", "sub"):
                parts = [x.strip() for x in operands.split(",")]
                if len(parts) >= 1:
                    src = parts[-1]
                    if re.fullmatch(IDENT, src) and (src.lstrip("$") in info.labels or src.lstrip("$") in externs) and src.lstrip("$") not in info.constants:
                        self.add("error" if pic else "warning", "ASMPIC004", info.path, number,
                                 f"'{op} ..., {src}' uses the absolute address of {src}: 'relocation R_X86_64_64 (or _32) cannot be used' in a .so or PIE",
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
    for path in projects:
        project = linter.project(path)
        if project is None:
            continue
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
