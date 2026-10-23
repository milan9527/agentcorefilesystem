#!/usr/bin/env python3
"""Benchmark the three AgentCore Runtime filesystems via InvokeAgentRuntimeCommand.

This orchestrator runs on the host. It does NOT modify the AgentCore Runtime:
it only uploads a self-contained, stdlib-only engine (bench_engine.py) into a
runtime session's /tmp and executes it with the python3 already present in the
container. Nothing is installed and nothing outside the bench directories is
touched.

Filesystems under test (mount paths from the runtime configuration):
  session   /mnt/workspace   Session Storage (per-session, isolated)
  efs       /mnt/datasets    Amazon EFS (shared)
  s3files   /mnt/tools       Amazon S3 Files (shared, S3-backed)

Test matrix (default): each (filesystem x workload) is its own 5-minute case.
  workloads: seqwrite, seqread, randwrite, randread
  3 filesystems x 4 workloads x 5 min = ~60 min total.

Metrics per case: throughput (MiB/s), IOPS, latency percentiles (ms).

Example:
  python3 run_benchmark.py \
      --runtime-arn arn:aws:bedrock-agentcore:us-east-1:632930644527:runtime/agentcore_fs_demo-vQv834FKFx \
      --region us-east-1 --duration 300 --out results.json

  # quick smoke test (10s per case, only session storage):
  python3 run_benchmark.py --duration 10 --filesystems session --bs 65536
"""

import argparse
import base64
import json
import os
import sys
import time
import uuid

import boto3
from botocore.config import Config

ENGINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_engine.py")
REMOTE_ENGINE = "/tmp/agentcore_bench_engine.py"
RESULT_BEGIN = "===BENCH_RESULT_BEGIN==="
RESULT_END = "===BENCH_RESULT_END==="

# Mount paths must match the runtime's filesystemConfigurations.
FILESYSTEMS = {
    "session": {"label": "Session Storage", "path": "/mnt/workspace"},
    "efs": {"label": "Amazon EFS", "path": "/mnt/datasets"},
    "s3files": {"label": "Amazon S3 Files", "path": "/mnt/tools"},
}

WORKLOADS = ["seqwrite", "seqread", "randwrite", "randread"]

DEFAULT_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:632930644527:runtime/agentcore_fs_demo-vQv834FKFx"
)


class RuntimeShell:
    """Thin wrapper over InvokeAgentRuntimeCommand for one runtime session.

    Mirrors the production client in backend/app/services/agentcore.py so the
    benchmark exercises the exact same data-plane path the app uses.
    """

    def __init__(self, runtime_arn, region, session_id, qualifier="DEFAULT", read_timeout=3600):
        # The engine emits results only when a case finishes, so the response
        # stream stays idle for the whole duration. read_timeout must exceed the
        # longest case or botocore aborts mid-run with ReadTimeoutError.
        cfg = Config(
            read_timeout=read_timeout,
            connect_timeout=30,
            retries={"max_attempts": 0, "mode": "standard"},
        )
        self._client = boto3.client("bedrock-agentcore", region_name=region, config=cfg)
        self._arn = runtime_arn
        self._session_id = session_id
        self._qualifier = qualifier

    def exec(self, command, timeout):
        resp = self._client.invoke_agent_runtime_command(
            agentRuntimeArn=self._arn,
            runtimeSessionId=self._session_id,
            qualifier=self._qualifier,
            contentType="application/json",
            accept="application/vnd.amazon.eventstream",
            body={
                "command": f'/bin/bash -c "{command}"',
                "timeout": timeout,
            },
        )
        out, err = [], []
        exit_code, status = None, None
        for event in resp.get("stream", []):
            chunk = event.get("chunk")
            if not chunk:
                continue
            delta = chunk.get("contentDelta")
            if delta:
                if delta.get("stdout"):
                    out.append(delta["stdout"])
                if delta.get("stderr"):
                    err.append(delta["stderr"])
            stop = chunk.get("contentStop")
            if stop:
                exit_code = stop.get("exitCode")
                status = stop.get("status")
        return {
            "stdout": "".join(out),
            "stderr": "".join(err),
            "exit_code": exit_code,
            "status": status,
        }


def upload_engine(shell):
    """Copy bench_engine.py into the session via a base64 heredoc.

    base64 avoids any quoting/escaping hazards inside the bash -c wrapper.
    """
    with open(ENGINE_PATH, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    # Write base64 to a temp file, then decode it to the engine path.
    cmd = (
        f"printf '%s' '{b64}' | base64 -d > {REMOTE_ENGINE} && "
        f"python3 -c \\\"import py_compile,sys; py_compile.compile('{REMOTE_ENGINE}', doraise=True)\\\" && "
        f"echo ENGINE_OK"
    )
    res = shell.exec(cmd, timeout=60)
    if "ENGINE_OK" not in res["stdout"]:
        raise RuntimeError(
            f"engine upload failed: exit={res['exit_code']} "
            f"stderr={res['stderr'][:500]} stdout={res['stdout'][:500]}"
        )


def parse_result(stdout):
    """Extract the JSON metrics object emitted between the markers."""
    start = stdout.find(RESULT_BEGIN)
    end = stdout.find(RESULT_END)
    if start == -1 or end == -1:
        return None
    blob = stdout[start + len(RESULT_BEGIN) : end].strip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def run_case(shell, fs_key, workload, args):
    """Run one (filesystem, workload) case for `args.duration` seconds."""
    fs = FILESYSTEMS[fs_key]
    bench_dir = f"{fs['path']}/.benchmark"
    cmd = (
        f"python3 {REMOTE_ENGINE} "
        f"--dir {bench_dir} "
        f"--workload {workload} "
        f"--bs {args.bs} "
        f"--duration {args.duration} "
        f"--filesize {args.filesize} "
        f"--seed {args.seed}"
    )
    if args.fsync:
        cmd += " --fsync"

    # Allow generous margin over the workload duration for prep + teardown.
    api_timeout = min(args.duration + 120, 3600)

    t0 = time.time()
    res = shell.exec(cmd, timeout=api_timeout)
    wall = time.time() - t0

    metrics = parse_result(res["stdout"])
    record = {
        "filesystem": fs_key,
        "filesystem_label": fs["label"],
        "mount_path": fs["path"],
        "workload": workload,
        "wall_clock_s": round(wall, 2),
        "exit_code": res["exit_code"],
        "status": res["status"],
    }
    if metrics is None:
        record["ok"] = False
        record["error"] = (
            res["stderr"][:1000] or res["stdout"][-1000:] or "no result emitted"
        )
    else:
        record["ok"] = metrics.get("ok", False)
        record["metrics"] = metrics
    return record


def cleanup(shell):
    """Remove benchmark artifacts and the uploaded engine from the session."""
    paths = " ".join(f"{fs['path']}/.benchmark" for fs in FILESYSTEMS.values())
    shell.exec(f"rm -rf {paths} {REMOTE_ENGINE}", timeout=60)


def fmt_row(rec):
    if not rec.get("ok"):
        return f"  {rec['workload']:<10} FAILED: {rec.get('error', '')[:80]}"
    m = rec["metrics"]
    lat = m["latency_ms"]
    return (
        f"  {rec['workload']:<10} "
        f"{m['throughput_mibps']:>10.2f} MiB/s  "
        f"{m['iops']:>10.1f} IOPS  "
        f"p50={lat['p50']:.3f}ms p95={lat['p95']:.3f}ms p99={lat['p99']:.3f}ms"
    )


def main(argv):
    p = argparse.ArgumentParser(
        description="Benchmark AgentCore Runtime filesystems via InvokeAgentRuntimeCommand",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--runtime-arn", default=os.environ.get("AGENTCORE_RUNTIME_ARN", DEFAULT_RUNTIME_ARN))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--session-id", default=None, help="reuse a session id (>=33 chars); default: generated")
    p.add_argument("--duration", type=int, default=300, help="seconds per case (5 min default)")
    p.add_argument("--bs", type=int, default=1 << 20, help="block size in bytes")
    p.add_argument("--filesize", type=int, default=256 << 20, help="working file size (read/random)")
    p.add_argument("--fsync", action="store_true", help="fsync after each write op")
    p.add_argument("--seed", type=int, default=88172645463325252)
    p.add_argument("--filesystems", nargs="+", choices=list(FILESYSTEMS), default=list(FILESYSTEMS))
    p.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=WORKLOADS)
    p.add_argument("--out", default="results.json", help="path to write JSON results")
    p.add_argument("--no-cleanup", action="store_true", help="leave bench files in the session")
    args = p.parse_args(argv)

    session_id = args.session_id or f"bench-{uuid.uuid4().hex}"
    if len(session_id) < 33:
        session_id += "0" * (33 - len(session_id))

    # read_timeout must comfortably exceed one case (engine emits only at end).
    shell = RuntimeShell(
        args.runtime_arn,
        args.region,
        session_id,
        read_timeout=min(args.duration + 300, 3600),
    )

    total_cases = len(args.filesystems) * len(args.workloads)
    est_min = total_cases * args.duration / 60.0
    print("=" * 78)
    print("AgentCore Runtime Filesystem Benchmark")
    print("=" * 78)
    print(f"Runtime    : {args.runtime_arn}")
    print(f"Region     : {args.region}")
    print(f"Session    : {session_id}")
    print(f"Filesystems: {', '.join(args.filesystems)}")
    print(f"Workloads  : {', '.join(args.workloads)}")
    print(f"Per case   : {args.duration}s | block={args.bs}B file={args.filesize}B fsync={args.fsync}")
    print(f"Cases      : {total_cases}  (~{est_min:.0f} min total)")
    print("=" * 78)

    print("\n[setup] provisioning session + uploading engine ...")
    # Touch the session so the microVM is up, then upload the engine.
    shell.exec("echo ready", timeout=60)
    upload_engine(shell)
    print("[setup] engine ready at", REMOTE_ENGINE)

    results = []
    case_no = 0
    started = time.time()
    try:
        for fs_key in args.filesystems:
            print(f"\n### {FILESYSTEMS[fs_key]['label']} ({FILESYSTEMS[fs_key]['path']})")
            for workload in args.workloads:
                case_no += 1
                print(f"[{case_no}/{total_cases}] running {fs_key}/{workload} for {args.duration}s ...", flush=True)
                rec = run_case(shell, fs_key, workload, args)
                results.append(rec)
                print(fmt_row(rec), flush=True)
    finally:
        if not args.no_cleanup:
            print("\n[teardown] cleaning up session artifacts ...")
            cleanup(shell)

    report = {
        "runtime_arn": args.runtime_arn,
        "region": args.region,
        "session_id": session_id,
        "config": {
            "duration_s": args.duration,
            "block_size": args.bs,
            "file_size": args.filesize,
            "fsync": args.fsync,
            "seed": args.seed,
        },
        "total_wall_clock_s": round(time.time() - started, 1),
        "results": results,
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"{'filesystem':<14}{'workload':<11}{'MiB/s':>11}{'IOPS':>12}{'p50 ms':>10}{'p99 ms':>10}")
    print("-" * 78)
    for rec in results:
        if rec.get("ok"):
            m = rec["metrics"]
            print(
                f"{rec['filesystem']:<14}{rec['workload']:<11}"
                f"{m['throughput_mibps']:>11.2f}{m['iops']:>12.1f}"
                f"{m['latency_ms']['p50']:>10.3f}{m['latency_ms']['p99']:>10.3f}"
            )
        else:
            print(f"{rec['filesystem']:<14}{rec['workload']:<11}{'FAILED':>11}")
    print("-" * 78)
    print(f"Results written to {args.out}")
    failures = [r for r in results if not r.get("ok")]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
