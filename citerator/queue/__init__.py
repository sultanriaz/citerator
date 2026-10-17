"""Distributed job queue.

Two backends behind one interface:

  - InlineQueue   runs jobs synchronously in a daemon thread. Default.
                  No dependencies, works out of the box, jobs die with
                  the process.
  - RQQueue       enqueues to Redis; a separate worker process (or pool
                  of them) executes jobs. Survives API restarts, scales
                  horizontally, requires redis + rq.

Both backends delegate to the same job functions in citerator/jobs/, so
the execution logic is identical. Swapping backends changes only the
transport.

Status is never stored in the queue. The SQLite tables in
documents/jobs.py and evaluation/store.py are the source of truth; the
queue carries work orders. A worker updates its row as it progresses.
If the queue is wiped, no client-visible state is lost.
"""

from citerator.queue.base import QueueBackend, get_queue, reset_queue

__all__ = ["QueueBackend", "get_queue", "reset_queue"]