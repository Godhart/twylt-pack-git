import json,os,shutil,subprocess,sys
from pathlib import Path
import pytest
from toolpack_builder.builder import BuildConfig,scan,build_from_report
BASE=Path(__file__).resolve().parents[1]

def test_copied_pack_builder_nested_transport(tmp_path,monkeypatch):
    pack=tmp_path/'copied'
    shutil.copytree(BASE/'tools',pack/'tools',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(BASE/'shared',pack/'shared',ignore=shutil.ignore_patterns('__pycache__'))
    config=BuildConfig(root=pack/'tools',glob='*/tool.py',python=sys.executable)
    report=scan(config)
    assert len(report.valid)==10,report.failed
    payload=build_from_report(config,report).payload
    tools={t['name']:t for t in payload['category']['tools']}
    workspace=tmp_path/'workspace';workspace.mkdir()
    runs=tmp_path/'transport';cwd=runs/'request'/'nested';cwd.mkdir(parents=True)
    env={**os.environ,'TWYLT_GUARDRAILS':'1','TWYLT_WORKSPACE_ROOT':str(workspace),
         'TWYLT_ALLOWED_CWD':str(runs),'TWYLT_DISABLE_NETWORK':'0','TWYLT_INCIDENT_LOG':''}
    subprocess.run(['git','init',str(workspace/'repo')],check=True,capture_output=True)
    (cwd/'input.json').write_text(json.dumps({'repo':'/repo'}))
    code=''+tools['git_status']['code']
    r=subprocess.run([sys.executable,'-c',code],cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                     capture_output=True,text=True,timeout=20)
    assert r.returncode==0,r.stderr
    result=json.loads((cwd/'output.json').read_text())
    assert result['ok']
    assert not (workspace/'output.json').exists()


def test_network_clone_denied_before_git(tmp_path,monkeypatch):
    monkeypatch.setenv('TWYLT_DISABLE_NETWORK','1')
    monkeypatch.setenv('TWYLT_WORKSPACE_ROOT',str(tmp_path))
    r=subprocess.run([sys.executable,str(BASE/'tools/git_clone/run.py'),
                      '{"url":"https://example.invalid/repo.git","destination":"/new"}'],
                     capture_output=True,text=True,timeout=10)
    assert r.returncode==6,r.stderr
    assert json.loads(r.stderr.splitlines()[-1])['error']['code']=='network_disabled'
    assert not (tmp_path/'new').exists()

@pytest.mark.parametrize('operation',['fetch','pull','push'])
def test_network_remote_operations_denied(tmp_path,monkeypatch,operation):
    monkeypatch.setenv('TWYLT_DISABLE_NETWORK','1')
    monkeypatch.setenv('TWYLT_WORKSPACE_ROOT',str(tmp_path))
    subprocess.run(['git','init',str(tmp_path/'repo')],check=True,capture_output=True)
    subprocess.run(['git','-C',str(tmp_path/'repo'),'remote','add','origin','https://example.invalid/repo.git'],check=True)
    payload={'repo':'/repo','remote':'origin'}
    if operation=='pull':payload['branch']='main'
    r=subprocess.run([sys.executable,str(BASE/'tools'/('git_'+operation)/'run.py'),json.dumps(payload)],
                     capture_output=True,text=True,timeout=10)
    assert r.returncode==6,r.stderr
    assert json.loads(r.stderr.splitlines()[-1])['error']['code']=='network_disabled'
