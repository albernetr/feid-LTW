"""Suites: un grupo que junta varios Flujos (/suites) y/o Casos sueltos para correrlos todos de una vez y sacar un
solo reporte combinado — a diferencia de un Flujo, que es UNA secuencia ordenada de pasos encadenados entre sí
(Sorteos, variables compartidas, enriquecimiento). Una Suite no encadena nada entre sus miembros: cada uno corre
con lo suyo propio; lo único que comparten es el ambiente (para los Casos sueltos) y quedar en un solo reporte."""
from nicegui import ui, run
from .. import core, automation
from .common import frame, guard, confirm, empty_state, require_project, show_run


async def run_group(group):
    token = automation.new_cancel_token()
    progress = []
    with ui.dialog().props('persistent') as dialog, ui.card().classes('w-96'):
        ui.label(f'Ejecutando «{group["name"]}»').classes('text-lg font-semibold')
        ui.linear_progress(show_value=False).props('indeterminate')
        status = ui.label('Iniciando…').classes('text-gray-600 text-sm')

        def cancel():
            token.set()
            status.set_text('Cancelando tras el miembro en curso…')
        ui.button('Cancelar ejecución', icon='stop', on_click=cancel).props('outline color=negative')
    dialog.open()
    timer = ui.timer(0.5, lambda: status.set_text(f'{len(progress)} de {len(group["members"])} miembros terminados'))
    try:
        result = await run.io_bound(automation.execute_suite_group, group, token, progress.append)
    finally:
        timer.cancel()
        dialog.close()
    show_run(result)
    return result


@ui.page('/suite-groups')
def suite_groups_list():
    with frame('Suites', '/suite-groups'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.button('Nueva suite', icon='add', on_click=lambda: ui.navigate.to('/suite-groups/edit')).props('color=primary')
        items = core.list_project_items('suite_groups', pid)
        if not items:
            empty_state('No hay suites. Una suite junta varios Flujos y/o Casos sueltos para correrlos todos de una vez.')
        for group in items:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    with ui.column().classes('gap-0 grow'):
                        ui.label(group['name']).classes('font-semibold')
                        policy = 'se detiene al primer fallo' if group.get('on_failure') == 'stop' else 'continúa tras fallos'
                        flows = sum(1 for m in group['members'] if m['type'] == 'flow')
                        cases = sum(1 for m in group['members'] if m['type'] == 'case')
                        ui.label(f'{flows} flujo(s) · {cases} caso(s) suelto(s) · {policy}').classes('text-sm text-gray-500')
                    ui.button(icon='play_arrow', on_click=guard(lambda g=group: run_group(g))).props('flat round color=positive').tooltip('Ejecutar')
                    ui.button(icon='edit', on_click=lambda _, i=group['id']: ui.navigate.to(f'/suite-groups/edit?id={i}')).props('flat round').tooltip('Editar')

                    def remove(g=group):
                        core.delete('suite_groups', g['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, g=group, r=remove: confirm(f'¿Eliminar la suite «{g["name"]}»?', r)).props('flat round color=negative')


@ui.page('/suite-groups/edit')
def suite_group_edit(id: str = ''):
    with frame('Editor de suite', '/suite-groups'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('suite_groups', id) if id else None
        if id and current is None:
            ui.label('La suite no existe.')
            return
        envs = core.list_project_items('environments', pid)
        flows = {s['id']: s for s in core.list_project_items('suites', pid)}
        cases = {c['id']: c for c in core.list_project_items('cases', pid) if c.get('type') != 'ui'}
        if not envs:
            ui.label('Necesitas al menos un ambiente en este proyecto.').classes('text-amber-700')
            return
        members = [dict(m) for m in (current or {}).get('members', [])]
        members = [m for m in members if (flows if m['type'] == 'flow' else cases).get(m['id'])]

        with ui.card().classes('w-full'):
            with ui.row().classes('w-full gap-3'):
                name = ui.input('Nombre', value=(current or {}).get('name', 'Regresión completa')).props('outlined dense').classes('grow')
                env = ui.select({e['id']: e['name'] for e in envs}, value=(current or {}).get('environment_id') or (envs[0]['id'] if envs else None),
                                label='Ambiente (para los casos sueltos)').props('outlined dense').classes('w-72')
                on_failure = ui.select({'continue': 'Continuar tras un fallo', 'stop': 'Detener al primer fallo'},
                                       value=(current or {}).get('on_failure', 'continue'), label='Política de fallo').props('outlined dense').classes('w-64')

        with ui.row().classes('w-full gap-4 items-start no-wrap'):
            with ui.card().classes('w-1/2'):
                ui.label('Flujos y casos disponibles').classes('font-semibold')
                filter_input = ui.input('Filtrar por nombre').props('outlined dense clearable').classes('w-full').on_value_change(lambda e: available.refresh(e.value or ''))
                with ui.column().classes('w-full gap-1').style('max-height:55vh;overflow-y:auto'):
                    @ui.refreshable
                    def available(text=''):
                        text = (text or '').lower()
                        pool = [('flow', f) for f in flows.values() if text in f['name'].lower()] + [('case', c) for c in cases.values() if text in c['name'].lower()]
                        if not pool:
                            ui.label('Sin coincidencias').classes('text-gray-500')
                        for kind, item in pool:
                            added = any(m['type'] == kind and m['id'] == item['id'] for m in members)
                            with ui.row().classes('items-center w-full gap-2 no-wrap'):
                                ui.badge('Flujo' if kind == 'flow' else 'Caso', color='deep-orange' if kind == 'flow' else 'primary').classes('shrink-0')
                                ui.label(item['name']).classes('grow').style('min-width:0')
                                if added:
                                    ui.badge('Agregado', color='positive').classes('shrink-0 text-xs')
                                else:
                                    def add(k=kind, i=item['id']):
                                        members.append({'type': k, 'id': i})
                                        chosen.refresh()
                                        available.refresh(filter_input.value or '')
                                    ui.button(icon='add', on_click=lambda _, f=add: f()).props('flat round dense color=primary').classes('shrink-0').tooltip('Agregar')
                    available()
            with ui.card().classes('w-1/2'):
                ui.label('Orden de ejecución').classes('font-semibold')

                @ui.refreshable
                def chosen():
                    if not members:
                        ui.label('Agrega flujos o casos desde la izquierda.').classes('text-gray-500')
                    for index, member in enumerate(members):
                        pool = flows if member['type'] == 'flow' else cases
                        item = pool.get(member['id'])
                        with ui.row().classes('items-center w-full gap-2 no-wrap'):
                            ui.label(f'{index + 1}.').classes('w-6 text-gray-500')
                            ui.badge('Flujo' if member['type'] == 'flow' else 'Caso', color='deep-orange' if member['type'] == 'flow' else 'primary').classes('shrink-0')
                            ui.label(item['name'] if item else '(eliminado)').classes('grow').style('min-width:0')

                            def move(delta, i=index):
                                j = i + delta
                                if 0 <= j < len(members):
                                    members[i], members[j] = members[j], members[i]
                                    chosen.refresh()
                            ui.button(icon='arrow_upward', on_click=lambda _, m=move: m(-1)).props('flat round dense')
                            ui.button(icon='arrow_downward', on_click=lambda _, m=move: m(1)).props('flat round dense')
                            ui.button(icon='close', on_click=lambda _, i=index: (members.pop(i), chosen.refresh(), available.refresh(filter_input.value or ''))) \
                                .props('flat round dense color=negative')
                chosen()

        def save():
            options = dict(id=(current or {}).get('id'), on_failure=on_failure.value, environment_id=env.value)
            if current:
                options['expected_updated_at'] = current.get('updated_at')
            saved = core.save_suite_group(name.value or '', pid, members, **options)
            if current:
                current['updated_at'] = saved['updated_at']
            ui.notify('Suite guardada', type='positive')
            return saved
        with ui.row().classes('gap-3'):
            ui.button('Guardar', icon='save', on_click=guard(lambda: (save(), ui.navigate.to('/suite-groups')))).props('color=primary')

            async def save_and_run():
                await run_group(save())
            ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline color=positive')
            ui.button('Volver', on_click=lambda: ui.navigate.to('/suite-groups')).props('flat')
