#!/usr/bin/env python3
"""Build every task-eval workspace with the real AsmFoundation.Sdk, and run what it produced.

Why this exists: `claude plugin eval` grades the files an agent wrote with regex and file
graders, which can only check the shape of the answer. Whether the answer works is decided by
`dotnet build` with the real SDK (0.3.0) and its bundled NASM and LLVM linkers, by the exports
of each runtime identifier's output (ELF, PE and Mach-O, read by the plugin's own
inspect_output.py), and by running the Linux outputs. This script does that for both arms
(with and without the plugin) of each task case, from a `claude plugin eval --keep-temp
--json` result.

The build host may be any OS: AsmSdk builds every RID from every host, so the Windows and
macOS libraries are built and inspected here, but only Linux outputs are ever run.

Safety: the workspaces were written by an agent. Each one is copied into a fresh folder before
building, and a project that uses Exec, inline or external task code, downloads or deletes is
not built (none of the tasks needs one), so no agent-written command runs; targets that only
add items or copy files are built. Outputs run inside a throw-away Linux container (docker),
never on the host; Windows and macOS outputs are only read, never run.

The same checks run on the suite's controls (evals/controls): a correct answer and wrong
ones for every task, each known to pass or fail. Run them after changing this script, a task
or the SDK version, before trusting a verdict on an agent's workspace.

Usage:
    build_check.py (--result task.json | --controls evals/controls)
                   --feed <folder with AsmFoundation.*.nupkg>
                   --nuget-packages <isolated NuGet cache> --work <scratch folder>
                   [--docker] [--out build-check.json]

Exit codes: 0 = every workspace was checked (whatever the outcomes of an eval's workspaces);
1 = a control did not pass or fail as its folder name says; 2 = bad input.
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
from typing import Dict, List, Optional, Tuple

#: The generic MSBuild type GUID an .slnx entry for an .asmproj needs.
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: The SDK version the prompts name, and the one a global.json gets when a task did not ask
#: the agent to write one. Keep it equal to the prompts' version: a workspace pinned to
#: another version would be built against an SDK its task never described.
SDK_VERSION = "0.3.0"

#: Container image used to run the Linux outputs; it has glibc 2.39 and the .NET 10 runtime.
RUNTIME_IMAGE = "mcr.microsoft.com/dotnet/runtime:10.0"

#: The plugin's inspector, which reads ELF, PE and Mach-O exports with the toolchain's own
#: llvm-readobj (found in the NuGet cache the build just filled).
INSPECTOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "asmsdk", "scripts", "inspect_output.py")

#: task-dotnet-interop: the library each RID must produce, named "calc" the way each OS
#: names a shared library (the prompt spells out all three).
CALC_LIBRARIES: Tuple[Tuple[str, str], ...] = (
    ("linux-x64", "libcalc.so"), ("win-x64", "calc.dll"), ("osx-x64", "libcalc.dylib"))

#: task-port-to-every-os: the project the prompt shows (the agent writes only the sources),
#: and the library each of its RIDs produces (AssemblyName defaults to the project name).
HASH_PROJECT = ('<Project Sdk="AsmFoundation.Sdk">\n  <PropertyGroup>\n'
                '    <RuntimeIdentifiers>linux-x64;win-x64;osx-x64</RuntimeIdentifiers>\n'
                '  </PropertyGroup>\n</Project>\n')
HASH_LIBRARIES: Tuple[Tuple[str, str], ...] = (
    ("linux-x64", "libHash.so"), ("win-x64", "Hash.dll"), ("osx-x64", "libHash.dylib"))

#: task-defines-keep-debug: the probe source's portable body. It must assemble and link for
#: every RID the agent's project lists (the prompt's project lists linux-x64 and win-x64), so
#: it exports through asmsdk.inc's FUNCTION and writes the ELF-only stack note on Linux only;
#: a Linux-only probe would fail the Windows build and blame the agent for it.
DEFINES_PROBE_BODY = ('%include "asmsdk.inc"\ndefault rel\nsection .text\nFUNCTION fast_check\n'
                      '    RETURN\nENDFUNCTION\n%ifdef LINUX\n'
                      'section .note.GNU-stack noalloc noexec nowrite progbits\n%endif\n')

#: Elements that would let a project run commands, load task code, download, or delete
#: outside the build's own outputs. A <Target> that only adds items or copies files is
#: allowed: agents without the skill often write one to copy the .so by hand, and refusing
#: those would hide how their projects actually fare.
UNSAFE_MSBUILD = re.compile(r"<\s*(Exec|UsingTask|DownloadFile|Delete|RemoveDir)\b|TaskFactory", re.IGNORECASE)


def run(cmd: List[str], cwd: str, env: Dict[str, str], timeout: int = 600) -> Tuple[int, str]:
    """Run a command and return its exit code and combined output.

    Args:
        cmd: The command and its arguments.
        cwd: Working folder.
        env: Full environment for the process.
        timeout: Seconds before the process is killed (a hung build counts as a failure).

    Returns:
        (exit code, stdout+stderr). A timeout returns exit code 124 with a note.
    """
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(cmd)}"


def errors_of(output: str) -> List[str]:
    """Pick the distinct error lines out of a build log, shortest form first.

    Args:
        output: dotnet build or pack output.

    Returns:
        Up to six distinct lines that contain "error", with machine-specific paths removed so
        the committed results do not expose local folders.
    """
    seen: List[str] = []
    for line in output.splitlines():
        if re.search(r"\berror\b", line) and "Build FAILED" not in line:
            line = re.sub(r"[A-Za-z]:[\\/][^\s\"']*[\\/]", "", line).strip()
            if line not in seen:
                seen.append(line)
    return seen[:6]


def ensure_feed(workspace: str, feed: str) -> None:
    """Make the workspace restore AsmFoundation.* from the local feed, keeping its own sources.

    The SDK is resolved through nuget.config (global.json's msbuild-sdks), so the eval feed
    must be in the config the build reads. An agent-written nuget.config is extended (a source
    and, when it maps packages, a mapping for AsmFoundation.*); without one, a minimal config is
    written at the workspace root.

    Args:
        workspace: The copied workspace.
        feed: Folder holding AsmFoundation.Sdk and AsmFoundation.Toolchain.<rid> packages.
    """
    config = next((os.path.join(workspace, n) for n in os.listdir(workspace) if n.lower() == "nuget.config"), None)
    source = f'<add key="asmsdk-eval-feed" value="{feed}" />'
    if config is None:
        with open(os.path.join(workspace, "nuget.config"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <packageSources>\n'
                    f'    {source}\n    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />\n'
                    '  </packageSources>\n</configuration>\n')
        return
    with open(config, encoding="utf-8-sig") as f:
        text = f.read()
    # After <clear /> when present, so the clear does not remove the eval feed again. The
    # replacements are functions, not template strings: the feed is a Windows path, and its
    # backslashes would otherwise be read as regex escapes (\U...).
    if re.search(r"<packageSources>\s*<clear\s*/>", text):
        text = re.sub(r"(<packageSources>\s*<clear\s*/>)", lambda m: m.group(1) + "\n    " + source, text, count=1)
    elif "<packageSources>" in text:
        text = text.replace("<packageSources>", "<packageSources>\n    " + source, 1)
    else:
        text = text.replace("<configuration>", f"<configuration>\n  <packageSources>\n    {source}\n  </packageSources>", 1)
    if "<packageSourceMapping>" in text:
        mapping = '<packageSource key="asmsdk-eval-feed"><package pattern="AsmFoundation.*" /></packageSource>'
        text = re.sub(r"(<packageSourceMapping>(\s*<clear\s*/>)?)", lambda m: m.group(1) + "\n    " + mapping, text, count=1)
    with open(config, "w", encoding="utf-8") as f:
        f.write(text)


def ensure_global_json(workspace: str) -> bool:
    """Add global.json's msbuild-sdks entry when a task did not ask the agent for one.

    Args:
        workspace: The copied workspace.

    Returns:
        True when the agent had written its own global.json (it is left untouched, so a wrong
        version there fails the build as it would for the user).
    """
    path = os.path.join(workspace, "global.json")
    if os.path.isfile(path):
        return True
    with open(path, "w", encoding="utf-8") as f:
        f.write('{ "msbuild-sdks": { "AsmFoundation.Sdk": "%s" } }\n' % SDK_VERSION)
    return False


def find_output(workspace: str, project_dir: str, rid: str, name: str) -> Optional[str]:
    """Find one RID's output of an asm project, whatever target framework built it.

    0.3.0 puts each RID's output in bin/<Configuration>/<TargetFramework>/<rid>/, and the
    tasks leave the target framework to the agent (freestanding or libc), so the framework
    folder is a wildcard.

    Args:
        workspace: The copied workspace.
        project_dir: The project's folder, relative to the workspace (e.g. "Calc.Native").
        rid: The runtime identifier folder (e.g. "win-x64").
        name: The file name the RID must produce (e.g. "calc.dll").

    Returns:
        The output's path relative to the workspace, with forward slashes; None when the
        Debug build produced no such file.
    """
    matches = sorted(glob.glob(os.path.join(workspace, project_dir, "bin", "Debug", "*", rid, name)))
    return os.path.relpath(matches[0], workspace).replace("\\", "/") if matches else None


def exports_of(workspace: str, output: str, env: Dict[str, str]) -> Tuple[Optional[List[str]], str]:
    """List the symbols an image exports, by their C names, with the plugin's inspector.

    Args:
        workspace: The copied workspace (the inspector runs there).
        output: The image's path relative to the workspace: an ELF .so, a PE .dll or a
            Mach-O .dylib.
        env: Environment with the isolated NUGET_PACKAGES, where the inspector finds the
            toolchain's llvm-readobj.

    Returns:
        (sorted export names, "") on success; (None, the inspector's message) when it could not
        read the file, which the caller reports instead of guessing.
    """
    rc, out = run([sys.executable, "-I", INSPECTOR, output, "--json"], workspace, env)
    if rc != 0:
        return None, out.strip()[-200:]
    try:
        # Images list exports as objects with a "name"; only archives use plain strings,
        # and no task inspects an archive.
        return sorted(e["name"] if isinstance(e, dict) else e for e in json.loads(out)["exports"]), ""
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"unreadable inspector output: {exc}"


def check_exports(workspace: str, project_dir: str, libraries: Tuple[Tuple[str, str], ...],
                  env: Dict[str, str], result: Dict[str, object]) -> Dict[str, Optional[List[str]]]:
    """Read the exports of each RID's library, recording what was found in the result's details.

    Args:
        workspace: The copied workspace.
        project_dir: The asm project's folder, relative to the workspace.
        libraries: (RID, file name) pairs the build must have produced.
        env: Environment with the isolated NUGET_PACKAGES.
        result: The case's result dictionary; one "details" line is appended per RID.

    Returns:
        RID -> sorted export names, or None for a RID whose library is missing or unreadable
        (such a RID never passes a check).
    """
    found: Dict[str, Optional[List[str]]] = {}
    for rid, name in libraries:
        output = find_output(workspace, project_dir, rid, name)
        if output is None:
            found[rid] = None
            result["details"].append(f"{rid}: no {name}")
            continue
        names, error = exports_of(workspace, output, env)
        found[rid] = names
        result["details"].append(f"{rid}: {name} exports {names}" if names is not None else f"{rid}: {name}: {error}")
    return found


def unsafe_projects(workspace: str) -> List[str]:
    """List agent-written MSBuild files that could run commands or delete files (not built, see module doc).

    Args:
        workspace: The copied workspace.

    Returns:
        Relative paths of offending files.
    """
    found = []
    for root, _, files in os.walk(workspace):
        for name in files:
            if name.lower().endswith((".asmproj", ".csproj", ".props", ".targets")):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    if UNSAFE_MSBUILD.search(f.read()):
                        found.append(os.path.relpath(path, workspace))
    return found


def docker_run(workspace: str, script: str) -> Tuple[int, str]:
    """Run a shell script in the Linux runtime container with the workspace mounted at /w.

    Args:
        workspace: Folder to mount (read-write, so chmod works on outputs built on Windows).
        script: sh script to run.

    Returns:
        (exit code, output) of the script.
    """
    mount = workspace
    if os.name == "nt":
        mount = os.path.abspath(workspace)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    return run(["docker", "run", "--rm", "-v", f"{mount}:/w", "-w", "/w", RUNTIME_IMAGE, "sh", "-c", script], workspace, env, 300)


def find_app(workspace: str) -> Optional[str]:
    """Find the Calc.App build the Linux container can run.

    A portable app (no RuntimeIdentifier, the default) is bin/Debug/net10.0/Calc.App.dll and
    finds libcalc.so under runtimes/linux-x64/native/ through its deps.json; an app the agent
    made RID-specific for Linux is one folder deeper. An app built for Windows or macOS only
    has no Linux build to run, which counts against it: the prompt asks for all three.

    Args:
        workspace: The copied workspace.

    Returns:
        The app's path relative to the workspace, with forward slashes; None when neither
        build exists.
    """
    for candidate in ("Calc.App/bin/Debug/net10.0/Calc.App.dll", "Calc.App/bin/Debug/net10.0/linux-x64/Calc.App.dll"):
        if os.path.isfile(os.path.join(workspace, candidate)):
            return candidate
    return None


def find_tool(workspace: str) -> Optional[str]:
    """Find Tool's Linux executable, preferring the linux-x64 build.

    Linux executables have no extension, which tells them apart from a Windows .exe the
    agent may also have built; the linux-x64 folder goes first because a musl build, which
    an agent may add, is equally runnable but not what the prompt asked for.

    Args:
        workspace: The copied workspace.

    Returns:
        The executable's path relative to the workspace, with forward slashes; None when the
        build produced none.
    """
    found = sorted(os.path.relpath(os.path.join(r, f), workspace).replace("\\", "/")
                   for r, _, fs in os.walk(os.path.join(workspace, "Tool", "bin")) for f in fs if "." not in f)
    found.sort(key=lambda path: "/linux-x64/" not in path)
    return found[0] if found else None


def check(case: str, workspace: str, args: argparse.Namespace, env: Dict[str, str]) -> Dict[str, object]:
    """Build (and where possible run) one workspace according to its task.

    Args:
        case: The eval case name (decides what to build and run).
        workspace: A fresh copy of the agent's workspace.
        args: Command-line options (feed, docker).
        env: Environment with the isolated NUGET_PACKAGES.

    Returns:
        A result dictionary: built (bool: the task's build exited 0), ran (bool: every check
        after the build passed, the Linux run and the exports of each RID's output; None when
        nothing could be checked, e.g. a run without --docker for a task that only runs),
        details (what was found) and errors (the build's distinct error lines).
    """
    result: Dict[str, object] = {"built": False, "ran": None, "details": [], "errors": []}
    unsafe = unsafe_projects(workspace)
    if unsafe:
        result["details"].append(f"not built: defines MSBuild targets/tasks in {unsafe}")
        return result
    ensure_feed(workspace, args.feed)
    dotnet = ["dotnet"]
    nodereuse = ["-nodeReuse:false", "-v:m"]
    if case == "task-dotnet-interop":
        result["details"].append("agent global.json" if ensure_global_json(workspace) else "global.json injected")
        code, out = run(dotnet + ["build", "Calc.slnx"] + nodereuse, workspace, env)
        result["built"] = code == 0
        result["errors"] = errors_of(out) if code else []
        if code == 0:
            # Windows and macOS libraries cannot run here, but a missing export (a plain
            # global is no DLL export) is what fails there first, and the file name decides
            # whether .NET finds the library at all.
            exports = check_exports(workspace, "Calc.Native", CALC_LIBRARIES, env, result)
            passed = all(names is not None and "calc_sum" in names for names in exports.values())
            if args.docker:
                dll = find_app(workspace)
                if dll is None:
                    passed = False
                    result["details"].append("run: no Linux build of Calc.App.dll")
                else:
                    rc, out = docker_run(workspace, f"dotnet {dll}")
                    passed = passed and rc == 0 and re.search(r"\b10\b", out) is not None
                    result["details"].append(f"run {dll}: exit {rc}: {out.strip()[-160:]}")
            result["ran"] = passed
    elif case == "task-package-and-consume":
        result["details"].append("agent global.json" if ensure_global_json(workspace) else "global.json injected")
        # A previous run's Acme.Crc must not satisfy this run's restore.
        shutil.rmtree(os.path.join(env["NUGET_PACKAGES"], "acme.crc"), ignore_errors=True)
        code, out = run(dotnet + ["pack", "Crc/Crc.asmproj", "-o", "packages"] + nodereuse, workspace, env)
        if code != 0:
            result["errors"] = ["pack: " + e for e in errors_of(out)]
            return result
        code, out = run(dotnet + ["build", "Tool/Tool.asmproj"] + nodereuse, workspace, env)
        result["built"] = code == 0
        result["errors"] = errors_of(out) if code else []
        if code == 0 and args.docker:
            exe = find_tool(workspace)
            if exe:
                rc, out = docker_run(workspace, f"chmod +x '{exe}' && './{exe}'")
                result["ran"] = rc == 0
                result["details"].append(f"run {exe}: exit {rc}")
            else:
                result["ran"] = False
                result["details"].append("run: no Linux executable under Tool/bin")
    elif case == "task-defines-keep-debug":
        ensure_global_json(workspace)
        checks = {"Debug": "%ifndef DEBUG\n%error \"DEBUG lost in Debug\"\n%endif\n",
                  "Release": "%ifdef DEBUG\n%error \"DEBUG defined in Release\"\n%endif\n"}
        outcomes = []
        for config, guard in checks.items():
            with open(os.path.join(workspace, "Fast", "check.asm"), "w", newline="\n", encoding="utf-8") as f:
                f.write(guard + "%ifndef USE_AVX2\n%error \"USE_AVX2 missing\"\n%endif\n" + DEFINES_PROBE_BODY)
            # Every RID the project lists is an inner build, so each one checks the symbols.
            code, out = run(dotnet + ["build", "Fast/Fast.asmproj", "-c", config, "--no-incremental"] + nodereuse, workspace, env)
            outcomes.append(code == 0)
            if code:
                result["errors"].extend(f"{config}: {e}" for e in errors_of(out))
                result["errors"].extend(f"{config}: {l.strip()[:200]}" for l in out.splitlines() if "%error" in l or ": error:" in l)
        result["built"] = all(outcomes)
    elif case == "task-port-to-every-os":
        ensure_global_json(workspace)
        # The prompt shows this project and asks for the sources only, so an agent-written
        # project (one adding an ExportsFile, say) is replaced by the one it was given.
        with open(os.path.join(workspace, "Hash", "Hash.asmproj"), "w", encoding="utf-8") as f:
            f.write(HASH_PROJECT)
        code, out = run(dotnet + ["build", "Hash/Hash.asmproj"] + nodereuse, workspace, env)
        result["built"] = code == 0
        result["errors"] = errors_of(out) if code else []
        if code == 0:
            # The task's requirement: hash64 is the only export of every RID's library.
            exports = check_exports(workspace, "Hash", HASH_LIBRARIES, env, result)
            result["ran"] = all(names == ["hash64"] for names in exports.values())
    return result


#: A workspace to check: (case name, arm, run number, workspace folder or None when it was not
#: kept, grader score or None). The arm is "with"/"without" for eval runs and "pass"/"fail"
#: for controls.
Source = Tuple[str, str, int, Optional[str], Optional[float]]


def eval_sources(doc: Dict[str, object]) -> List[Source]:
    """List the workspaces of a `claude plugin eval --keep-temp --json` result.

    Each run's workspace is the home/cwd folder beside its trace's folder: the layout that
    `claude plugin eval --keep-temp` leaves in the temp directory.

    Args:
        doc: The parsed result.

    Returns:
        One entry per run of each arm ("with", then "without"), in the result's case order; the
        folder is None when the run's folder is gone (an eval run without --keep-temp, or one
        already cleaned up).
    """
    sources: List[Source] = []
    for case in doc.get("cases", []):
        for arm in ("with", "without"):
            for index, run_result in enumerate(case.get("arms", {}).get(arm, [])):
                trace = run_result.get("tracePath") or ""
                source = os.path.join(os.path.dirname(os.path.dirname(trace)), "home", "cwd")
                sources.append((case["name"], arm, index + 1, source if os.path.isdir(source) else None, run_result.get("score")))
    return sources


def control_sources(folder: str) -> List[Source]:
    """List the known answers of a controls folder.

    The layout is <case>/pass-<n>/ for a correct answer, which must build and pass every check,
    and <case>/fail-<n>/ for a wrong one, which must not. Running them proves that the check
    still tells the two apart after a change to this script, to the SDK or to a task; other
    folder names are ignored, so notes can sit beside them.

    Args:
        folder: The controls folder (evals/controls).

    Returns:
        One entry per control, arm "pass" or "fail", sorted by case and number; no score.
    """
    sources: List[Source] = []
    for case in sorted(os.listdir(folder)):
        case_dir = os.path.join(folder, case)
        if not os.path.isdir(case_dir):
            continue
        controls = []
        for name in os.listdir(case_dir):
            match = re.fullmatch(r"(pass|fail)-(\d+)", name)
            if match and os.path.isdir(os.path.join(case_dir, name)):
                controls.append((match.group(1), int(match.group(2)), os.path.join(case_dir, name)))
        sources.extend((case, arm, number, path, None) for arm, number, path in sorted(controls))
    return sources


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; None means sys.argv[1:].

    Returns:
        0 when every workspace was processed (and, with --controls, each control passed or
        failed as its folder name says); 1 when a control did not; 2 on bad input.
    """
    parser = argparse.ArgumentParser(description="Build and run task-eval workspaces with the real AsmSdk.")
    sources_group = parser.add_mutually_exclusive_group(required=True)
    sources_group.add_argument("--result", help="claude plugin eval --json output (with --keep-temp)")
    sources_group.add_argument("--controls", help="folder of known answers (<case>/pass-<n>, <case>/fail-<n>); "
                                                  "exit 1 unless each one passes or fails as named")
    parser.add_argument("--feed", required=True, help="folder feed with AsmFoundation.Sdk and AsmFoundation.Toolchain packages")
    parser.add_argument("--nuget-packages", required=True, help="isolated NuGet global packages folder")
    parser.add_argument("--work", required=True, help="scratch folder for workspace copies")
    parser.add_argument("--docker", action="store_true", help="run Linux outputs in a container")
    parser.add_argument("--out", default="build-check.json", help="where to write the results")
    args = parser.parse_args(argv)
    if args.controls:
        if not os.path.isdir(args.controls):
            print(f"build_check: no controls folder {args.controls}", file=sys.stderr)
            return 2
        sources = control_sources(args.controls)
    else:
        try:
            with open(args.result, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"build_check: cannot read {args.result}: {exc}", file=sys.stderr)
            return 2
        sources = eval_sources(doc)
    env = dict(os.environ, NUGET_PACKAGES=os.path.abspath(args.nuget_packages), DOTNET_NOLOGO="1",
               DOTNET_CLI_TELEMETRY_OPTOUT="1", MSBUILDDISABLENODEREUSE="1")
    rows = []
    unexpected = 0
    for case_name, arm, number, source, score in sources:
        row = {"case": case_name, "arm": arm, "run": number, "graderScore": score}
        if source is None:
            row.update(built=None, ran=None, details=["workspace not kept (run without --keep-temp?)"], errors=[])
        else:
            target = os.path.join(args.work, f"{case_name}-{arm}-{number}")
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
            row["files"] = sorted(os.path.relpath(os.path.join(r, f), target).replace("\\", "/")
                                  for r, _, fs in os.walk(target) for f in fs)
            row.update(check(case_name, target, args, env))
        verdict = ""
        if args.controls:
            # A control passes when it built and no check after the build failed; a check that
            # could not run (the Linux run without --docker) counts neither way.
            passed = row["built"] is True and row["ran"] is not False
            row["verdict"] = "as expected" if passed == (arm == "pass") else "UNEXPECTED"
            unexpected += row["verdict"] == "UNEXPECTED"
            verdict = f"[{row['verdict']}] "
        rows.append(row)
        print(f"{row['case']:28} {arm:8} run {row['run']}: {verdict}built={row.get('built')} ran={row.get('ran')} "
              f"{'; '.join(row.get('errors', [])[:2])[:160]}")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
