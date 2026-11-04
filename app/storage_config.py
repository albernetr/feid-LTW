"""Qué backend de almacenamiento está activo (SQLite local o Azure SQL) y los datos de conexión de Azure SQL,
persistidos en un archivo dentro de `core.ROOT` (la misma carpeta, fuera de git, donde ya vive la base SQLite y
el token de agente) — hace falta saber a qué base conectarse *antes* de poder leer cualquier fila de cualquier
base, así que esto no puede vivir dentro de una tabla.

La contraseña de Azure SQL nunca se guarda en este archivo: vive en el llavero del sistema
(`core.secret_set`/`secret_get`), bajo el nombre fijo `AZURE_SQL_SECRET_NAME` — mismo mecanismo que ya usa la
autenticación de un Ambiente o de una Integración."""
import base64
import json
import os
from . import core

AZURE_SQL_SECRET_NAME = 'azure_sql_password'
EXPORT_FORMAT = 'ltw-storage-config/1'
PBKDF2_ITERATIONS = 390_000


def _config_path():
    return core.ROOT / 'storage_config.json'


def load():
    """{'backend': 'sqlite'|'azure_sql', 'server':, 'database':, 'user':, 'port':, 'secret': AZURE_SQL_SECRET_NAME}
    — los campos de Azure SQL faltan si nunca se guardó una configuración (backend sigue siendo 'sqlite')."""
    path = _config_path()
    if not path.is_file():
        return {'backend': 'sqlite'}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {'backend': 'sqlite'}
    if not isinstance(data, dict) or data.get('backend') not in ('sqlite', 'azure_sql'):
        return {'backend': 'sqlite'}
    return data


def save(config):
    """`config`: {'backend':, 'server':, 'database':, 'user':, 'port':} — nunca una contraseña (eso va al
    llavero por separado, con `core.secret_set(AZURE_SQL_SECRET_NAME, password)` antes de llamar a esto)."""
    if config.get('backend') not in ('sqlite', 'azure_sql'):
        raise ValueError('Backend inválido')
    if 'password' in config:
        raise ValueError('La contraseña no se guarda en este archivo — usa core.secret_set primero')
    core.ROOT.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


def active_backend():
    """'azure_sql' o 'sqlite' — LTW_BACKEND (variable de entorno) gana siempre si está puesta, para no romper
    usos con contenedores/CI que ya la definen; si no, lo decide la configuración guardada."""
    env = os.environ.get('LTW_BACKEND', '').strip().lower()
    if env:
        return 'azure_sql' if env == 'azure_sql' else 'sqlite'
    return load().get('backend', 'sqlite')


def azure_sql_connection_config():
    """server/database/user/port + la contraseña del llavero, listos para azure_sql_backend._connect(). None si
    todavía no se guardó ninguna configuración de Azure SQL."""
    cfg = load()
    if 'server' not in cfg:
        return None
    password = core.secret_get(cfg.get('secret', AZURE_SQL_SECRET_NAME))
    if not password:
        return None
    return {'server': cfg['server'], 'database': cfg['database'], 'user': cfg['user'],
           'port': cfg.get('port', 1433), 'password': password}


def set_azure_sql(server, database, user, password, port=1433, activate=False):
    """Guarda los datos de conexión de Azure SQL (la contraseña va al llavero) y, si `activate`, lo marca como
    backend activo — sigue siendo 'dual': si `activate` es False, Azure SQL queda configurado y listo para
    activarse después sin volver a escribir nada, mientras SQLite sigue siendo el backend en uso."""
    core.secret_set(AZURE_SQL_SECRET_NAME, password)
    current = load()
    save({'backend': 'azure_sql' if activate else current.get('backend', 'sqlite'),
         'server': server, 'database': database, 'user': user, 'port': port, 'secret': AZURE_SQL_SECRET_NAME})


def set_active(backend):
    """Cambia solo cuál backend está activo, preservando los datos de conexión de Azure SQL que ya hubiera."""
    if backend not in ('sqlite', 'azure_sql'):
        raise ValueError('Backend inválido')
    current = load()
    if backend == 'azure_sql' and 'server' not in current:
        raise ValueError('Todavía no hay una configuración de Azure SQL guardada')
    current['backend'] = backend
    save(current)


# --------------------------------------------------------------------------- exportar/importar (cifrado)

def _derive_key(passphrase, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode('utf-8')))


def export_encrypted(passphrase):
    """Arma server/database/user/port + la contraseña (del llavero) y los cifra con una clave derivada de
    `passphrase` (PBKDF2 + Fernet) — devuelve los bytes del archivo a descargar. Compartí la frase por un canal
    aparte del archivo (nunca en el mismo correo/chat): es lo único que hace falta para descifrarlo."""
    from cryptography.fernet import Fernet
    cfg = load()
    if 'server' not in cfg:
        raise ValueError('Todavía no hay una configuración de Azure SQL para exportar')
    password = core.secret_get(cfg.get('secret', AZURE_SQL_SECRET_NAME))
    if not password:
        raise ValueError('Falta la contraseña guardada en el llavero')
    payload = {'server': cfg['server'], 'database': cfg['database'], 'user': cfg['user'],
              'port': cfg.get('port', 1433), 'password': password}
    salt = os.urandom(16)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    envelope = {'format': EXPORT_FORMAT, 'salt': base64.b64encode(salt).decode('ascii'), 'ciphertext': token.decode('ascii')}
    return json.dumps(envelope, indent=2, ensure_ascii=False).encode('utf-8')


def import_encrypted(data, passphrase):
    """Descifra un archivo de `export_encrypted` y guarda server/database/user/port + la contraseña (al
    llavero) — NO activa Azure SQL solo con importar: `backend` queda como estaba, activar sigue siendo un paso
    aparte y confirmado (ver set_active/set_azure_sql con activate=True)."""
    from cryptography.fernet import Fernet, InvalidToken
    try:
        envelope = json.loads(data)
    except ValueError:
        raise ValueError('El archivo no es una configuración válida (JSON inválido).')
    if not isinstance(envelope, dict) or envelope.get('format') != EXPORT_FORMAT:
        raise ValueError('El archivo no es una configuración de LTW reconocible.')
    try:
        salt = base64.b64decode(envelope['salt'])
        token = envelope['ciphertext'].encode('ascii')
    except (KeyError, ValueError):
        raise ValueError('El archivo está corrupto o incompleto.')
    try:
        plaintext = Fernet(_derive_key(passphrase, salt)).decrypt(token)
    except InvalidToken:
        raise ValueError('La frase no coincide con la que se usó para exportar este archivo.')
    payload = json.loads(plaintext)
    set_azure_sql(payload['server'], payload['database'], payload['user'], payload['password'],
                  port=payload.get('port', 1433), activate=False)
    return {'server': payload['server'], 'database': payload['database'], 'user': payload['user'], 'port': payload.get('port', 1433)}
