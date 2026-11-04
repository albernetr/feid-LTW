"""Small editors shared by the workspace. They take GETTERS so they keep working when the draft is replaced."""
import json
from nicegui import ui
from .. import core, workspace as ws
from .common import parse_value, show_value

STRING_ONLY = ('contains', 'not_contains', 'regex', 'json_regex', 'header_equals', 'header_contains', 'body_equals')
METHOD_COLOR = {'GET': 'positive', 'POST': 'primary', 'PUT': 'orange', 'PATCH': 'purple', 'DELETE': 'negative'}


def method_badge(method):
    return ui.badge(method, color=METHOD_COLOR.get(method, 'grey')).classes('w-14 justify-center text-xs')


def status_chip(http_status, error=False):
    if error or not http_status:
        return ui.badge('error' if error else '—', color='negative' if error else 'grey').classes('text-xs')
    color = 'positive' if http_status < 300 else 'warning' if http_status < 400 else 'negative'
    return ui.badge(str(http_status), color=color).classes('text-xs')


def kv_rows(get_rows, key_label='Nombre', value_label='Valor', on_change=None, suggestions=()):
    """Rows with an on/off checkbox (disabled rows are kept but not sent) and a bulk-text mode for fast editing."""
    state = {'bulk': False}

    @ui.refreshable
    def view():
        rows = get_rows()
        if state['bulk']:
            area = ui.textarea(value=ws.format_bulk(rows), placeholder=f'{key_label}: {value_label}  (una por línea; # al inicio la desactiva)') \
                .props('outlined dense autogrow input-class=font-mono').classes('w-full')

            def apply(e=None):
                rows[:] = ws.parse_bulk(area.value)
                if on_change:
                    on_change()
            area.on('blur', apply)
        else:
            for item in list(rows):
                with ui.row().classes('w-full items-center gap-1 no-wrap'):
                    ui.checkbox(value=item.get('on', True)).props('dense').on_value_change(lambda e, r=item: (r.__setitem__('on', e.value), on_change and on_change()))
                    ui.input(placeholder=key_label, value=item['key']).props('outlined dense').classes('w-2/5') \
                        .on_value_change(lambda e, r=item: (r.__setitem__('key', e.value), on_change and on_change()))
                    ui.input(placeholder=value_label, value=item['value']).props('outlined dense').classes('grow') \
                        .on_value_change(lambda e, r=item: (r.__setitem__('value', e.value), on_change and on_change()))
                    ui.button(icon='close', on_click=lambda _, r=item: (rows.remove(r), view.refresh(), on_change and on_change())).props('flat round dense size=sm color=grey')
        with ui.row().classes('items-center gap-2'):
            if not state['bulk']:
                ui.button('Agregar', icon='add', on_click=lambda: (rows.append(ws.row()), view.refresh())).props('flat dense color=primary size=sm')
            for label, key, value in suggestions:
                ui.button(label, on_click=lambda _, k=key, v=value: (rows.append(ws.row(k, v)), view.refresh(), on_change and on_change())).props('flat dense size=sm color=grey no-caps')
            ui.space()
            ui.switch('Texto', value=state['bulk'], on_change=lambda e: (state.__setitem__('bulk', e.value), view.refresh())).props('dense').tooltip('Edición masiva: una línea por elemento')
    view()
    return view


DYNAMIC_VAR_HINTS = (('now_date', 'fecha de hoy'), ('now_time', 'hora actual'), ('now_iso', 'fecha y hora, ISO 8601'),
                      ('now_epoch', 'segundos desde 1970'), ('uuid', 'identificador único'), ('seq', 'consecutivo global'))


def dynamic_variable_chips():
    """Botones para copiar las variables integradas ({{now_date}}, {{uuid}}, {{seq}}…): se calculan solas en cada
    envío, nunca hay que declararlas acá — tocar uno copia el texto al portapapeles para pegarlo donde haga falta
    (headers, query, body). El detalle (y los consecutivos con nombre, {{seq:nombre}}) vive en Variables y secuencias."""
    with ui.row().classes('items-center gap-1 flex-wrap'):
        ui.label('Ya calculadas, toca para copiar:').classes('text-xs text-gray-500')
        for name, hint in DYNAMIC_VAR_HINTS:
            token = '{{' + name + '}}'
            ui.button(token, on_click=lambda _, t=token: (ui.clipboard.write(t), ui.notify(f'Copiado {t}', type='positive'))) \
                .props('flat dense size=sm no-caps color=grey-8').tooltip(hint)
        ui.link('Ver / ajustar consecutivos →', '/sequences').classes('text-xs')


def json_box(value, on_set):
    """Editable JSON with the same fold/unfold affordances as a JSON formatter, instead of one giant textarea
    that only ever grows taller. on_set(value) runs with the parsed value whenever it changes validly."""
    def changed(e):
        content = e.content or {}
        if 'json' in content:
            on_set(content['json'])
            return
        try:
            on_set(json.loads(content.get('text') or 'null'))
        except ValueError:
            pass   # mid-edit invalid text (e.g. a trailing comma): keep the last valid value, don't discard it
    return ui.json_editor({'content': {'json': value}}, on_change=changed).classes('w-full').style('height:280px')


def assertion_rows(get_rules, get_results=lambda: [], on_change=None, get_paths=lambda: []):
    """Visual editor of assertions; shows pass/fail of the last response next to each rule.
    get_paths: () -> [(path, preview), ...] from the last response, so a JSONPath can be picked instead of typed."""
    @ui.refreshable
    def view():
        rules = get_rules()
        results = get_results()
        if not rules:
            ui.label('Sin pruebas. Agrégalas o genéralas desde la respuesta.').classes('text-gray-500 text-sm')
        for index, rule in enumerate(rules):
            with ui.column().classes('w-full gap-1 border rounded p-2'):
                with ui.row().classes('w-full items-center gap-1 no-wrap'):
                    if index < len(results):
                        ui.icon('check_circle' if results[index]['passed'] else 'cancel', color='positive' if results[index]['passed'] else 'negative', size='sm')

                    def change_type(event, r=rule):
                        r.clear()
                        r['type'] = event.value
                        view.refresh()
                    ui.select({k: v['label'] for k, v in core.ASSERTION_TYPES.items()}, value=rule['type'], on_change=change_type).props('outlined dense options-dense').classes('grow')
                    ui.button(icon='close', on_click=lambda _, r=rule: (rules.remove(r), view.refresh(), on_change and on_change())).props('flat round dense size=sm color=grey')
                fields = core.ASSERTION_TYPES.get(rule['type'], {}).get('fields', [])
                with ui.row().classes('w-full gap-1 no-wrap'):
                    if 'path' in fields:
                        path_options = {path: f'{path}   ·   {preview}' for path, preview in get_paths()}
                        current = rule.get('path', '')
                        if current and current not in path_options:
                            path_options = {current: current, **path_options}
                        ui.select(path_options, value=current or None, label='JSONPath', with_input=True, new_value_mode='add-unique') \
                            .props('outlined dense options-dense fill-input hide-selected input-debounce=0').classes('grow') \
                            .on_value_change(lambda e, r=rule: r.__setitem__('path', e.value or '')) \
                            .tooltip('Elegí un campo de la última respuesta o escribí la ruta vos mismo')
                    if 'name' in fields:
                        ui.input('Header', value=rule.get('name', '')).props('outlined dense').classes('grow').on_value_change(lambda e, r=rule: r.__setitem__('name', e.value))
                    if 'expected' in fields and rule['type'] == 'json_type':
                        ui.select(list(core.JSON_TYPES), value=rule.get('expected'), label='Tipo').props('outlined dense').classes('w-32') \
                            .on_value_change(lambda e, r=rule: r.__setitem__('expected', e.value))
                    elif 'expected' in fields and rule['type'] not in ('json_matches',):
                        def set_expected(e, r=rule):
                            r['expected'] = e.value if r['type'] in STRING_ONLY else parse_value(e.value)
                        ui.input('Esperado', value=show_value(rule['expected']) if 'expected' in rule else '').props('outlined dense').classes('w-32').on_value_change(set_expected)
                if rule['type'] == 'json_matches':
                    ui.label('JSON esperado').classes('text-xs text-gray-500')
                    json_box(rule.get('expected', {}), lambda v, r=rule: r.__setitem__('expected', v))
                    ui.input('Ignorar (JSONPath, coma)', value=', '.join(rule.get('ignore', []))).props('outlined dense').classes('w-full') \
                        .on_value_change(lambda e, r=rule: r.__setitem__('ignore', [p.strip() for p in (e.value or '').split(',') if p.strip()]))
                if 'schema' in fields:
                    ui.label('JSON Schema').classes('text-xs text-gray-500')
                    json_box(rule.get('schema', {}), lambda v, r=rule: r.__setitem__('schema', v))
                    ui.input('Ignorar (JSONPath, coma)', value=', '.join(rule.get('ignore', []))).props('outlined dense').classes('w-full') \
                        .on_value_change(lambda e, r=rule: r.__setitem__('ignore', [p.strip() for p in (e.value or '').split(',') if p.strip()])) \
                        .tooltip('Lo deja fuera del schema (ni requerido ni validado) — útil para campos volátiles como fechas')
                if index < len(results) and not results[index]['passed']:
                    ui.label('→ obtenido: ' + show_value(results[index]['actual'])[:200]).classes('text-xs text-red-700 whitespace-pre-wrap')
        ui.button('Agregar prueba', icon='add', on_click=lambda: (rules.append({'type': 'status', 'expected': 200}), view.refresh(), on_change and on_change())).props('flat dense color=primary size=sm')
    view()
    return view
