import io
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from pathlib import Path
import pytest
from app import core

SPEC='''openapi: 3.0.3
info:
  title: Demo
  version: '1'
paths:
  /hello:
    get:
      responses:
        '200':
          description: ok
'''

@pytest.fixture(autouse=True)
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DB',tmp_path/'test.db')
    monkeypatch.setattr(core,'ARTIFACTS',tmp_path/'evidence')
    core.initialize()

def test_openapi():
    m=core.import_openapi(SPEC)
    assert m['operations'][0]['path']=='/hello'
    assert len(core.list_items('modules'))==1
    with pytest.raises(ValueError):core.import_openapi('foo: bar')


def test_openapi_resolves_local_refs_and_rejects_external_refs():
    raw=json.dumps({'openapi':'3.0.3','info':{'title':'Refs'},'components':{'parameters':{'Trace':{'name':'X-Trace','in':'header','required':True}}},'paths':{'/items':{'get':{'parameters':[{'$ref':'#/components/parameters/Trace'}],'responses':{'200':{'description':'ok'}}}}}})
    module=core.parse_openapi(raw)
    assert module['operations'][0]['parameters'][0]['name']=='X-Trace'
    with pytest.raises(ValueError, match='locales'):
        core.parse_openapi(json.dumps({'openapi':'3.0.3','paths':{'/x':{'get':{'$ref':'other.yaml#/get'}}}}))


def test_projects_persist_and_select_active():
  project=core.create_project('Comercial', 'Pruebas del módulo comercial')
  module=core.import_openapi(SPEC, project['id'])
  assert core.get('projects', project['id'])['name']=='Comercial'
  assert module['project_id']==project['id']
  assert core.get_active_project_id()==project['id']
  other=core.create_project('Operaciones')
  core.set_active_project(other['id'])
  assert core.get_active_project_id()==other['id']
  with pytest.raises(ValueError):core.set_active_project('missing-project')


def test_project_update_stats_and_safe_delete():
  project=core.create_project('Temporal')
  assert core.project_stats(project['id'])['modules']==0
  updated=core.update_project(project['id'], 'Temporal actualizado', 'Descripción')
  assert updated['name']=='Temporal actualizado'
  core.import_openapi(SPEC, project['id'])
  assert core.project_stats(project['id'])['modules']==1
  with pytest.raises(ValueError, match='recursos asociados'):
    core.delete_project(project['id'])
  empty=core.create_project('Vacío')
  core.delete_project(empty['id'])
  assert core.get('projects', empty['id']) is None

def test_roundtrip(tmp_path):
    m=core.import_openapi(SPEC)
    c=core.save('cases',{'name':'demo','module_id':m['id'],'assertions':[]})
    core.save('suites',{'name':'smoke','case_ids':[c['id']]})
    p=core.export_workspace(tmp_path/'out.zip')
    assert core.import_workspace(p,'merge')['modules']==0
    counts=core.import_workspace(p,'new')
    assert counts['modules']==1 and counts['cases']==1
    assert len(core.list_items('modules'))==2
    assert all(s['case_ids'][0] in [x['id'] for x in core.list_items('cases')] for s in core.list_items('suites'))

def test_http_run():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
          self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('X-Test','ok');self.end_headers();self.wfile.write(b'{"ok":true,"count":3}')
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        env=core.save('environments',{'base_url':f'http://127.0.0.1:{server.server_port}','auth':{'type':'none'}})
        case=core.save('cases',{'name':'test','method':'GET','path':'/hello','assertions':[{'type':'status','expected':200},{'type':'json_equals','path':'ok','expected':True},{'type':'header_equals','name':'X-Test','expected':'ok'},{'type':'numeric_greater','path':'count','expected':2},{'type':'response_time_max','expected':1000}]})
        result=core.execute_api(case,env)
        assert result['status']=='passed'
        assert len(core.list_items('runs'))==1
    finally:server.shutdown();server.server_close()


def test_project_filtering_and_adoption():
    a=core.create_project('A'); b=core.create_project('B')
    core.import_openapi(SPEC,a['id']); core.import_openapi(SPEC,b['id'])
    legacy=core.import_openapi(SPEC)
    assert len(core.list_project_items('modules',a['id']))==1
    assert len(core.list_project_items('modules',None))==3
    assert core.adopt_unassigned(a['id'])['modules']==1
    assert core.get('modules',legacy['id'])['project_id']==a['id']
    assert len(core.list_project_items('modules',b['id']))==1


def test_suite_requires_same_project_and_schedule_inherits_it():
    from app import automation
    a=core.create_project('A'); b=core.create_project('B')
    env_a=core.save('environments',{'name':'qa','project_id':a['id'],'base_url':'http://127.0.0.1'})
    case_a=core.save('cases',{'name':'c','project_id':a['id']})
    case_b=core.save('cases',{'name':'c','project_id':b['id']})
    with pytest.raises(ValueError,match='no pertenece'):
        core.save_suite('s',env_a['id'],[case_b['id']],a['id'])
    with pytest.raises(ValueError,match='no pertenece'):
        core.save_suite('s',env_a['id'],[case_a['id']],b['id'])
    suite=core.save_suite('s',env_a['id'],[case_a['id']],a['id'])
    assert suite['project_id']==a['id']
    schedule=automation.create_schedule(suite['id'],'daily','02:00','UTC')
    assert schedule['project_id']==a['id']
    assert core.project_stats(a['id'])['schedules']==1


def test_export_import_keeps_projects(tmp_path):
    a=core.create_project('A')
    core.import_openapi(SPEC,a['id'])
    path=core.export_workspace(tmp_path/'p.zip')
    counts=core.import_workspace(path,'new')
    assert counts['projects']==1 and counts['modules']==1
    new_ids={p['id'] for p in core.list_items('projects')}-{a['id']}
    assert len(new_ids)==1
    copied=[m for m in core.list_items('modules') if m['project_id'] in new_ids]
    assert len(copied)==1


def test_reset_workspace_wipes_everything():
    a=core.create_project('A')
    core.import_openapi(SPEC,a['id'])
    shot=core.ARTIFACTS/'evidence.txt'
    shot.write_text('x')
    core.reset_workspace()
    assert core.list_items('projects')==[]
    assert core.list_items('modules')==[]
    assert core.get_active_project_id() is None
    assert not shot.exists()
    assert core.DB.exists()  # the schema is recreated, usable right away


def test_reset_workspace_can_keep_evidence():
    core.create_project('A')
    shot=core.ARTIFACTS/'evidence.txt'
    shot.write_text('x')
    core.reset_workspace(remove_evidence=False)
    assert core.list_items('projects')==[]
    assert shot.exists()
