"""Run separately to keep local scheduled suites active: python scheduler.py"""
import sys
from app.automation import serve_scheduler, SchedulerLockError

if __name__ == '__main__':
    try:
        serve_scheduler()
    except SchedulerLockError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
