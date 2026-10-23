#!/usr/bin/env python3
"""In-microVM storage benchmark engine (pure Python standard library).

This file is uploaded into an AgentCore Runtime session and executed there via
InvokeAgentRuntimeCommand. It performs no installs and touches nothing outside
the target directory, so the runtime image and configuration stay unchanged.

It measures, for a single (filesystem, workload) case:
  - throughput  (MiB/s)
  - IOPS        (operations/second)
  - latency     (per-operation, with avg/p50/p95/p99/max in milliseconds)

Workloads:
  seqwrite   sequential write of `bs`-sized blocks to one growing file
  seqread    sequential read of `bs`-sized blocks from a pre-created file
  randwrite  random-offset write of `bs`-sized blocks within a fixed file
  randread   random-offset read of `bs`-sized blocks from a fixed file

Results are emitted as a single JSON object on stdout, delimited by markers so
the orchestrator can extract it from mixed shell output.

Usage:
  python3 bench_engine.py --dir DIR --workload W --bs BYTES \
      --duration SECONDS [--filesize BYTES] [--fsync] [--seed N]
"""

import argparse
import json
import os
import sys
import time

RESULT_BEGIN = "===BENCH_RESULT_BEGIN==="
RESULT_END = "===BENCH_RESULT_END==="

# Deterministic LCG so we get reproducible random offsets without importing
# anything heavyweight and without per-call overhead skewing the timings.
_LCG_A = 6364136223846793005
_LCG_C = 1442695040888963407
_LCG_M = (1 << 64) - 1


def _percentile(sorted_vals, pct):
    """Nearest-rank percentile from an already-sorted list."""
    if not sorted_vals:
        return 0.0
    k = int(round((pct / 100.0) * (len(sorted_vals) - 1)))
    k = max(0, min(k, len(sorted_vals) - 1))
    return sorted_vals[k]


def _summarize(latencies_s, total_bytes, elapsed_s, op_count):
    """Build the metrics dict from raw per-op latencies (seconds)."""
    lat_ms = sorted(l * 1000.0 for l in latencies_s)
    n = len(lat_ms)
    avg_ms = (sum(lat_ms) / n) if n else 0.0
    return {
        "ops": op_count,
        "bytes": total_bytes,
        "elapsed_s": round(elapsed_s, 4),
        "throughput_mibps": round((total_bytes / (1024 * 1024)) / elapsed_s, 3)
        if elapsed_s > 0
        else 0.0,
        "iops": round(op_count / elapsed_s, 2) if elapsed_s > 0 else 0.0,
        "latency_ms": {
            "avg": round(avg_ms, 4),
            "p50": round(_percentile(lat_ms, 50), 4),
            "p95": round(_percentile(lat_ms, 95), 4),
            "p99": round(_percentile(lat_ms, 99), 4),
            "max": round(lat_ms[-1], 4) if n else 0.0,
            "min": round(lat_ms[0], 4) if n else 0.0,
        },
    }


def _prepare_file(path, size, bs):
    """Create a file of exactly `size` bytes for read/random workloads."""
    buf = os.urandom(bs)
    written = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o644)
    try:
        while written < size:
            chunk = buf if (size - written) >= bs else buf[: size - written]
            written += os.write(fd, chunk)
        os.fsync(fd)
    finally:
        os.close(fd)


def run(dir_path, workload, bs, duration, filesize, fsync, seed):
    os.makedirs(dir_path, exist_ok=True)
    target = os.path.join(dir_path, f"bench_{workload}_{os.getpid()}.dat")
    buf = os.urandom(bs)
    latencies = []
    total_bytes = 0
    op_count = 0
    deadline = time.monotonic() + duration

    try:
        if workload == "seqwrite":
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(target, flags, 0o644)
            try:
                while time.monotonic() < deadline:
                    t0 = time.perf_counter()
                    os.write(fd, buf)
                    if fsync:
                        os.fsync(fd)
                    latencies.append(time.perf_counter() - t0)
                    total_bytes += bs
                    op_count += 1
                    # Roll over so we don't fill the volume on long seq writes.
                    if total_bytes % filesize == 0:
                        os.lseek(fd, 0, os.SEEK_SET)
            finally:
                os.close(fd)

        elif workload == "seqread":
            _prepare_file(target, filesize, bs)
            fd = os.open(target, os.O_RDONLY)
            try:
                while time.monotonic() < deadline:
                    t0 = time.perf_counter()
                    data = os.read(fd, bs)
                    latencies.append(time.perf_counter() - t0)
                    if not data:
                        os.lseek(fd, 0, os.SEEK_SET)
                        continue
                    total_bytes += len(data)
                    op_count += 1
            finally:
                os.close(fd)

        elif workload in ("randread", "randwrite"):
            _prepare_file(target, filesize, bs)
            nblocks = max(1, filesize // bs)
            state = seed & _LCG_M
            if workload == "randread":
                fd = os.open(target, os.O_RDONLY)
            else:
                fd = os.open(target, os.O_WRONLY)
            try:
                while time.monotonic() < deadline:
                    state = (_LCG_A * state + _LCG_C) & _LCG_M
                    offset = (state % nblocks) * bs
                    t0 = time.perf_counter()
                    os.lseek(fd, offset, os.SEEK_SET)
                    if workload == "randread":
                        data = os.read(fd, bs)
                        nbytes = len(data)
                    else:
                        nbytes = os.write(fd, buf)
                        if fsync:
                            os.fsync(fd)
                    latencies.append(time.perf_counter() - t0)
                    total_bytes += nbytes
                    op_count += 1
            finally:
                os.close(fd)
        else:
            raise ValueError(f"unknown workload: {workload}")

        elapsed = duration if op_count else 0.0
        # Use measured wall time for accuracy (loop may overrun the last op).
        if latencies:
            elapsed = sum(latencies)
            # Wall-clock elapsed is more honest for throughput than summed
            # latency (which excludes loop overhead); recompute from deadline.
            elapsed = duration if duration > 0 else sum(latencies)

        metrics = _summarize(latencies, total_bytes, elapsed, op_count)
        metrics.update(
            {
                "ok": True,
                "workload": workload,
                "dir": dir_path,
                "block_size": bs,
                "file_size": filesize,
                "fsync": bool(fsync),
                "requested_duration_s": duration,
            }
        )
        return metrics
    finally:
        try:
            os.unlink(target)
        except OSError:
            pass


def main(argv):
    p = argparse.ArgumentParser(description="In-VM storage benchmark engine")
    p.add_argument("--dir", required=True)
    p.add_argument(
        "--workload",
        required=True,
        choices=["seqwrite", "seqread", "randwrite", "randread"],
    )
    p.add_argument("--bs", type=int, default=1 << 20, help="block size in bytes")
    p.add_argument("--duration", type=int, default=300, help="seconds")
    p.add_argument(
        "--filesize",
        type=int,
        default=256 << 20,
        help="working file size in bytes (read/random)",
    )
    p.add_argument("--fsync", action="store_true", help="fsync after each write")
    p.add_argument("--seed", type=int, default=88172645463325252)
    args = p.parse_args(argv)

    try:
        result = run(
            args.dir,
            args.workload,
            args.bs,
            args.duration,
            args.filesize,
            args.fsync,
            args.seed,
        )
    except Exception as exc:  # surface failures as structured JSON
        result = {
            "ok": False,
            "workload": args.workload,
            "dir": args.dir,
            "error": f"{type(exc).__name__}: {exc}",
        }

    sys.stdout.write(RESULT_BEGIN + "\n")
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.write(RESULT_END + "\n")
    sys.stdout.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
