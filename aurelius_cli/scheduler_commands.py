"""CLI for the in-process TaskScheduler — schedule cron/interval/delayed shell
commands directly from the terminal.

Usage:
  aurelius schedule cron "<cron_expr>" -- <command> [args...]
  aurelius schedule interval <seconds> -- <command> [args...]
  aurelius schedule once <delay_seconds> -- <command> [args...]

Examples:
  # Run backup.py every day at 02:00
  aurelius schedule cron "0 2 * * *" -- python backup.py

  # Heartbeat every 30 seconds
  aurelius schedule interval 30 -- curl -X POST https://hc.io/ping

  # Delay a notification by 5 minutes
  aurelius schedule once 300 -- osascript -e 'display notification "Done!"'

The scheduler runs in the foreground until interrupted (Ctrl+C). Jobs execute
concurrently in background threads. Press Ctrl+C to stop the scheduler and
wait for in-flight jobs to finish (best-effort).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from src.agent.task_scheduler import TaskScheduler, _make_runner

__all__ = ["build_schedule_parser", "handle_schedule", "main_schedule"]


def _parse_delay(delay: str | int | float) -> float:
    """Parse a delay spec like "30s", "5m", "1h", or a raw number (seconds)."""
    if isinstance(delay, (int, float)):
        return float(delay)
    s = str(delay).strip().lower()
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("d"):
        return float(s[:-1]) * 86400
    return float(s)


def build_schedule_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aurelius schedule",
        description=(
            "Run shell commands on a schedule using Aurelius' in-process TaskScheduler. "
            "Subcommands create new jobs or manage existing ones. Creation commands block until Ctrl+C."
        ),
        epilog=(
            "examples:\n"
            '  aurelius schedule cron "0 2 * * *" -- python backup.py\n'
            "  aurelius schedule interval 60 -- curl -X POST https://hc.io/ping\n"
            "  aurelius schedule once 300 -- say 'task complete'\n"
            "  aurelius schedule list\n"
            "  aurelius schedule cancel <job_id>\n"
            "  aurelius schedule pause <job_id>\n"
            "  aurelius schedule resume <job_id>\n"
            "  aurelius schedule clear --yes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subs = parser.add_subparsers(dest="schedule_cmd", required=True, help="scheduling mode")

    cron = subs.add_parser("cron", help="Schedule a cron-expression job")
    cron.add_argument(
        "cron_expr",
        help='Cron expression (minute hour day month day-of-week). Example: "0 2 * * *"',
    )
    cron.add_argument(
        "shell_cmd",
        nargs=argparse.REMAINDER,
        help="Shell command and arguments to run",
    )

    interval = subs.add_parser("interval", help="Schedule a repeating job every N seconds")
    interval.add_argument("seconds", type=float, help="Interval in seconds")
    interval.add_argument(
        "shell_cmd",
        nargs=argparse.REMAINDER,
        help="Shell command and arguments to run",
    )

    once = subs.add_parser("once", help="Schedule a one-shot job after a delay")
    once.add_argument("delay", help="Delay in seconds (or suffix form like 30s, 5m, 1h)")
    once.add_argument(
        "shell_cmd",
        nargs=argparse.REMAINDER,
        help="Shell command and arguments to run",
    )

    subs.add_parser("list", help="List all scheduled jobs")

    cancel = subs.add_parser("cancel", help="Cancel a job by ID")
    cancel.add_argument("job_id", help="Job identifier to cancel")

    pause = subs.add_parser("pause", help="Pause a job by ID")
    pause.add_argument("job_id", help="Job identifier to pause")

    resume = subs.add_parser("resume", help="Resume a paused job by ID")
    resume.add_argument("job_id", help="Job identifier to resume")

    clear = subs.add_parser("clear", help="Remove all jobs from the store")
    clear.add_argument(
        "--yes", action="store_true", default=False, help="Confirm removal without prompting"
    )
    return parser


def _format_schedule(job: dict[str, Any]) -> str:
    if job.get("cron_expr"):
        return f"cron {job['cron_expr']}"
    if job.get("interval_secs") is not None:
        secs = job["interval_secs"]
        return f"every {secs}s" if job.get("is_recurring") else f"once after {secs}s"
    return "unknown"


def handle_schedule(args: argparse.Namespace) -> int:
    """Dispatch scheduling mode and block until interrupted for creation,
    or perform management operations (list/cancel/pause/resume/clear)."""
    if args.schedule_cmd in ("cron", "interval", "once"):
        if not args.shell_cmd:
            print("error: no command specified", file=sys.stderr)
            return 2

        runner = _make_runner(args.shell_cmd)
        sched = TaskScheduler()

        if args.schedule_cmd == "cron":
            job_id = sched.schedule_cron(args.cron_expr, runner, shell_cmd=args.shell_cmd)
            print(f"Scheduled cron job {job_id}: {args.shell_cmd}")
        elif args.schedule_cmd == "interval":
            job_id = sched.schedule_interval(args.seconds, runner, shell_cmd=args.shell_cmd)
            print(f"Scheduled interval job {job_id} every {args.seconds}s: {args.shell_cmd}")
        else:
            secs = _parse_delay(args.delay)
            job_id = sched.schedule_delayed(secs, runner, shell_cmd=args.shell_cmd)
            print(f"Scheduled one-shot job {job_id} in {secs}s: {args.shell_cmd}")

        print("Press Ctrl+C to stop the scheduler.")
        try:
            sched.start()
        except KeyboardInterrupt:
            print("\nInterrupted — stopping scheduler…")
        finally:
            sched.shutdown(wait=True)
        return 0

    sched = TaskScheduler()  # loads persisted jobs

    if args.schedule_cmd == "list":
        jobs = sched.list_jobs()
        if not jobs:
            print("No jobs scheduled.")
            return 0

        header = f"{'ID':<8} {'Name':<20} {'Schedule':<22} {'Next Run':<19} {'Paused'}"
        print(header)
        print("-" * len(header))
        for job in jobs:
            schedule = _format_schedule(job)
            next_run = job.get("next_run", "")
            paused = "yes" if job.get("is_paused") else "no"
            print(
                f"{job['id']:<8} {job['name'][:20]:<20} {schedule:<22} {str(next_run)[:19]:<19} {paused}"
            )
        return 0

    if args.schedule_cmd == "cancel":
        job_id = args.job_id
        if sched.cancel(job_id):
            print(f"Cancelled job {job_id}")
            return 0
        print(f"error: job {job_id} not found", file=sys.stderr)
        return 1

    if args.schedule_cmd == "pause":
        job_id = args.job_id
        if sched.pause(job_id):
            print(f"Paused job {job_id}")
            return 0
        print(f"error: job {job_id} not found or already paused", file=sys.stderr)
        return 1

    if args.schedule_cmd == "resume":
        job_id = args.job_id
        if sched.resume(job_id):
            print(f"Resumed job {job_id}")
            return 0
        print(f"error: job {job_id} not found or not paused", file=sys.stderr)
        return 1

    if args.schedule_cmd == "clear":
        if args.yes:
            sched.clear()
            print("All jobs cleared.")
            return 0
        print("error: --yes confirmation required to clear all jobs", file=sys.stderr)
        return 2

    print(f"error: unknown subcommand {args.schedule_cmd}", file=sys.stderr)
    return 2


def main_schedule(argv: list[str] | None = None) -> int:
    parser = build_schedule_parser()
    args = parser.parse_args(argv)
    return handle_schedule(args)
