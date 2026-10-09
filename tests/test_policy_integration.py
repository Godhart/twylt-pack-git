import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
BASE=Path(__file__).resolve().parents[1]
TOOLS=sorted(p for p in (BASE/'tools').iterdir() if p.is_dir())

def call(op,data,env):
    return subprocess.run([sys.executable,str(BASE/'tools'/op/'run.py'),json.dumps(data)],env=env,text=True,capture_output=True,timeout=20)

def setup_env(tmp_path):
    root=tmp_path/'ws';root.mkdir()
    log=tmp_path/'audit.jsonl'
    env={**os.environ,'TWYLT_WORKSPACE_ROOT':str(root),'TWYLT_INCIDENT_LOG':str(log)}
    env.pop('INPUT_DESCRIBE',None)
    return root,log,env

@pytest.mark.parametrize('tool',TOOLS,ids=lambda p:p.name)
def test_every_tool_requires_root(tool,tmp_path):
    env={**os.environ};env.pop('TWYLT_WORKSPACE_ROOT',None);env.pop('TWYLT_INCIDENT_LOG',None);env.pop('INPUT_DESCRIBE',None)
    result=call(tool.name,json.loads((tool/'example.json').read_text()),env)
    assert result.returncode==6 and not result.stdout
    event=json.loads(result.stderr.splitlines()[0])
    assert event['code']=='workspace_not_configured' and event['tool']==tool.name
    described=call(tool.name,{'describe':'json_spec'},env)
    assert described.returncode==0 and json.loads(described.stdout)['name']==tool.name

@pytest.mark.parametrize('tool',TOOLS,ids=lambda p:p.name)
def test_every_tool_checks_log_before_business(tool,tmp_path):
    root,log,env=setup_env(tmp_path)
    env['TWYLT_INCIDENT_LOG']=str(tmp_path/'absent'/'audit.jsonl')
    result=call(tool.name,json.loads((tool/'example.json').read_text()),env)
    assert result.returncode==6
    assert json.loads(result.stderr.splitlines()[0])['code']=='incident_log_unavailable'
    assert list(root.iterdir())==[]

def native(*args):
    return subprocess.run(['git',*map(str,args)],capture_output=True,text=True,check=True).stdout.strip()

def repository(path):
    native('init','--initial-branch=main',path)
    native('-C',path,'config','user.name','Test')
    native('-C',path,'config','user.email','test@example.invalid')
    return path

@pytest.mark.parametrize('key,value', [('include.path','/outside/config'),('core.worktree','/outside'),('filter.evil.clean','touch /outside'),('core.sshCommand','touch /outside')])
def test_git_implicit_config_paths(tmp_path,key,value):
    root,log,env=setup_env(tmp_path)
    repo=repository(root/'repo')
    native('-C',repo,'config',key,value)
    p=call('git_status',{'repo':'/repo'},env)
    assert p.returncode==6
    assert json.loads(log.read_text())['code']=='git_config_forbidden'
    assert '/outside' not in log.read_text()

@pytest.mark.parametrize('op', ['git_fetch','git_pull','git_push'])
def test_local_remote_outside(tmp_path,op):
    root,log,env=setup_env(tmp_path)
    repo=repository(root/'repo')
    remote=tmp_path/'outside.git';native('init','--bare',remote)
    native('-C',repo,'remote','add','origin',remote)
    p=call(op,{'repo':'/repo'},env)
    assert p.returncode==6
    assert json.loads(log.read_text())['code']=='git_local_remote_outside_workspace'

@pytest.mark.parametrize('kind', ['gitfile','alternates','symlink'])
def test_git_storage_redirection(tmp_path,kind):
    root,log,env=setup_env(tmp_path)
    repo=repository(root/'repo')
    if kind=='gitfile':
        (repo/'.git').rename(root/'hidden.git');(repo/'.git').write_text('gitdir: ../hidden.git\n')
    elif kind=='alternates':
        (repo/'.git/objects/info/alternates').write_text(str(tmp_path/'outside')+'\n')
    else: (repo/'link').symlink_to(tmp_path)
    p=call('git_log',{'repo':'/repo'},env)
    assert p.returncode==6 and len(log.read_text().splitlines())==1

@pytest.mark.skipif(os.name!='posix',reason='shell hook')
def test_hooks_disabled_and_clone_symlink_tree(tmp_path):
    root,log,env=setup_env(tmp_path)
    repo=repository(root/'repo')
    marker=tmp_path/'hook-ran'
    hook=repo/'.git/hooks/pre-commit';hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\n');hook.chmod(0o755)
    (repo/'a').write_text('hello');native('-C',repo,'add','a')
    p=call('git_commit',{'repo':'/repo','message':'Initial'},env)
    assert p.returncode==0 and json.loads(p.stdout)['ok'] and not marker.exists()
    # Native setup creates a symlink commit, then removes the physical symlink.
    (repo/'link').symlink_to(tmp_path);native('-C',repo,'add','link')
    hook.unlink();native('-C',repo,'commit','-m','Link');(repo/'link').unlink()
    p=call('git_clone',{'url':'/repo','destination':'/clone'},env)
    assert p.returncode==6
    assert json.loads(log.read_text())['code']=='git_symlink_tree_forbidden'
    assert not (root/'clone/link').exists() and not (root/'clone/link').is_symlink()

def test_clone_traversal_and_credentials_not_logged(tmp_path):
    root,log,env=setup_env(tmp_path)
    p=call('git_clone',{'url':'https://name:supersecret@example.invalid/repo','destination':'../escape'},env)
    assert p.returncode==6 and 'supersecret' not in log.read_text()
    assert json.loads(log.read_text())['requested_path']=='../escape'

def test_file_transport_cannot_escape(tmp_path):
    root,log,env=setup_env(tmp_path)
    tool=TOOLS[0]
    (tmp_path/'output.json').write_text('keep outside')
    p=subprocess.run([sys.executable,str(tool/'run.py')],cwd=tmp_path,stdin=subprocess.DEVNULL,env=env,text=True,capture_output=True)
    assert p.returncode==6 and (tmp_path/'output.json').read_text()=='keep outside'
    assert json.loads(log.read_text())['code']=='transport_cwd_or_path_outside_allowed_roots'
    log.write_text('')
    target=tmp_path/'outside';target.write_text('keep target')
    (root/'output.json').symlink_to(target)
    p=subprocess.run([sys.executable,str(tool/'run.py')],cwd=root,stdin=subprocess.DEVNULL,env=env,text=True,capture_output=True)
    assert p.returncode==6 and target.read_text()=='keep target' and (root/'output.json').is_symlink()
    assert json.loads(log.read_text())['code']=='symlink_forbidden'
