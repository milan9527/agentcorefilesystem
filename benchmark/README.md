# AgentCore Runtime Filesystem Benchmark

Measures **throughput**, **IOPS**, and **latency** for the three filesystems
mounted inside the AgentCore Runtime microVM:

| Key | Mount | Type |
|---|---|---|
| `session` | `/mnt/workspace` | Session Storage (per-session, isolated) |
| `efs` | `/mnt/datasets` | Amazon EFS (shared) |
| `s3files` | `/mnt/tools` | Amazon S3 Files (shared, S3-backed) |

## How it works — and what it does *not* touch

The benchmark drives the existing **`InvokeAgentRuntimeCommand`** data-plane API
(the same path the app uses in [`backend/app/services/agentcore.py`](../backend/app/services/agentcore.py)).
It does **not** modify the runtime in any way:

- No image rebuild, no `filesystemConfigurations` change, no redeploy.
- It uploads one self-contained, **stdlib-only** engine (`bench_engine.py`) into
  the session's `/tmp` and runs it with the `python3` already in the container.
- Nothing is installed. All artifacts (engine + test files under
  `<mount>/.benchmark`) are removed on teardown.

```
run_benchmark.py (host)  ──InvokeAgentRuntimeCommand──▶  microVM
        │                                                   │
        │  base64 upload bench_engine.py ─▶ /tmp            │
        │  python3 /tmp/...bench_engine.py --workload ...   │
        ◀── JSON metrics between markers ──────────────────┘
```

## Test matrix

Default: **each `(filesystem × workload)` pair is its own 5-minute case.**

- Workloads: `seqwrite`, `seqread`, `randwrite`, `randread`
- 3 filesystems × 4 workloads × 5 min ≈ **60 min** total.

| Workload | Reports |
|---|---|
| `seqwrite` | sequential write throughput (MiB/s) + latency |
| `seqread` | sequential read throughput (MiB/s) + latency |
| `randwrite` | random write IOPS + latency percentiles |
| `randread` | random read IOPS + latency percentiles |

Sequential workloads use a 1 MiB block by default (throughput-oriented);
override `--bs 4096` for the random workloads if you want classic 4K IOPS.

## Usage

```bash
cd benchmark
pip install boto3          # only dependency, host-side

# Full run: 5 minutes per case (~60 min). Uses the deployed runtime by default.
python3 run_benchmark.py --duration 300 --out results.json

# Classic 4K random IOPS profile
python3 run_benchmark.py --duration 300 --bs 4096 --filesize $((512*1024*1024))

# Durable-write latency (fsync after every write)
python3 run_benchmark.py --duration 300 --fsync

# Quick smoke test before committing to the hour
python3 run_benchmark.py --duration 10 --filesystems session --bs 65536

# One filesystem / subset of workloads
python3 run_benchmark.py --filesystems efs s3files --workloads randread randwrite
```

### Key flags

| Flag | Default | Meaning |
|---|---|---|
| `--runtime-arn` | deployed demo ARN (or `$AGENTCORE_RUNTIME_ARN`) | target runtime |
| `--region` | `us-east-1` (or `$AWS_REGION`) | AWS region |
| `--duration` | `300` | seconds per case (5 min) |
| `--bs` | `1048576` | block size in bytes |
| `--filesize` | `268435456` | working-file size for read/random |
| `--fsync` | off | fsync after each write (durability latency) |
| `--filesystems` | all three | subset to test |
| `--workloads` | all four | subset to test |
| `--session-id` | generated | reuse a session id (≥33 chars) |
| `--out` | `results.json` | JSON output path |
| `--no-cleanup` | off | leave bench files in the session |

## Output

A live table prints per case, and full results are written to `--out`:

```json
{
  "runtime_arn": "...",
  "session_id": "bench-...",
  "config": { "duration_s": 300, "block_size": 1048576, ... },
  "results": [
    {
      "filesystem": "efs",
      "mount_path": "/mnt/datasets",
      "workload": "randread",
      "ok": true,
      "metrics": {
        "throughput_mibps": 118.4,
        "iops": 30310.2,
        "latency_ms": { "avg": 0.03, "p50": 0.02, "p95": 0.05, "p99": 0.09, "max": 4.1 }
      }
    }
  ]
}
```

## Notes

- **Caching:** the OS page cache can inflate read numbers. For cache-sensitive
  comparisons keep `--filesize` well above the microVM's RAM, or interpret read
  results as warm-cache figures. `--fsync` makes write latency reflect durable
  commit time rather than page-cache acknowledgement.
- **S3 Files (`/mnt/tools`):** backed by S3 with async sync; small-IO latency
  and random-write behaviour differ markedly from EFS/Session Storage — that
  contrast is the point of running all three.
- Each case is independent; a failure in one is recorded and the run continues.
