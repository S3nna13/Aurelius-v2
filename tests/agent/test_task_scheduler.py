"""Tests for the in-process task scheduler."""

from __future__ import annotations

import threading
import time
from datetime import datetime

from src.agent.task_scheduler import (
    Job,
    TaskScheduler,
    _next_cron_time,
    _parse_cron_field,
    _parse_delay,
)


def make_scheduler(tmp_path) -> TaskScheduler:
    return TaskScheduler(store_path=tmp_path / "jobs.json")


class TestParsers:
    def test_parse_cron_field_variants(self):
        assert len(_parse_cron_field("*", 0, 59)) == 60
        assert _parse_cron_field("5", 0, 59) == [5]
        assert _parse_cron_field("1,3,5", 0, 59) == [1, 3, 5]
        assert _parse_cron_field("1-5", 0, 59) == [1, 2, 3, 4, 5]
        assert _parse_cron_field("*/5", 0, 59) == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
        assert _parse_cron_field("1-10/2", 0, 59) == [1, 3, 5, 7, 9]
        mixed = _parse_cron_field("0,30-40/5,45", 0, 59)
        assert {0, 30, 35, 40, 45}.issubset(set(mixed))

    def test_parse_delay_variants(self):
        assert _parse_delay(10) == 10.0
        assert _parse_delay(5.5) == 5.5
        assert _parse_delay("30s") == 30.0
        assert _parse_delay("5m") == 300.0
        assert _parse_delay("2h") == 7200.0
        assert _parse_delay("1d") == 86400.0


class TestNextCronTime:
    def test_every_minute(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        next_t = _next_cron_time("* * * * *", now)
        assert next_t.minute == 1
        assert next_t.hour == 12
        assert next_t.day == 1

    def test_specific_time(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        next_t = _next_cron_time("15 14 * * *", now)
        assert next_t.minute == 15
        assert next_t.hour == 14
        assert next_t.day == 1

    def test_next_day_rollover(self):
        now = datetime(2025, 1, 1, 23, 59, 0)
        next_t = _next_cron_time("0 * * * *", now)
        assert next_t.day == 2
        assert next_t.hour == 0
        assert next_t.minute == 0


class TestJob:
    def test_job_defaults_and_cancel(self):
        job = Job()
        assert job.is_recurring is False
        assert job.is_paused is False
        assert job.is_cancelled is False
        assert job.run_count == 0
        job._cancel()
        assert job.is_cancelled is True


class TestSchedulerBasics:
    def test_new_scheduler_has_no_jobs(self, tmp_path):
        sched = make_scheduler(tmp_path)
        assert sched.list_jobs() == []

    def test_schedule_interval_returns_job_id(self, tmp_path):
        sched = make_scheduler(tmp_path)
        job_id = sched.schedule_interval(1.0, lambda: None, name="every1")
        assert isinstance(job_id, str)
        jobs = sched.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "every1"
        assert jobs[0]["is_recurring"] is True


class TestSchedulerControl:
    def test_cancel_pause_resume(self, tmp_path):
        sched = make_scheduler(tmp_path)
        job_id = sched.schedule_interval(1.0, lambda: None)

        assert sched.pause(job_id) is True
        assert sched.pause(job_id) is False
        assert sched.resume(job_id) is True
        assert sched.resume(job_id) is False
        assert sched.cancel(job_id) is True
        assert sched.cancel(job_id) is False

    def test_pause_resume_unknown_job(self, tmp_path):
        sched = make_scheduler(tmp_path)
        assert sched.pause("missing") is False
        assert sched.resume("missing") is False
        assert sched.cancel("missing") is False


class TestSchedulerExecution:
    def test_delayed_task_runs_once(self, tmp_path):
        results: list[int] = []
        sched = make_scheduler(tmp_path)
        sched.schedule_delayed(0.05, lambda: results.append(1))
        sched.start()
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline and not results:
            time.sleep(0.01)
        sched.shutdown(wait=True)
        assert results == [1]

    def test_interval_task_runs_multiple_times(self, tmp_path):
        results: list[int] = []
        sched = make_scheduler(tmp_path)
        sched.schedule_interval(0.03, lambda: results.append(1))
        sched.start()
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline and len(results) < 3:
            time.sleep(0.01)
        sched.shutdown(wait=True)
        assert len(results) >= 3

    def test_paused_task_does_not_run(self, tmp_path):
        results: list[int] = []
        sched = make_scheduler(tmp_path)
        job_id = sched.schedule_interval(0.02, lambda: results.append(1))
        assert sched.pause(job_id) is True
        sched.start()
        time.sleep(0.12)
        sched.shutdown(wait=True)
        assert results == []

    def test_resumed_task_runs_after_pause(self, tmp_path):
        results: list[int] = []
        sched = make_scheduler(tmp_path)
        job_id = sched.schedule_interval(0.03, lambda: results.append(1))
        assert sched.pause(job_id) is True
        sched.start()
        time.sleep(0.05)
        assert sched.resume(job_id) is True
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline and len(results) < 2:
            time.sleep(0.01)
        sched.shutdown(wait=True)
        assert len(results) >= 2

    def test_cancelled_task_stops_running(self, tmp_path):
        results: list[int] = []
        sched = make_scheduler(tmp_path)
        job_id = sched.schedule_interval(0.02, lambda: results.append(1))
        sched.start()
        time.sleep(0.05)
        assert results
        count_after_cancel = len(results)
        assert sched.cancel(job_id) is True
        time.sleep(0.08)
        sched.shutdown(wait=True)
        assert len(results) == count_after_cancel

    def test_one_shot_removed_after_run(self, tmp_path):
        sched = make_scheduler(tmp_path)
        sched.schedule_delayed(0.02, lambda: None)
        sched.start()
        time.sleep(0.08)
        sched.shutdown(wait=True)
        assert sched.list_jobs() == []

    def test_job_args_and_kwargs(self, tmp_path):
        results: list[int] = []

        def capture(a, b, c=None):
            results.append(a + b + (c or 0))

        sched = make_scheduler(tmp_path)
        sched.schedule_interval(0.02, capture, 1, 2, c=3)
        sched.start()
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline and 6 not in results:
            time.sleep(0.01)
        sched.shutdown(wait=True)
        assert 6 in results

    def test_scheduler_context_manager(self, tmp_path):
        with make_scheduler(tmp_path) as sched:
            sched.schedule_interval(10.0, lambda: None)
            assert sched._runner_thread is not None
            assert sched._runner_thread.is_alive()
        assert sched._stop_event.is_set()


class TestThreadSafetySmoke:
    def test_concurrent_add_cancel(self, tmp_path):
        sched = make_scheduler(tmp_path)
        sched.start()
        ids: list[str] = []

        def add_jobs():
            for _ in range(20):
                ids.append(sched.schedule_interval(1.0, lambda: None))
                time.sleep(0.001)

        def cancel_jobs():
            time.sleep(0.01)
            for jid in ids[:10]:
                sched.cancel(jid)
                time.sleep(0.001)

        t1 = threading.Thread(target=add_jobs)
        t2 = threading.Thread(target=cancel_jobs)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        sched.shutdown(wait=True)
        assert True
