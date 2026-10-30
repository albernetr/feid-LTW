"""Observer: what really enters and leaves each module."""
import json
from nicegui import ui
from .. import core, observer as obs
from .common import frame, guard, confirm, empty_state, require_project, fmt_time

STATE_COLOR = {'sin línea base': 'grey', 'sin cambios': 'positive'}


def state_badge(doc):
    state = obs.interface_state(doc)
    return ui.badge(state, color=STATE_COLOR.get(state, 'negative'))


@ui.page('/observer')
def observer_page():
    with frame('Observador de interfaces', '/observer'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Qué entra y qué sale de cada módulo, aprendido del tráfico real (solo JSON). Pon un tap entre quien llama y el módulo, '
                 'o aprende de las ejecuciones ya registradas. Fija una línea base y el observador avisa de cambios sin anuncio.').classes('text-gray-600')

        summaries = obs.module_summaries(pid)
        interfaces = obs.list_interfaces(pid)
        if summaries:
            with ui.row().classes('gap-3 flex-wrap'):
                for row in summaries:
                    card = ui.card().classes('w-72' + (' cursor-pointer' if interfaces else ''))
                    if interfaces:
                        card.on('click', lambda _, m=row['module']: filter_module.set_value(m))
                    with card:
                        ui.label(row['module']).classes('font-semibold')
                        meta = ' · '.join(x for x in (row.get('company'), row.get('owner')) if x)
                        if meta:
                            ui.label(meta).classes('text-xs text-gray-500')
                        ui.label(f'{row["interfaces"]} interfaces · {row["calls"]} llamadas').classes('text-sm')
                        if row['drift']:
                            ui.badge(f'{row["drift"]} cambio(s) sin aprobar', color='negative')
                        elif row['unbaselined']:
                            ui.badge(f'{row["unbaselined"]} sin línea base', color='grey')
                        elif row['interfaces']:
                            ui.badge('sin cambios', color='positive')

        # ------------------------------------------------------------ taps
        taps = core.list_project_items('taps', pid)
        with ui.expansion('Nuevo tap (proxy de observación)', icon='compare_arrows', value=not taps).classes('w-full border rounded'):
            ui.label('Un tap escucha en tu equipo (127.0.0.1) y reenvía todo al módulo destino sin modificarlo, registrando el JSON. '
                     'Apunta al tap el módulo que llama, en lugar de apuntar directo al destino.').classes('text-sm text-gray-600')
            with ui.row().classes('w-full gap-3 items-start'):
                name = ui.input('Módulo (nombre)').props('outlined dense').classes('w-52')
                company = ui.input('Empresa / equipo (opcional)').props('outlined dense').classes('w-52')
                owner = ui.input('Responsable (opcional)').props('outlined dense').classes('w-52')
            with ui.row().classes('w-full gap-3 items-start no-wrap'):
                port = ui.number('Puerto local', value=9101 + len(core.list_items('taps')), min=1024, max=65535, precision=0).props('outlined dense').classes('w-36')
                scheme = ui.select(['https', 'http'], value='https', label='Protocolo').props('outlined dense').classes('w-28')
                target = ui.input('Dirección del módulo destino', placeholder='modulo.ejemplo.com:8443/base').props('outlined dense').classes('grow')

                def follow(event):
                    value = (event.value or '').strip().lower()
                    for candidate in ('https', 'http'):
                        if value.startswith(candidate + '://') and scheme.value != candidate:
                            scheme.set_value(candidate)
                target.on_value_change(follow)
            contracts = core.list_project_items('modules', pid)
            contract = ui.select({'': 'Sin contrato', **{m['id']: m['name'] for m in contracts}}, value='', label='Contrato OpenAPI del módulo (opcional: normaliza las rutas)').props('outlined dense').classes('w-96')

            def create_tap():
                tap = {'name': (name.value or '').strip(), 'company': (company.value or '').strip(), 'owner': (owner.value or '').strip(), 'project_id': pid,
                       'listen_port': int(port.value or 0), 'target': core.normalize_url(target.value, scheme.value), 'module_id': contract.value or None}
                obs.validate_tap(tap)
                core.save('taps', tap)
                ui.notify('Tap creado. Pulsa «Iniciar» para empezar a observar.', type='positive')
                ui.navigate.reload()
            ui.button('Crear tap', icon='add', on_click=guard(create_tap)).props('color=primary')

        for tap in taps:
            running = obs.tap_running(tap['id'])
            with ui.card().classes('w-full').props('flat bordered'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    ui.icon('podcasts', color='positive' if running else 'grey')
                    with ui.column().classes('gap-0 grow'):
                        ui.label(f'{tap["name"]}' + (f' · {tap["company"]}' if tap.get('company') else '')).classes('font-semibold')
                        ui.label(f'http://127.0.0.1:{tap["listen_port"]}  →  {tap["target"]}').classes('font-mono text-sm text-gray-600')
                    calls = ui.label(f'{obs.tap_calls(tap["id"])} llamadas' if running else 'detenido').classes('text-sm text-gray-500')
                    if running:
                        ui.timer(2.0, lambda c=calls, t=tap: c.set_text(f'{obs.tap_calls(t["id"])} llamadas'))

                    def toggle(t=tap):
                        if obs.tap_running(t['id']):
                            obs.stop_tap(t['id'])
                        else:
                            obs.start_tap(t['id'])
                        ui.navigate.reload()
                    ui.button('Detener' if running else 'Iniciar', icon='stop' if running else 'play_arrow', on_click=guard(toggle)) \
                        .props('outline dense color=' + ('negative' if running else 'positive'))

                    def remove(t=tap):
                        obs.stop_tap(t['id'])
                        core.delete('taps', t['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, t=tap, r=remove: confirm(f'¿Eliminar el tap «{t["name"]}»? El catálogo aprendido se conserva.', r)).props('flat round dense color=negative')

        # ------------------------------------------------------------ history
        with ui.row().classes('items-center gap-3'):
            def learn():
                count = obs.observe_runs(pid)
                ui.notify(f'{count} ejecución(es) nuevas aprendidas del historial' if count else 'No hay ejecuciones nuevas que aprender', type='positive' if count else 'info')
                if count:
                    ui.navigate.reload()
            ui.button('Aprender del historial', icon='history', on_click=guard(learn)).props('outline').tooltip('Usa las peticiones y respuestas de tus ejecuciones registradas; cada una cuenta una sola vez')

        # ------------------------------------------------------------ catalog
        if not interfaces:
            empty_state('Todavía no se ha observado nada. Crea y arranca un tap, o aprende del historial.')
            return
        with ui.row().classes('items-center gap-3'):
            filter_module = ui.select({'': 'Todos los módulos', **{i['module']: i['module'] for i in interfaces}}, value='', label='Módulo').props('outlined dense').classes('w-60')
            text = ui.input('Buscar ruta').props('outlined dense clearable').classes('w-60')
        columns = [{'name': 'module', 'label': 'Módulo', 'field': 'module', 'align': 'left', 'sortable': True},
                   {'name': 'method', 'label': 'Método', 'field': 'method', 'align': 'left'},
                   {'name': 'path', 'label': 'Ruta', 'field': 'path', 'align': 'left'},
                   {'name': 'count', 'label': 'Llamadas', 'field': 'count', 'sortable': True},
                   {'name': 'codes', 'label': 'Códigos', 'field': 'codes', 'align': 'left'},
                   {'name': 'seen', 'label': 'Última vez', 'field': 'seen', 'align': 'left'},
                   {'name': 'state', 'label': 'Estado', 'field': 'state', 'align': 'left'}]

        def rows():
            return [{'id': i['id'], 'module': i['module'], 'method': i['method'], 'path': i['path_template'], 'count': i['count'],
                     'codes': ', '.join(f'{k}×{v}' for k, v in sorted(i['statuses'].items())), 'seen': fmt_time(i['last_seen']), 'state': obs.interface_state(i)}
                    for i in interfaces if (not filter_module.value or i['module'] == filter_module.value) and (text.value or '').lower() in i['path_template'].lower()]
        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').props('flat bordered')
        table.add_slot('body-cell-state', '''<q-td :props="props"><q-badge :color="props.value==='sin cambios'?'positive':(props.value==='sin línea base'?'grey':'negative')">{{ props.value }}</q-badge></q-td>''')

        def refresh(_=None):
            table.rows = rows()
            table.update()
        filter_module.on_value_change(refresh)
        text.on_value_change(refresh)
        table.on('rowClick', lambda e: ui.navigate.to(f'/observer/interface?id={e.args[1]["id"]}'))
        ui.label('Haz clic en una fila para ver campos, muestras, cambios y comparación con el contrato.').classes('text-sm text-gray-500')


def _field_rows(section):
    fields = section['fields']
    required = set(obs.required_paths(section))
    rows = []
    for path in sorted(fields):
        info = fields[path]
        parent = obs.parent_path(path)
        base = fields[parent]['count'] if parent in fields else section['total']
        rows.append({'path': path, 'types': ' / '.join(sorted(info['types'])), 'presence': f'{info["count"]}/{base}' + (f' ({round(100 * info["count"] / base)}%)' if base else ''),
                     'required': '✓' if path in required else '', 'examples': ', '.join(json.dumps(e, ensure_ascii=False) for e in info['examples'])})
    return rows


@ui.page('/observer/interface')
def interface_detail(id: str = ''):
    with frame('Interfaz observada', '/observer'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        doc = core.get('interfaces', id) if id else None
        if doc is None:
            ui.label('La interfaz no existe.')
            return
        with ui.row().classes('items-center gap-3'):
            ui.badge(doc['method'], color='primary').classes('text-base')
            ui.label(doc['path_template']).classes('font-mono text-lg')
            ui.label(f'· {doc["module"]}').classes('text-gray-600')
            state_badge(doc)
        ui.label(f'{doc["count"]} llamadas · promedio {doc["avg_ms"]} ms · códigos {", ".join(f"{k}×{v}" for k, v in sorted(doc["statuses"].items()))}'
                 f' · desde {fmt_time(doc["first_seen"])} hasta {fmt_time(doc["last_seen"])}'
                 + (f' · {doc["non_json"]} respuesta(s) no JSON (no analizadas)' if doc['non_json'] else '')
                 + (f' · parámetros de query: {", ".join(doc["query_params"])}' if doc['query_params'] else '')).classes('text-sm text-gray-600')

        def baseline():
            obs.set_baseline(doc['id'])
            ui.notify('Línea base fijada: estos son los formatos aceptados', type='positive')
            ui.navigate.reload()

        def make_case():
            case, env = obs.create_case_from_sample(doc, pid)
            holes = core.find_unresolved(case.get('body'))
            ui.notify(f'Caso «{case["name"]}» creado en el ambiente «{env["name"]}»' + (f'. Completa las variables: {", ".join(holes)}' if holes else ''), type='positive', multi_line=True)

        def remove():
            core.delete('interfaces', doc['id'])
            ui.navigate.to('/observer')
        with ui.row().classes('gap-2'):
            ui.button('Aceptar cambios y fijar línea base' if doc.get('baseline') and doc['drift'] else 'Fijar línea base', icon='flag', on_click=guard(baseline)).props('color=primary')
            ui.button('Crear caso de regresión desde la última muestra', icon='playlist_add', on_click=guard(make_case)).props('outline')
            ui.button('Olvidar esta interfaz', icon='delete', on_click=lambda: confirm('Se borra lo aprendido de esta interfaz (no afecta a tus casos).', remove, 'Olvidar')).props('flat color=negative')

        with ui.tabs().classes('w-full') as tabs:
            tab_fields = ui.tab('Campos')
            tab_changes = ui.tab(f'Cambios ({len(doc["drift"])})')
            tab_samples = ui.tab('Muestras')
            tab_contract = ui.tab('Contrato')
        columns = [{'name': k, 'label': label, 'field': k, 'align': 'left'} for k, label in
                   (('path', 'Campo'), ('types', 'Tipos'), ('presence', 'Presencia'), ('required', 'Obligatorio'), ('examples', 'Ejemplos'))]
        with ui.tab_panels(tabs, value=tab_fields).classes('w-full'):
            with ui.tab_panel(tab_fields):
                sections = [('Solicitud', doc['request'])] + [(f'Respuesta {s}', sec) for s, sec in sorted(doc['responses'].items())]
                sections = [(label, sec) for label, sec in sections if sec['total']]
                if not sections:
                    ui.label('Aún no hay JSON observado en esta interfaz.').classes('text-gray-500')
                for label, section in sections:
                    with ui.expansion(f'{label} · {section["total"]} observación(es)', icon='data_object', value=True).classes('w-full border rounded'):
                        if section['total'] < 2:
                            ui.label('Con una sola observación no se puede saber qué campos son obligatorios.').classes('text-xs text-amber-700')
                        ui.table(columns=columns, rows=_field_rows(section), row_key='path').classes('w-full').props('flat dense')
                        with ui.expansion('JSON Schema observado').classes('w-full'):
                            ui.code(json.dumps(obs.observed_schema(section), indent=2, ensure_ascii=False), language='json').classes('w-full')
            with ui.tab_panel(tab_changes):
                if not doc.get('baseline'):
                    ui.label('Fija una línea base para empezar a detectar cambios: lo observado hasta ahora pasa a ser «lo conocido».').classes('text-gray-600')
                else:
                    ui.label(f'Línea base fijada el {fmt_time(doc["baseline"]["at"])} con {doc["baseline"]["count"]} llamadas.').classes('text-sm text-gray-600')
                    if not doc['drift']:
                        ui.label('Sin cambios respecto a la línea base.').classes('text-green-800')
                for event in sorted(doc['drift'], key=lambda e: e['last_seen'], reverse=True):
                    with ui.row().classes('items-start gap-2 no-wrap'):
                        ui.icon('warning', color='negative')
                        ui.label(f'[{event["where"]}] {event["kind"]}: {event["detail"]} — {event["count"]} vez/veces, última {fmt_time(event["last_seen"])}').classes('text-sm')
            with ui.tab_panel(tab_samples):
                for sample in reversed(doc['samples']):
                    with ui.expansion(f'{fmt_time(sample["at"])} · {sample["path"]}{"?" + sample["query"] if sample.get("query") else ""} · {sample["status"]}').classes('w-full border rounded'):
                        ui.label('Los valores sensibles aparecen como ***.').classes('text-xs text-gray-500')
                        if sample['request'] is not None:
                            ui.label('Solicitud').classes('font-medium')
                            ui.code(json.dumps(sample['request'], indent=2, ensure_ascii=False), language='json').classes('w-full')
                        if sample['response'] is not None:
                            ui.label('Respuesta').classes('font-medium')
                            ui.code(json.dumps(sample['response'], indent=2, ensure_ascii=False), language='json').classes('w-full')
            with ui.tab_panel(tab_contract):
                modules = core.list_project_items('modules', pid)
                if not modules:
                    ui.label('Importa el contrato OpenAPI del módulo (menú Módulos) para compararlo con lo observado.').classes('text-gray-600')
                else:
                    pick = ui.select({m['id']: m['name'] for m in modules}, label='Contrato OpenAPI', value=modules[0]['id']).props('outlined dense').classes('w-80')
                    out = ui.column().classes('w-full gap-1')

                    def compare():
                        out.clear()
                        result = obs.compare_with_contract(doc, core.get('modules', pick.value))
                        with out:
                            if not result['issues']:
                                ui.label('Lo observado coincide con el contrato.').classes('text-green-800')
                            for issue in result['issues']:
                                with ui.row().classes('items-start gap-2 no-wrap'):
                                    ui.icon('error_outline', color='negative' if result['matched'] else 'grey')
                                    ui.label(issue).classes('text-sm')
                    ui.button('Comparar con lo observado', icon='compare', on_click=guard(compare)).props('color=primary')
