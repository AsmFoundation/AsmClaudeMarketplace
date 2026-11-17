#!/usr/bin/env python3
"""Build every task-eval workspace with the real AsmFoundation.Sdk, and run what it produced.

Why this exists: `claude plugin eval` grades the files an agent wrote with regex and file
graders, which can only check the shape of the answer. Whether the answer works is decided by
`dotnet build` with the real SDK and its bundled NASM and ld.lld, and by running the outputs on
Linux. This script does that for both arms (with and without the plugin) of each task case,
from a `claude plugin eval --keep-temp --json` result.

Safety: the workspaces were written by an agent. Each one is copied into a fresh folder before
building, and a project that uses Exec, inline or external task code, downloads or deletes is
not built (none of the tasks needs one), so no agent-written command runs; targets that only
add items or copy files are built. Outputs run inside a throw-away Linux container (docker),
never on the host.

Usage:
    build_check.py --result task.json --feed <folder with AsmFoundation.*.nupkg>
                   --nuget-packages <isolated NuGet cache> --work <scratch folder>
                   [--docker] [--out build-check.json]

Exit codes: 0 = every workspace was checked (whatever the outcomes); 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

#: The generic MSBuild type GUID an .slnx entry for an .asmproj needs.
ASMPROJ_TYPE_GUID = "13B669BE-BB05-4DDF-9536-439F39A36129"

#: Container image used to run the Linux outputs; it has glibc 2.39 and the .NET 10 runtime.
RUNTIME_IMAGE = "mcr.microsoft.com/dotnet/runtime:10.0"

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
        True when the agent had written its own global.json (it is left untouched).
    """
    path = os.path.join(workspace, "global.json")
    if os.path.isfile(path):
        return True
    with open(path, "w", encoding="utf-8") as f:
        f.write('{ "msbuild-sdks": { "AsmFoundation.Sdk": "0.1.0" } }\n')
    return False


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


def check(case: str, workspace: str, args: argparse.Namespace, env: Dict[str, str]) -> Dict[str, object]:
    """Build (and where possible run) one workspace according to its task.

    Args:
        case: The eval case name (decides what to build and run).
        workspace: A fresh copy of the agent's workspace.
        args: Command-line options (feed, docker).
        env: Environment with the isolated NUGET_PACKAGES.

    Returns:
        A result dictionary: built (bool), ran (bool or None when not run), details and errors.
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
        if code == 0 and args.docker:
            dll = "Calc.App/bin/Debug/net10.0/Calc.App.dll"
            rc, out = docker_run(workspace, f"dotnet {dll}")
            result["ran"] = rc == 0 and re.search(r"\b10\b", out) is not None
            result["details"].append(f"run: exit {rc}: {out.strip()[-160:]}")
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
            exe = next((os.path.relpath(os.path.join(r, f), workspace).replace("\\", "/")
                        for r, _, fs in os.walk(os.path.join(workspace, "Tool", "bin")) for f in fs
                        if "." not in f), None)
            if exe:
                rc, out = docker_run(workspace, f"chmod +x '{exe}' && './{exe}'")
                result["ran"] = rc == 0
                result["details"].append(f"run {exe}: exit {rc}")
    elif case == "task-defines-keep-debug":
        ensure_global_json(workspace)
        checks = {"Debug": "%ifndef DEBUG\n%error \"DEBUG lost in Debug\"\n%endif\n",
                  "Release": "%ifdef DEBUG\n%error \"DEBUG defined in Release\"\n%endif\n"}
        outcomes = []
        for config, guard in checks.items():
            with open(os.path.join(workspace, "Fast", "check.asm"), "w", newline="\n", encoding="utf-8") as f:
                f.write(guard + "%ifndef USE_AVX2\n%error \"USE_AVX2 missing\"\n%endif\n"
                        "default rel\nsection .text\nglobal fast_check:function\nfast_check:\n    ret\n"
                        "section .note.GNU-stack noalloc noexec nowrite progbits\n")
            code, out = run(dotnet + ["build", "Fast/Fast.asmproj", "-c", config, "--no-incremental"] + nodereuse, workspace, env)
            outcomes.append(code == 0)
            if code:
                result["errors"].extend(f"{config}: {e}" for e in errors_of(out))
                result["errors"].extend(f"{config}: {l.strip()[:200]}" for l in out.splitlines() if "%error" in l or ": error:" in l)
        result["built"] = all(outcomes)
    elif case == "task-fix-pic-link-errors":
        ensure_global_json(workspace)
        with open(os.path.join(workspace, "Hash", "Hash.asmproj"), "w", encoding="utf-8") as f:
            f.write('<Project Sdk="AsmFoundation.Sdk" />\n')
        code, out = run(dotnet + ["build", "Hash/Hash.asmproj"] + nodereuse, workspace, env)
        result["built"] = code == 0
        result["errors"] = errors_of(out) if code else []
        if code == 0:
            inspector = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "asmsdk", "scripts", "inspect_elf.py")
            rc, out = run([sys.executable, inspector, "Hash/bin/Debug/libHash.so", "--json"], workspace, env)
            exports = sorted(e["name"] for e in json.loads(out)["exports"]) if rc == 0 else []
            result["details"].append(f"exports: {exports}")
            # The task's requirement: hash64 is the only public symbol.
            result["ran"] = exports == ["hash64"]
    return result


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; None means sys.argv[1:].

    Returns:
        0 when every workspace was processed; 2 on bad input.
    """
    parser = argparse.ArgumentParser(description="Build and run task-eval workspaces with the real AsmSdk.")
    parser.add_argument("--result", required=True, help="claude plugin eval --json output (with --keep-temp)")
    parser.add_argument("--feed", required=True, help="folder feed with AsmFoundation.Sdk and AsmFoundation.Toolchain packages")
    parser.add_argument("--nuget-packages", required=True, help="isolated NuGet global packages folder")
    parser.add_argument("--work", required=True, help="scratch folder for workspace copies")
    parser.add_argument("--docker", action="store_true", help="run Linux outputs in a container")
    parser.add_argument("--out", default="build-check.json", help="where to write the results")
    args = parser.parse_args(argv)
    try:
        with open(args.result, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"build_check: cannot read {args.result}: {exc}", file=sys.stderr)
        return 2
    env = dict(os.environ, NUGET_PACKAGES=os.path.abspath(args.nuget_packages), DOTNET_NOLOGO="1",
               DOTNET_CLI_TELEMETRY_OPTOUT="1", MSBUILDDISABLENODEREUSE="1")
    rows = []
    for case in doc.get("cases", []):
        for arm in ("with", "without"):
            for index, run_result in enumerate(case.get("arms", {}).get(arm, [])):
                trace = run_result.get("tracePath") or ""
                source = os.path.join(os.path.dirname(os.path.dirname(trace)), "home", "cwd")
                row = {"case": case["name"], "arm": arm, "run": index + 1, "graderScore": run_result.get("score")}
                if not os.path.isdir(source):
                    row.update(built=None, ran=None, details=["workspace not kept (run without --keep-temp?)"], errors=[])
                else:
                    target = os.path.join(args.work, f"{case['name']}-{arm}-{index + 1}")
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(source, target)
                    row["files"] = sorted(os.path.relpath(os.path.join(r, f), target).replace("\\", "/")
                                          for r, _, fs in os.walk(target) for f in fs)
                    row.update(check(case["name"], target, args, env))
                rows.append(row)
                print(f"{row['case']:28} {arm:8} run {row['run']}: built={row.get('built')} ran={row.get('ran')} "
                      f"{'; '.join(row.get('errors', [])[:2])[:160]}")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
