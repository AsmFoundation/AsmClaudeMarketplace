# asmsdk evaluation

This folder holds a [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals)
suite for the `asmsdk` plugin, plus a build check that runs the real AsmSdk on what the agent
wrote, and the committed results.

## What is measured

| Suite | Cases | Question | Graders |
|---|---|---|---|
| `trigger/` | 10 should-trigger + 10 near misses | Does Claude load the skill when, and only when, a request is about AsmSdk? | `tool_used: Skill` (`min: 0, max: 0` for near misses) |
| `task/` | 4 tasks, run **with** and **without** the plugin | Does the plugin make Claude's answer correct? | free `regex` / `file_exists` graders over the files written, plus `build_check.py` |

**Should-trigger requests** mix explicit ones (an `.asmproj`, ASM0001,
`AsmDefineConstants`) with implicit ones: "build my NASM with `dotnet build`", "C# calling
NASM in one solution", a raw `ld.lld` relocation error.

**Near misses** share vocabulary but belong elsewhere:

- instruction semantics (PDEP);
- CMake, Makefile, MASM or AT&T syntax;
- C intrinsics;
- trusted publishing for a C# library;
- a `.csproj` pre-build script;
- a .NET `DllNotFoundException` for SQLite;
- an ABI register question.

**Task cases** ask for files at fixed paths, so free graders can read them:

| Case | What it tests |
|---|---|
| `task-dotnet-interop` | a new `.slnx` with an asm shared library and a .NET app that P/Invokes it: `global.json` msbuild-sdks, the `.slnx` type GUID, `AsmLibraryName`, `ProjectReference`, `LibraryImport` name |
| `task-package-and-consume` | a static library packed as `Acme.Crc` 1.2.0, consumed by version from a folder feed: public include file in `include/` (otherwise not packed), `PackageReference`, `nuget.config` |
| `task-defines-keep-debug` | adding `USE_AVX2=1` without losing `DEBUG`: `AsmDefine` items, because `$(AsmDefineConstants);X` drops the default |
| `task-fix-pic-link-errors` | two `R_X86_64_PC32 … recompile with -fPIC` errors where only `hash64` may stay public: `hidden`, with the visibility before any size |

**`build_check.py`** copies each kept workspace and builds it with AsmFoundation.Sdk 0.1.0
and its bundled toolchain. It never builds a project that defines its own MSBuild targets.
Then it runs what it can in a Linux container:

| Case | Build check |
|---|---|
| `task-dotnet-interop` | the .NET app runs and prints 10 |
| `task-package-and-consume` | `Crc` is packed into `packages/`, `Tool` restores it by version and builds, and the executable exits 0 |
| `task-defines-keep-debug` | a probe source fails the build unless Debug defines `DEBUG` and `USE_AVX2`, and Release defines `USE_AVX2` but not `DEBUG` |
| `task-fix-pic-link-errors` | `libHash.so` links, and `hash64` is its only export |

Where a task did not ask for them, the check adds only a `global.json` entry and the local
feed for the SDK. The SDK was not on nuget.org when the suite was written.

## Running it

From `plugins/asmsdk`:

```sh
# Trigger suite: one arm (the Skill grader is the whole question).
claude plugin eval . --tag trigger --ablation none --runs 3 -j 4 --model claude-sonnet-5-5 --no-publish

# Task suite: with and without the plugin; keep the workspaces for the build check.
claude plugin eval . --tag task --runs 3 -j 4 --model claude-sonnet-5-5 \
  --allow-tools Write Edit --keep-temp --no-publish --json task.json

python evals/build_check.py --result task.json --feed <folder with AsmFoundation.*.nupkg> \
  --nuget-packages <empty folder> --work <scratch folder> --docker --out build-check.json
```

- **Bash is not needed:** the cases grant only Read, Glob, Grep, Skill, Write and Edit.
  This lets the suite run on native Windows, where `claude plugin eval` refuses shell
  grants for lack of a sandbox backend.
- **Clean up afterwards:** `--keep-temp` leaves each run's folder in the temp directory.
  Delete those folders once the build check is done.

## Results

See [`benchmarks/`](benchmarks). Each dated folder holds the raw `aggregate-result.json`
files, the HTML reports, `build-check.json` and a `SUMMARY.md` with the numbers and what
they mean.
