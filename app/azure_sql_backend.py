"""Adaptador opcional de almacenamiento contra Azure SQL (SQL Server), como alternativa al SQLite local por
archivo que usa `core.py` por defecto — pensado para el escenario de «base de datos compartida» (ver capítulo 15
del manual) cuando varias personas quieren una base real en la nube en vez de un archivo en una carpeta de red.

Mismo esquema «fila = id + payload JSON» que ya usa core.py (`CREATE TABLE ... (id, payload)`), así que todo el
resto de la app (save/get/list_items/delete/transaction en core.py) sigue funcionando exactamente igual sin
cambiar una sola función de negocio — este módulo solo traduce esas cinco operaciones a T-SQL.

Se activa con `LTW_BACKEND=azure_sql` más estas variables de entorno (nunca credenciales en la base ni en el
código): `LTW_AZURE_SQL_SERVER` (p. ej. `test-ws.database.windows.net`), `LTW_AZURE_SQL_DATABASE`,
`LTW_AZURE_SQL_USER`, `LTW_AZURE_SQL_PASSWORD`, y opcionalmente `LTW_AZURE_SQL_PORT` (1433 por defecto).
Usa autenticación SQL (usuario/contraseña) — no Microsoft Entra ID. Requiere `python-tds` (driver TDS puro
Python, sin instalar el driver ODBC de Microsoft) y `pyOpenSSL` (Azure SQL exige conexión cifrada)."""
import os
import re
import threading

TABLE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
# Reentrante: list_items/get/save/delete/initialize toman el lock para TODA la operación (no solo para obtener
# la conexión cacheada) y _live_connection() también lo toma internamente — sin reentrancia esto se bloquearía
# a sí mismo. Hace falta cubrir la operación completa, no solo conseguir la conexión: dos hilos ejecutando en
# paralelo sobre el mismo socket TDS compartido (p. ej. «Probar conexión» corriendo en segundo plano mientras
# otra pestaña carga una página) dejan el socket en un estado inconsistente que se cuelga para siempre, y como
# casi toda página pasa por current_user() -> Azure SQL, un solo socket colgado congela la aplicación entera.
_lock = threading.RLock()
# core.list_items/get/save/delete llaman a core.initialize() en CADA operación (barato en SQLite: un CREATE
# TABLE IF NOT EXISTS local). Para Azure SQL, sin esto, cada una de esas llamadas repetía un «¿existe esta
# tabla?» por red para las ~17 tablas de ALL_TABLES — crear una sola cuenta (que hace dos operaciones) llegó a
# sumar ~35 idas y vueltas al servidor, encontrado probando en vivo: parecía un cuelgue pero solo eran muchos
# redondeos innecesarios. Una vez confirmado que las tablas existen para la conexión cacheada actual, no hace
# falta volver a preguntar — se reinicia solo si la conexión se cae y se vuelve a crear (close()/_connect()).
_initialized = False
_connection = None


class AzureSqlConfigError(ValueError):
    """Falta alguna variable de entorno necesaria para conectar (LTW_AZURE_SQL_*)."""


def enabled():
    from . import storage_config
    return storage_config.active_backend() == 'azure_sql'


def _config():
    """Variables de entorno LTW_AZURE_SQL_* si están puestas (gana siempre, para usos con contenedores/CI);
    si no, la configuración guardada desde Configuraciones → Base de datos (storage_config.py)."""
    server = os.environ.get('LTW_AZURE_SQL_SERVER', '').strip()
    database = os.environ.get('LTW_AZURE_SQL_DATABASE', '').strip()
    user = os.environ.get('LTW_AZURE_SQL_USER', '').strip()
    password = os.environ.get('LTW_AZURE_SQL_PASSWORD', '')
    if server or database or user or password:
        missing = [name for name, value in (('LTW_AZURE_SQL_SERVER', server), ('LTW_AZURE_SQL_DATABASE', database),
                                            ('LTW_AZURE_SQL_USER', user), ('LTW_AZURE_SQL_PASSWORD', password)) if not value]
        if missing:
            raise AzureSqlConfigError('Faltan variables de entorno para Azure SQL: ' + ', '.join(missing))
        port = int(os.environ.get('LTW_AZURE_SQL_PORT', '1433'))
        return {'server': server, 'database': database, 'user': user, 'password': password, 'port': port}
    from . import storage_config
    cfg = storage_config.azure_sql_connection_config()
    if cfg is None:
        raise AzureSqlConfigError('No hay una configuración de Azure SQL guardada ni variables de entorno LTW_AZURE_SQL_*.')
    return cfg


def _connect(config=None):
    import certifi
    import pytds
    cfg = config or _config()
    # Azure SQL exige la conexión cifrada; pytds solo la activa si se le pasa un archivo de certificados raíz
    # (cafile) — sin esto, el servidor la rechaza con "Client does not have encryption enabled but it is
    # required". certifi trae el mismo paquete de raíces confiables que ya usa httpx en el resto de la app.
    return pytds.connect(server=cfg['server'], port=cfg['port'], database=cfg['database'],
                         user=cfg['user'], password=cfg['password'], autocommit=True, login_timeout=15, timeout=30,
                         cafile=certifi.where())


def _live_connection():
    """One cached connection, reused across calls (evita renegociar TLS en cada operación); se reabre sola si
    se cayó. No pensado para alta concurrencia — igual que SQLite, para «pocas personas simultáneas»."""
    global _connection, _initialized
    import pytds
    with _lock:
        if _connection is not None:
            try:
                _connection.cursor().execute('SELECT 1')
                return _connection
            except Exception:
                try:
                    _connection.close()
                except Exception:
                    pass
                _connection = None
        _connection = _connect()
        _initialized = False   # conexión nueva: todavía no se confirmó que las tablas existan en ESTA sesión
        return _connection


def close():
    """Cierra la conexión en caché, si hay una abierta (para pruebas, o para forzar una reconexión limpia)."""
    global _connection, _initialized
    with _lock:
        _initialized = False
        if _connection is not None:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None


def test_connection(config=None):
    """Confirma que se puede conectar y autenticar (SELECT 1), sin tocar ninguna tabla. Usado por
    `python run.py --check-storage` (lee la config de las variables de entorno) y por «Probar conexión» en
    Configuraciones → Base de datos (puede pasar una config explícita, para validar credenciales antes de
    definir las variables de entorno y reiniciar)."""
    con = _connect(config)
    try:
        cur = con.cursor()
        cur.execute('SELECT 1')
        cur.fetchone()
    finally:
        con.close()


def describe_error(exc):
    """pytds suele envolver el error real (p. ej. del servidor) en un TimeoutError propio sin texto
    (utils.exponential_backoff hace `raise TimeoutError() from ex`) — esto arma un mensaje legible bajando por
    la cadena `__cause__` hasta encontrar uno, en vez de mostrar un TimeoutError vacío."""
    current = exc
    while current is not None:
        if str(current):
            return f'{type(current).__name__}: {current}'
        current = current.__cause__
    return type(exc).__name__


def _check_table(table):
    if not TABLE_NAME_RE.match(table):
        raise ValueError(f'Nombre de tabla inválido: {table!r}')
    return table


def initialize(all_tables):
    """core.initialize() llama a esto en CADA list_items/get/save/delete (barato en SQLite: un CREATE TABLE IF
    NOT EXISTS local). Acá cada tabla es un redondeo de red aparte, así que una vez confirmadas todas para la
    conexión cacheada actual, no se repite — ver _initialized."""
    global _initialized
    with _lock:
        if _initialized:
            return
        con = _live_connection()
        cur = con.cursor()
        for table in all_tables:
            _check_table(table)
            cur.execute(f"IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = '{table}') "
                        f"CREATE TABLE {table} (id NVARCHAR(400) NOT NULL PRIMARY KEY, payload NVARCHAR(MAX) NOT NULL, "
                        f"seq INT IDENTITY(1,1) NOT NULL)")
        _initialized = True


def list_items(table):
    _check_table(table)
    with _lock:
        con = _live_connection()
        cur = con.cursor()
        cur.execute(f'SELECT payload FROM {table} ORDER BY seq DESC')
        return [row[0] for row in cur.fetchall()]


def get(table, identifier):
    _check_table(table)
    with _lock:
        con = _live_connection()
        cur = con.cursor()
        cur.execute(f'SELECT payload FROM {table} WHERE id=%s', (identifier,))
        row = cur.fetchone()
        return row[0] if row else None


def save(table, identifier, payload_json):
    """Upsert: UPDATE primero (la mayoría de los guardados son ediciones), INSERT si no existía la fila."""
    _check_table(table)
    with _lock:
        con = _live_connection()
        cur = con.cursor()
        cur.execute(f'UPDATE {table} SET payload=%s WHERE id=%s', (payload_json, identifier))
        if cur.rowcount == 0:
            cur.execute(f'INSERT INTO {table} (id, payload) VALUES (%s, %s)', (identifier, payload_json))


def delete(table, identifier):
    _check_table(table)
    with _lock:
        con = _live_connection()
        cur = con.cursor()
        cur.execute(f'DELETE FROM {table} WHERE id=%s', (identifier,))


class TransactionCursor:
    """Lo que core.transaction() entrega cuando el backend es Azure SQL — misma superficie que un
    sqlite3.Connection (`.execute(sql, params).fetchone()/.fetchall()`), para que el puñado de funciones de
    core.py que arman SQL crudo dentro de una transacción (core.save, delete_project_cascade, import_workspace)
    no tengan que saber contra qué motor corren. Solo traduce el placeholder `?` de SQLite al `%s` de pytds —
    nunca dentro de los valores, solo en el texto del SQL — y da `.upsert(...)` para el único punto donde el
    dialecto SÍ cambia de verdad (T-SQL no tiene `INSERT OR REPLACE`)."""

    def __init__(self, con):
        self.con = con
        self.cur = con.cursor()

    def execute(self, sql, params=()):
        self.cur.execute(sql.replace('?', '%s'), params)
        return self.cur

    def upsert(self, table, identifier, payload_json):
        _check_table(table)
        self.cur.execute(f'UPDATE {table} SET payload=%s WHERE id=%s', (payload_json, identifier))
        if self.cur.rowcount == 0:
            self.cur.execute(f'INSERT INTO {table} (id, payload) VALUES (%s, %s)', (identifier, payload_json))


def connect_for_transaction():
    """Conexión propia (no la cacheada: no queremos que otra operación la comparta a medio commitear),
    sin autocommit mientras dura la transacción."""
    con = _connect()
    con.autocommit = False
    return con
