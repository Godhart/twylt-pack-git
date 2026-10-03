import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
BASE = Path(__file__).resolve().parents[1]
OPS = ['clone','fetch','pull','put','add','commit','push','diff','status','log']

@pytest.fixture(autouse=True)
def configured_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('TWYLT_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.delenv('TWYLT_INCIDENT_LOG', raising=False)

def virtual_input(data):
    data = dict(data)
    root = Path(os.environ['TWYLT_WORKSPACE_ROOT'])
    for field in ['repo', 'url', 'destination']:
        if field in data:
            path = Path(data[field])
            if path == root or root in path.parents:
                data[field] = '/' + path.relative_to(root).as_posix()
    return data

def invoke(op, data):
    data = virtual_input(data)
    p = subprocess.run([sys.executable,str(BASE/'tools'/('git_'+op)/'run.py'),json.dumps(virtual_input(data))],capture_output=True,text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)

def native(*args):
    return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()

@pytest.fixture
def repos(tmp_path):
    remote = tmp_path/'remote.git'
    a, b = tmp_path/'a', tmp_path/'b'
    native('init','--bare','--initial-branch=main',remote)
    assert invoke('clone',{'url':str(remote),'destination':str(a)})['ok']
    native('-C',a,'config','user.name','Test')
    native('-C',a,'config','user.email','test@example.invalid')
    return remote, a, b

def test_full_cycle(repos):
    remote,a,b = repos
    repo = {'repo':str(a)}
    assert invoke('put',dict(repo,path='src/a.txt',content='one\n'))['paths'] == ['src/a.txt']
    assert invoke('add',dict(repo,paths=['src/a.txt']))['ok']
    assert '+one' in invoke('diff',dict(repo,staged=True))['stdout']
    assert invoke('commit',dict(repo,message='First'))['ok']
    assert invoke('push',dict(repo,set_upstream=True))['ok']
    assert invoke('clone',{'url':str(remote),'destination':str(b)})['ok']
    assert invoke('put',dict(repo,path='src/a.txt',content='two\n',overwrite=True))['ok']
    assert '+two' in invoke('diff',repo)['stdout']
    assert invoke('add',dict(repo,paths=['.']))['ok']
    assert invoke('commit',dict(repo,message='Second'))['ok']
    assert invoke('push',repo)['ok']
    assert invoke('fetch',{'repo':str(b),'prune':True,'tags':True})['ok']
    assert (b/'src/a.txt').read_text() == 'one\n'
    assert invoke('pull',{'repo':str(b)})['ok']
    assert (b/'src/a.txt').read_text() == 'two\n'
    assert '+two' in invoke('diff',dict(repo,base='HEAD~1',target='HEAD'))['stdout']
    assert not invoke('commit',dict(repo,message='Empty'))['ok']
    (a/'src/a.txt').unlink()
    assert invoke('add',dict(repo,paths=['src/a.txt']))['ok']
    assert 'deleted file' in invoke('diff',dict(repo,staged=True))['stdout']

@pytest.mark.parametrize('op',OPS)
def test_describe(op):
    r = invoke(op,{'describe':'json_spec'})
    assert r['name'] == 'git_'+op
    assert r['inputSchema']['additionalProperties'] is False
    assert r['outputSchema'] and r['few_shots']
    assert 'twylt==1.0.0' in r['requirements']['content']

@pytest.mark.parametrize('path',['../outside','.git/config','/tmp/outside','sub/../../out','.GIT/config'])
def test_put_rejects_path(repos,path):
    _,a,_=repos
    p = subprocess.run([sys.executable,str(BASE/'tools/git_put/run.py'),json.dumps(virtual_input({'repo':str(a),'path':path,'content':'bad'}))],capture_output=True,text=True)
    assert p.returncode == 5

def test_overwrite_symlink_literal_and_validation(repos,tmp_path):
    _,a,_=repos
    repo={'repo':str(a)}
    invoke('put',dict(repo,path='file',content='original'))
    for data in [dict(repo,path='file',content='oops'),dict(repo,path='new',content='x',unknown=True)]:
        p=subprocess.run([sys.executable,str(BASE/'tools/git_put/run.py'),json.dumps(virtual_input(data))],capture_output=True,text=True)
        assert p.returncode != 0
    assert (a/'file').read_text() == 'original'
    outside=tmp_path/'outside'; outside.write_text('original')
    (a/'link').symlink_to(outside)
    p=subprocess.run([sys.executable,str(BASE/'tools/git_put/run.py'),json.dumps(virtual_input(dict(repo,path='link',content='oops',overwrite=True)))],capture_output=True,text=True)
    assert p.returncode == 5 and outside.read_text() == 'original'
    (a/'link').unlink()  # Strict policy rejects any repository containing symlinks.
    invoke('put',dict(repo,path='[a].txt',content='literal'))
    assert invoke('add',dict(repo,paths=['[a].txt']))['ok']
    assert native('-C',a,'diff','--cached','--name-only') == '[a].txt'

def test_divergence_and_no_force(repos):
    remote,a,b=repos
    ra={'repo':str(a)}
    invoke('put',dict(ra,path='a',content='1'))
    invoke('add',dict(ra,paths=['.']))
    invoke('commit',dict(ra,message='initial'))
    assert invoke('push',dict(ra,set_upstream=True))['ok']
    invoke('clone',{'url':str(remote),'destination':str(b)})
    native('-C',b,'config','user.name','Test'); native('-C',b,'config','user.email','test@example.invalid')
    for directory in [a,b]:
        r={'repo':str(directory)}
        invoke('put',dict(r,path=directory.name,content='divergent',overwrite=True))
        invoke('add',dict(r,paths=['.']))
        invoke('commit',dict(r,message='change '+directory.name))
    assert invoke('push',ra)['ok']
    old=native('-C',b,'rev-parse','HEAD')
    assert not invoke('pull',{'repo':str(b)})['ok']
    assert native('-C',b,'rev-parse','HEAD') == old
    assert not invoke('push',{'repo':str(b)})['ok']

def test_timeout(monkeypatch):
    spec=importlib.util.spec_from_file_location('git_diff_tool',BASE/'tools/git_diff/tool.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    def fail(*a,**kw): raise subprocess.TimeoutExpired('git',1)
    monkeypatch.setattr(module.subprocess,'run',fail)
    result=module.git(['diff'],timeout=1)
    assert result.timed_out and not result.ok and result.returncode == 124

def test_status_states_and_filters(repos):
    _, a, _ = repos
    repo = {'repo': str(a)}
    # Initial repository without commits is valid for status.
    status = invoke('status', repo)
    assert status['ok'] and status['stdout'].startswith('## ')
    invoke('put', dict(repo, path='new.txt', content='new\n'))
    invoke('put', dict(repo, path='sub/два.txt', content='unicode\n'))
    assert '?? new.txt' in invoke('status', repo)['stdout']
    assert '?? sub/два.txt' in invoke('status', dict(repo, untracked='all'))['stdout']
    assert '??' not in invoke('status', dict(repo, untracked='no'))['stdout']
    filtered = invoke('status', dict(repo, paths=['new.txt']))['stdout']
    assert 'new.txt' in filtered and 'sub/' not in filtered
    invoke('add', dict(repo, paths=['new.txt']))
    assert 'A  new.txt' in invoke('status', repo)['stdout']
    invoke('commit', dict(repo, message='Initial'))
    clean = invoke('status', dict(repo, untracked='no'))['stdout'].splitlines()
    assert len(clean) == 1 and clean[0].startswith('## main')
    invoke('put', dict(repo, path='new.txt', content='changed\n', overwrite=True))
    assert ' M new.txt' in invoke('status', repo)['stdout']
    invoke('add', dict(repo, paths=['new.txt']))
    assert 'M  new.txt' in invoke('status', repo)['stdout']
    (a/'new.txt').unlink()
    assert 'MD new.txt' in invoke('status', repo)['stdout']


def test_log_limit_skip_revision_paths_and_messages(repos):
    _, a, _ = repos
    repo = {'repo': str(a)}
    assert not invoke('log', repo)['ok']  # No HEAD yet; diagnostic is retained.
    hashes = []
    for i in range(3):
        invoke('put', dict(repo, path=f'{i}.txt', content=str(i)))
        invoke('add', dict(repo, paths=['.']))
        assert invoke('commit', dict(repo, message=f'Commit {i}\n\nBody {i}'))['ok']
        hashes.append(native('-C', a, 'rev-parse', 'HEAD'))
    full = invoke('log', repo)
    assert full['ok'] and 'Author:' in full['stdout'] and 'Body 2' in full['stdout']
    assert 'AuthorDate:' in full['stdout']
    assert invoke('log', dict(repo, oneline=True, limit=1))['stdout'].splitlines() == [hashes[2] + ' Commit 2']
    assert invoke('log', dict(repo, oneline=True, skip=1, limit=1))['stdout'].splitlines() == [hashes[1] + ' Commit 1']
    assert invoke('log', dict(repo, oneline=True, revision='HEAD~1', limit=1))['stdout'].startswith(hashes[1])
    by_path = invoke('log', dict(repo, paths=['0.txt'], oneline=True))
    assert by_path['stdout'].splitlines() == [hashes[0] + ' Commit 0']
    assert invoke('log', dict(repo, paths=['absent']))['stdout'] == ''
    assert not invoke('log', dict(repo, revision='missing-branch'))['ok']
    assert invoke('log', dict(repo, skip=10))['stdout'] == ''


@pytest.mark.parametrize('op,extra', [
    ('status', {'untracked': 'invalid'}), ('status', {'paths': ['../outside']}),
    ('log', {'limit': 0}), ('log', {'limit': 1001}), ('log', {'skip': -1}),
    ('log', {'revision': '--all'}), ('log', {'paths': ['.git/config']}),
])
def test_new_tools_reject_invalid_arguments(repos, op, extra):
    _, a, _ = repos
    data = {'repo': str(a), **extra}
    p = subprocess.run([sys.executable, str(BASE/'tools'/('git_'+op)/'run.py'), json.dumps(virtual_input(data))], capture_output=True, text=True)
    assert p.returncode in {2, 5}
