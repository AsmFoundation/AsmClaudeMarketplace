# Roadmap: plugins the AsmFoundation ecosystem can use next

The marketplace holds one plugin per topic. This list is the proposal of what comes after
`asmsdk`, ordered by how much each would change a working session today.

Each entry names the source material that already exists, so a plugin can be written from
measured facts rather than from scratch. None of these is built yet. Each needs its owner's
go-ahead, and then the same treatment as `asmsdk`: verified facts, tested scripts, and a
committed evaluation.

| # | Plugin | What Claude would do better with it | Source material that exists today |
|---|---|---|---|
| 1 | `asm-perf` | Optimize x86-64 hot paths with a repertoire: memory latency hiding, branch elimination, SWAR, allocation, system calls, concurrency, protocol parsing, code layout. Each technique comes with its "when", its "why" and how to measure it | KvAsm's `asm-perf-cookbook` skill (947 lines) and its measured "golden operations" and "golden services" proposals |
| 2 | `measured-not-argued` | Benchmark like the AsmFoundation does: paired A/B runs, control runs, quiet-host checks, certified runs, and a claims ledger where every public number has evidence | KvAsm's `benchmarks/METHODOLOGY.md` and `docs/CLAIMS.md` |
| 3 | `nasm-x86-64` | Write correct Linux x86-64 NASM beyond the build: the System V ABI in depth, system calls, SIMD (SSE to AVX-512), CPUID dispatch, alignment, atomics and memory ordering, and debugging with gdb and perf | `asmsdk`'s `nasm-for-asmsdk.md` (linking subset), KvAsm's source and audit notes |
| 4 | `asm-verification` | Prove asm code correct: differential tests against a reference implementation, fuzzing with request matrices, page-boundary tests, mutation checks that the tests catch bugs, and h2spec-style conformance suites | KvAsm's test suites (fuzzer, end-to-end, .NET), its mutation check (`mutate.sh`), h2spec results |
| 5 | `kvasm` | Use and operate KvAsm: the gRPC API, the `KvAsm.Client` .NET package, streaming upload and download, Docker deployment, sizing, and reading its metrics and limits | KvAsm's `PROTOCOL.md`, `ARCHITECTURE.md`, `docs/OPERATIONS.md`, the client's README |
| 6 | `asm-release` | Release an AsmFoundation project end to end: version from tags, changelog, NuGet trusted publishing, GHCR images, GitHub releases, deprecating and renaming packages | the KvAsm 0.3.0 rebrand and release, AsmSdk's `release.yml` |
| 7 | `asm-http2-grpc` | Work inside the HTTP/2, HPACK and gRPC engine: framing, flow control, header-block caching, a two-phase epoll worker, h2spec conformance | KvAsm's `h2n.asm`, its HTTP/2 ADRs, its h2spec 146/146 result |
| 8 | `grpcasm` | Build services on GrpcAsm through its NASM, C, .NET and Python APIs | GrpcAsm's plan (`docs/ROADMAP.md`); waits until GrpcAsm's first release |
| 9 | `storageasm` | Use StorageAsm once it exists | waits for the product |
| 10 | `asmfoundation-contributing` | Follow the organization's conventions: documentation style, evidence rules, commit messages, catalog and changelog upkeep | the organization profile, CONTRIBUTING.md and SECURITY.md defaults |

**Sequencing:**

- **1, 2 and 3** are product-independent and help every project in the organization at
  once.
- **5 and 6** pay off with the next KvAsm and AsmSdk releases.
- **7 and 8** follow GrpcAsm's milestones.
