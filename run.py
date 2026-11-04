"""Entry point.  python run.py            -> web UI on http://127.0.0.1:8080
                  python run.py --scheduler -> recurring-suite scheduler (one per workspace)
                  python run.py --run spec.json   -> agent protocol (see AGENTS.md; --validate / --schema too)
                  python run.py --status-report reporte.html [--project N] [--days 14]   -> executive status report
                  python run.py --explore --project N --module N [--environment N] [--save]   -> auto-discover & run read-only cases
                  python run.py --reset-workspace --yes [--keep-evidence]   -> wipe the database (irreversible, "start from zero")
                  python run.py --check-storage   -> which backend is active (SQLite/Azure SQL) and whether it connects"""
import sys

AGENT_FLAGS = ('--run', '--validate', '--schema')
REPORT_FLAG = '--status-report'
EXPLORE_FLAG = '--explore'
RESET_FLAG = '--reset-workspace'
CHECK_STORAGE_FLAG = '--check-storage'

if __name__ in {'__main__', '__mp_main__'}:
    if CHECK_STORAGE_FLAG in sys.argv:                           # which backend is active, and whether it connects: no web server
        from app import azure_sql_backend
        if not azure_sql_backend.enabled():
            print('Backend: SQLite (local). LTW_BACKEND no está en "azure_sql".')
            sys.exit(0)
        print('Backend: Azure SQL. Probando conexión…')
        try:
            azure_sql_backend.test_connection()
        except Exception as exc:
            print(f'No se pudo conectar: {azure_sql_backend.describe_error(exc)}', file=sys.stderr)
            sys.exit(1)
        print('Conexión correcta.')
        sys.exit(0)
    if REPORT_FLAG in sys.argv:                                 # executive status report from the shared workspace: file out, exit code 0 healthy / 1 attention
        from app.reporting import cli as report_cli
        sys.exit(report_cli(sys.argv[1:]))
    if EXPLORE_FLAG in sys.argv:                                 # auto-discover and run read-only cases from an imported contract
        from app.explorer import cli as explore_cli
        sys.exit(explore_cli(sys.argv[1:]))
    if RESET_FLAG in sys.argv:                                   # wipe the database and evidence: irreversible, no web server
        from app import core
        if '--yes' not in sys.argv:
            print('Esto borra TODO el workspace (proyectos, casos, historial…) y no se puede deshacer.\n'
                  'Vuelve a ejecutar con --reset-workspace --yes para confirmar (agrega --keep-evidence para '
                  'conservar capturas y trazas).', file=sys.stderr)
            sys.exit(2)
        core.reset_workspace(remove_evidence='--keep-evidence' not in sys.argv)
        print('Workspace reiniciado.')
        sys.exit(0)
    if any(flag in sys.argv for flag in AGENT_FLAGS):          # agent protocol: no web server, file in / file out, exit code
        from app.agent import cli
        sys.exit(cli(sys.argv[1:]))
    from app import core
    core.migrate_legacy_data()  # one-time copy of a pre-1.0 workspace into <package>/data
    if '--scheduler' in sys.argv:
        from app.automation import serve_scheduler, SchedulerLockError
        try:
            serve_scheduler()
        except SchedulerLockError as exc:
            print(exc, file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            pass
    else:
        from app.main import start
        start()
