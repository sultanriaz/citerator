"""Per-query observability: structlog configuration, tracing, and forwarding.

The tracer is a Protocol with three implementations:

  NullTracer    -- production-safe no-op (default when tracing is off or keys
                   are missing)
  LangfuseTracer -- real backend, lazy-imports the langfuse SDK
  FakeTracer    -- in-memory recorder for tests

The log-forwarding processor in log_sink.py is inert for any log event that
isn't part of a /query trace; ingestion, eval, and settings log lines pass
through untouched.
"""
