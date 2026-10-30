"""The product's own honest account of how battle-tested each part is - not "does it work" but "was it tried
against something real, more than once, with failures found and fixed". Shown on Inicio and mirrored in
README.md/the manual so nobody forms an expectation the product hasn't earned yet. One source, several places."""

DISCLAIMER = ('LTW se entrega tal cual, sin garantía (ver LICENSE, MIT). Pruébalo solo contra sistemas propios o '
             'autorizados, revisa siempre lo que una suite o un agente va a hacer antes de confiar en el resultado, '
             'y úsalo bajo tu propia responsabilidad.')

LEVELS = (
    {'key': 'estable', 'label': 'Estable', 'color': 'positive', 'icon': 'verified',
     'summary': 'Probado contra sistemas reales, con pruebas automáticas y fallos reales encontrados y corregidos.',
     'items': ['Motor de aserciones y ejecución de casos API (26 tipos)', 'Protocolo para agentes (ltw.spec / ltw.report / ltw.failure)',
               'Importar contratos OpenAPI (archivo, URL, Swagger UI/Redoc/FastAPI)', 'Exploración automática de contratos',
               'Importar / Exportar del workspace', 'Seguridad de secretos (almacén del sistema, redacción)']},
    {'key': 'beta', 'label': 'Beta', 'color': 'warning', 'icon': 'science',
     'summary': 'Funciona y tiene pruebas, pero con menos uso real sostenido o un límite conocido que conviene vigilar.',
     'items': ['Suites y flujos con enriquecimiento entre módulos', 'Observador de interfaces (el tap/proxy en vivo, más que aprender del historial)',
               'Resumen ejecutivo y reporte de estatus', 'Casos UI y el espacio de trabajo unificado (API y UI)',
               'Actualización automática de token por petición HTTP (proactiva por expiración y reactiva ante 401)']},
    {'key': 'experimental', 'label': 'Experimental', 'color': 'grey-7', 'icon': 'biotech',
     'summary': 'Usable, pero la calidad depende de algo fuera de LTW (el modelo que conectes) o de un uso que casi no se ha probado.',
     'items': ['Asistente con modelo de lenguaje (la calidad depende del modelo que conectes)',
               'Programaciones de larga duración sin supervisión (sesiones cortas probadas, no días seguidos)',
               'Actualización automática de token por comando del sistema (ejecución local sin supervisión)']},
)
