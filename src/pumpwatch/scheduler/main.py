"""Smoke-test entry point for the scheduler service.

Beat is launched via the celery CLI (see ``docker-compose.yml``); this
module exists so ``python -m pumpwatch.scheduler.main`` gives a clear
error rather than appearing to do nothing.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "The scheduler runs under Celery Beat. Launch with:\n"
        "  celery -A pumpwatch.celery_app beat --loglevel=INFO"
    )


if __name__ == "__main__":
    main()
