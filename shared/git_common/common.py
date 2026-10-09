from __future__ import annotations
from pathlib import Path
import os
import subprocess
from pydantic import BaseModel, ConfigDict, Field
from twylt.guardrails import workspace, check_network
import re
from urllib.parse import urlsplit

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Result(Model):
    ok: bool = Field(description='Whether the operation succeeded; always inspect this field.')
    returncode: int = Field(description='Git exit status; 124 for timeout.')
    stdout: str = Field(default='', description='Git standard output, or diff text.')
    stderr: str = Field(default='', description='Git diagnostics.')
    timed_out: bool = False
    paths: list[str] = Field(default_factory=list, description='Files written by put.')

class Common(Model):
    timeout: int = Field(default=120, ge=1, le=3600, description='Maximum Git runtime in seconds.')

class Repo(Common):
    repo: str = Field(min_length=1, description='Virtual path to a working-copy root inside TWYLT_WORKSPACE_ROOT.')

def atom(value):
    if not value or value.startswith('-') or '\x00' in value or ('\n' in value) or ('\r' in value):
        raise ValueError('Invalid remote, branch or revision argument')
    return value

def git(args, cwd=None, timeout=120):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('GIT_') and key not in {'GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSH_VARIANT'}:
            env.pop(key)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL='https:ssh:file', GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_EDITOR='true', GIT_MERGE_AUTOEDIT='no', GIT_LITERAL_PATHSPECS='1')
    try:
        p = subprocess.run(['git', '--no-pager', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false', '-c', 'submodule.recurse=false', '-c', 'fetch.recurseSubmodules=false', '-c', 'commit.gpgSign=false', *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, encoding='utf-8', errors='replace')
        return Result(ok=p.returncode == 0, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired:
        return Result(ok=False, returncode=124, timed_out=True, stderr='Git timed out; inspect repository state before retrying a mutation.')

def root(data):
    path = workspace().resolve(data.repo)
    validate_repository(path, data.timeout)
    r = git(['rev-parse', '--show-toplevel'], path, data.timeout)
    if not r.ok or Path(r.stdout.strip()).resolve() != path:
        raise ValueError('repo must be the root of a non-bare Git working copy')
    return path

def safe_path(base, name):
    if not name or name.startswith('/'):
        workspace().deny('invalid_repository_relative_path', name)
    if any((x.lower() == '.git' for x in name.split('/'))):
        workspace().deny('git_metadata_path_forbidden', name)
    return workspace().resolve(name, base=base)

_SAFE_CONFIG = re.compile('^(?:core\\.(?:repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|eol|safecrlf|quotepath|compression|packedgitlimit|packedgitwindowsize|bigfilethreshold)|user\\.(?:name|email)|extensions\\.objectformat|remote\\..+\\.(?:url|pushurl|fetch|push|tagopt|prune|mirror)|branch\\..+\\.(?:remote|pushremote|merge|rebase|description)|pull\\.(?:rebase|ff)|push\\.(?:default|autosetupremote)|fetch\\.prune|init\\.defaultbranch)$', re.I)

def local_or_network(value, virtual=False):
    ws = workspace()
    if not value or any((c in value for c in '\x00\n\r')) or value.startswith('-'):
        ws.deny('git_remote_forbidden')
    if value.startswith(('https://', 'ssh://')):
        parsed = urlsplit(value)
        if not parsed.hostname:
            ws.deny('git_remote_forbidden')
        return value
    if re.match('^(?:[^/@:]+@)?[^/@:]+:.+', value) and (not re.match('^[A-Za-z]:', value)) and ('::' not in value):
        return value
    if '://' in value or '::' in value:
        ws.deny('git_remote_forbidden')
    if virtual:
        path = ws.resolve(value)
    else:
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts:
            ws.deny('git_local_remote_outside_workspace')
        if not ws.contains(path):
            ws.deny('git_local_remote_outside_workspace')
        ws.inspect(path)
    return str(path)

def validate_repository(path, timeout=120, bare_ok=False, seen=None):
    ws = workspace()
    ws.tree(path)
    dotgit = path / '.git'
    if dotgit.is_file():
        ws.deny('git_indirect_worktree_forbidden', ws.virtual(dotgit))
    storage = dotgit if dotgit.is_dir() else path if bare_ok else None
    if storage is None or not (storage / 'config').is_file():
        raise ValueError('Expected a Git working copy (linked worktrees are not supported)')
    for rel in ['commondir', 'objects/info/alternates', 'objects/info/http-alternates']:
        if (storage / rel).exists():
            ws.deny('git_storage_redirection_forbidden')
    r = git(['config', '--no-includes', '--null', '--file', str(storage / 'config'), '--list'], timeout=timeout)
    if not r.ok:
        raise ValueError('Invalid repository configuration')
    config = {}
    for item in r.stdout.split('\x00'):
        if not item:
            continue
        key, _, value = item.partition('\n')
        if not _SAFE_CONFIG.fullmatch(key):
            ws.deny('git_config_forbidden')
        config.setdefault(key, []).append(value)
    seen = set() if seen is None else seen
    seen.add(path)
    names = {k[len('remote.'):].rsplit('.', 1)[0] for k in config if k.startswith('remote.')}
    for key, values in config.items():
        if key.startswith('remote.') and key.endswith(('.url', '.pushurl')):
            for value in values:
                result = local_or_network(value)
                if Path(result).is_absolute():
                    other = Path(result)
                    if other not in seen and other.exists():
                        validate_repository(other, timeout, bare_ok=True, seen=seen)
        if key.startswith('branch.') and key.endswith(('.remote', '.pushremote')):
            if any((v != '.' and v not in names for v in values)):
                ws.deny('git_remote_forbidden')
    return config

def configured_remote(path, name, timeout=120):
    atom(name)
    config = validate_repository(path, timeout)
    if name != '.' and 'remote.' + name + '.url' not in config:
        workspace().deny('git_remote_not_configured')
    for value in config.get('remote.' + name + '.url', []) + config.get('remote.' + name + '.pushurl', []):
        if not Path(local_or_network(value)).is_absolute():
            check_network(workspace().tool)
    return name

def check_tree(path, revision, timeout):
    r = git(['ls-tree', '-r', '-z', revision], path, timeout)
    if not r.ok:
        return r
    if any((record.startswith(b'120000 ') for record in r.stdout.encode('utf-8').split(b'\x00'))):
        workspace().deny('git_symlink_tree_forbidden')
    return Result(ok=True, returncode=0)
