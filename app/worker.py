"""Worker entrypoint: starts WORKER_CONCURRENCY RQ worker processes on the "heatmap" queue.

Total parallel heavy jobs = (worker containers x WORKER_CONCURRENCY), additionally
capped cluster-wide by GLOBAL_MAX_JOBS through a Redis semaphore.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import shutil

from .config import get_settings
from .logging_setup import setup_logging


def _run_one() -> None:
    from redis import Redis
    from rq import Worker

    from .jobs import QUEUE_NAME

    s = get_settings()
    setup_logging(s.log_level)
    conn = Redis.from_url(s.redis_url)
    Worker([QUEUE_NAME], connection=conn).work(with_scheduler=False)


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    # Clear temp files left behind by a crashed previous run.
    shutil.rmtree(s.tmp_dir, ignore_errors=True)
    os.makedirs(s.tmp_dir, exist_ok=True)
    n = max(1, s.worker_concurrency)
    if n == 1:
        _run_one()
        return
    procs = [mp.Process(target=_run_one, name=f"worker-{i}") for i in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
