"""Exportar/importar, en un solo archivo cifrado, la configuración local que todo el equipo necesita igual
pero que no puede vivir en git: los modelos de IA registrados (con su clave de API) y la conexión a la base de
datos (Azure SQL, con su contraseña). Reutiliza el cifrado de storage_config (PBKDF2 + Fernet, misma forma de
sobre) — cada sección es opcional, así que se puede exportar solo modelos, solo base de datos, o ambos."""
import base64
import json
import os
from . import core, llm, storage_config

EXPORT_FORMAT = 'ltw-team-config/1'


def _db_section():
    cfg = storage_config.load()
    if 'server' not in cfg:
        return None
    password = core.secret_get(cfg.get('secret', storage_config.AZURE_SQL_SECRET_NAME))
    if not password:
        return None
    return {'server': cfg['server'], 'database': cfg['database'], 'user': cfg['user'],
           'port': cfg.get('port', 1433), 'password': password}


def _models_section():
    profiles = llm.list_profiles()
    if not profiles:
        return None
    out = []
    for profile in profiles:
        item = dict(profile)
        item['api_key'] = core.secret_get(llm.profile_secret_name(profile['id']))
        out.append(item)
    return out


def export_encrypted(passphrase, include_db=True, include_models=True):
    """Arma las secciones pedidas y las cifra con una clave derivada de `passphrase` (PBKDF2 + Fernet) —
    devuelve los bytes del archivo a descargar. Comparte la frase por un canal aparte del archivo (nunca en el
    mismo correo/chat): es lo único que hace falta para descifrarlo."""
    if not include_db and not include_models:
        raise ValueError('Elige al menos una sección para exportar (modelos de IA o base de datos)')
    payload = {}
    if include_db:
        db = _db_section()
        if db is None:
            raise ValueError('Todavía no hay una configuración de Azure SQL para exportar')
        payload['db'] = db
    if include_models:
        models = _models_section()
        if models is None:
            raise ValueError('Todavía no hay modelos de IA registrados para exportar')
        payload['models'] = models
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    token = Fernet(storage_config._derive_key(passphrase, salt)).encrypt(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    envelope = {'format': EXPORT_FORMAT, 'salt': base64.b64encode(salt).decode('ascii'), 'ciphertext': token.decode('ascii')}
    return json.dumps(envelope, indent=2, ensure_ascii=False).encode('utf-8')


def import_encrypted(data, passphrase):
    """Descifra un archivo de `export_encrypted` y aplica las secciones que traiga. La base de datos se guarda
    como `storage_config.set_azure_sql(..., activate=False)` (no activa Azure SQL solo). Cada modelo se guarda
    con `llm.save_profile`, preservando su id — reimportar el mismo archivo actualiza en vez de duplicar; un
    modelo cuyo nombre choque con uno de otro id en esta máquina se omite (se reporta, no rompe el resto).
    Nada queda activado solo por importar: activar sigue siendo un paso aparte en cada pantalla."""
    from cryptography.fernet import Fernet, InvalidToken
    try:
        envelope = json.loads(data)
    except ValueError:
        raise ValueError('El archivo no es una configuración válida (JSON inválido).')
    if not isinstance(envelope, dict) or envelope.get('format') != EXPORT_FORMAT:
        raise ValueError('El archivo no es una configuración de equipo de LTW reconocible.')
    try:
        salt = base64.b64decode(envelope['salt'])
        token = envelope['ciphertext'].encode('ascii')
    except (KeyError, ValueError):
        raise ValueError('El archivo está corrupto o incompleto.')
    try:
        plaintext = Fernet(storage_config._derive_key(passphrase, salt)).decrypt(token)
    except InvalidToken:
        raise ValueError('La frase no coincide con la que se usó para exportar este archivo.')
    payload = json.loads(plaintext)
    summary = {'db': False, 'models_imported': 0, 'models_skipped': []}
    if payload.get('db'):
        db = payload['db']
        storage_config.set_azure_sql(db['server'], db['database'], db['user'], db['password'],
                                     port=db.get('port', 1433), activate=False)
        summary['db'] = True
    for profile in payload.get('models', []):
        try:
            llm.save_profile(profile, api_key=profile.get('api_key'))
            summary['models_imported'] += 1
        except ValueError as exc:
            summary['models_skipped'].append({'name': profile.get('name', '?'), 'reason': str(exc)})
    return summary
