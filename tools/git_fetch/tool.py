"""Shared source, embedded by scripts/build_tools.py. Do not edit generated copies."""
from pathlib import Path
import os
import subprocess
import tempfile
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from twylt import Tool, Requirements
"""Shared workspace policy 1.0.0. Embedded verbatim in standalone tools.
Explicit path confinement, not an OS sandbox. Environment is trusted configuration.
"""
import contextvars
import datetime as _datetime
import json as _json
import os as _os
from pathlib import Path as _Path
import stat as _stat
import sys as _sys
import uuid as _uuid

_POLICY = contextvars.ContextVar('twylt_workspace', default=None)

class WorkspaceDenied(ValueError):
    """A policy denial, already recorded in the incident sink."""
    def __init__(self, code, incident_id):
        self.code = code
        self.incident_id = incident_id
        super().__init__(f'{code}: access denied (incident {incident_id})')

class Workspace:
    def __init__(self, tool='unknown'):
        self.tool = tool
        self.log_path = None
        self.root = None
        value = _os.environ.get('TWYLT_WORKSPACE_ROOT', '')
        if not value or not _Path(value).is_absolute():
            self.deny('workspace_not_configured')
        candidate = _Path(_os.path.abspath(value))
        # The root and all of its ancestors must be real directories.
        try:
            for part in [*reversed(candidate.parents), candidate]:
                st = part.lstat()
                if self._link(st) or not _stat.S_ISDIR(st.st_mode):
                    self.deny('invalid_workspace_root')
            if candidate.parent == candidate:
                self.deny('filesystem_root_forbidden')
        except OSError:
            self.deny('invalid_workspace_root')
        self.root = candidate
        configured_log = _os.environ.get('TWYLT_INCIDENT_LOG', '')
        if configured_log:
            p = _Path(configured_log)
            if not p.is_absolute(): self.deny('invalid_incident_log')
            p = _Path(_os.path.abspath(p))
            if self.contains(p): self.deny('incident_log_inside_workspace')
            try:
                for parent in [*reversed(p.parent.parents), p.parent]:
                    st = parent.lstat()
                    if self._link(st) or not _stat.S_ISDIR(st.st_mode):
                        self.deny('invalid_incident_log')
                self.log_path = p
                fd = self._open_log()
                _os.close(fd)
            except WorkspaceDenied:
                raise
            except (OSError, ValueError):
                self.log_path = None
                self.deny('incident_log_unavailable')

    @staticmethod
    def _link(st):
        # Includes Windows junctions/reparse points even on Python without is_junction().
        return _stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & 0x400)

    def contains(self, path):
        return self.root is not None and (path == self.root or self.root in path.parents)

    def _open_log(self):
        p = self.log_path
        if p.exists() or p.is_symlink():
            st = p.lstat()
            if self._link(st) or not _stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError('unsafe audit sink')
        flags = _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT | getattr(_os, 'O_NOFOLLOW', 0) | getattr(_os, 'O_CLOEXEC', 0) | getattr(_os, 'O_NONBLOCK', 0)
        fd = _os.open(p, flags, 0o600)
        try:
            st = _os.fstat(fd)
            if not _stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError('unsafe audit sink')
        except BaseException:
            _os.close(fd)
            raise
        return fd

    def deny(self, code, requested=None):
        identifier = str(_uuid.uuid4())
        event = {'event': 'workspace_incident', 'schema_version': '1.0',
                 'timestamp': _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                 'incident_id': identifier, 'tool': self.tool, 'pid': _os.getpid(),
                 'action': 'deny', 'code': code}
        if requested is not None:
            # Only explicit path values, never file contents or remote URLs/credentials.
            event['requested_path'] = str(requested)[:1024]
        payload = (_json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
        try:
            if self.log_path is None:
                _sys.stderr.write(payload.decode('utf-8')); _sys.stderr.flush()
            else:
                fd = self._open_log()
                try:
                    if _os.write(fd, payload) != len(payload): raise OSError('short audit write')
                    _os.fsync(fd)
                finally: _os.close(fd)
        except (OSError, ValueError):
            event['original_code'] = code
            event['code'] = code = 'incident_log_unavailable'
            _sys.stderr.write(_json.dumps(event, ensure_ascii=True) + '\n'); _sys.stderr.flush()
        raise WorkspaceDenied(code, identifier)

    def inspect(self, path, allow_leaf_link=False):
        """Check physical path components without following any link."""
        path = _Path(path)
        if not self.contains(path): self.deny('path_outside_workspace')
        current = self.root
        parts = path.relative_to(self.root).parts
        for i, part in enumerate(parts):
            current = current / part
            try: st = current.lstat()
            except FileNotFoundError: break
            if self._link(st):
                if allow_leaf_link and i == len(parts)-1: return path
                self.deny('symlink_forbidden', self.virtual_unchecked(path))
            if _stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                self.deny('hardlink_forbidden', self.virtual_unchecked(path))
            if not (_stat.S_ISREG(st.st_mode) or _stat.S_ISDIR(st.st_mode)):
                self.deny('special_file_forbidden', self.virtual_unchecked(path))
            if st.st_dev != self.root.stat().st_dev:
                self.deny('mount_boundary_forbidden', self.virtual_unchecked(path))
        return path

    def resolve(self, value, base=None):
        """POSIX virtual / is root; relative paths are root-based unless base is explicit."""
        if not isinstance(value, str) or not value or '\x00' in value:
            self.deny('invalid_path')
        if '\\' in value or ':' in value or value.startswith('//') or value.startswith('~'):
            self.deny('invalid_path_syntax', value)
        parts = value.split('/')
        if '..' in parts: self.deny('path_outside_workspace', value)
        if _os.name == 'nt':
            reserved = {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}
            if any(p.endswith((' ', '.')) or p.split('.')[0].upper() in reserved for p in parts if p not in {'', '.'}):
                self.deny('invalid_path_syntax', value)
        start = self.root if value.startswith('/') or base is None else base
        path = start.joinpath(*(p for p in parts if p not in {'', '.'}))
        return self.inspect(path)

    def virtual_unchecked(self, path):
        relative = _Path(path).relative_to(self.root).as_posix()
        return '/' if relative == '.' else '/' + relative

    def virtual(self, path):
        if not self.contains(_Path(path)): self.deny('path_outside_workspace')
        return self.virtual_unchecked(path)

    def protect_root(self, path):
        if path == self.root: self.deny('workspace_root_mutation_forbidden', '/')

    def tree(self, path):
        """Preflight every descendant before a recursive mutation."""
        self.inspect(path)
        if not path.is_dir(): return
        stack = [path]
        while stack:
            parent = stack.pop()
            with _os.scandir(parent) as children:
                for child in children:
                    p = self.inspect(_Path(child.path))
                    if p.is_dir(): stack.append(p)

    def redact(self, value):
        if self.root is None: return str(value)
        return str(value).replace(str(self.root) + _os.sep, '/').replace(str(self.root), '/')

    def __enter__(self):
        self._token = _POLICY.set(self)
        return self

    def __exit__(self, typ, exc, tb):
        _POLICY.reset(self._token)
        # Remove host workspace prefixes from errors returned by business code.
        if exc is not None and not isinstance(exc, WorkspaceDenied):
            if isinstance(exc, OSError):
                if exc.filename: exc.filename = self.redact(exc.filename)
                if exc.filename2: exc.filename2 = self.redact(exc.filename2)
            exc.args = tuple(self.redact(a) if isinstance(a, str) else a for a in exc.args)
        return False

def workspace():
    active = _POLICY.get()
    return active if active is not None else Workspace()

class WorkspaceTransport:
    """Guard TWYLT 1.0.0's implicit input.json/output.json before its file I/O."""
    @classmethod
    def _transport_payload(cls):
        payload, source = super()._transport_payload()
        if source is None and not _os.environ.get('INPUT_DESCRIBE', ''):
            with Workspace(cls.name) as ws:
                cwd = _Path.cwd()
                if not ws.contains(cwd): ws.deny('transport_cwd_outside_workspace')
                ws.inspect(cwd)
                for attribute in ['input_path', 'output_path']:
                    path = _Path(getattr(cls, attribute))
                    full = path if path.is_absolute() else cwd/path
                    setattr(cls, attribute, ws.inspect(full))
        return payload, source

    @classmethod
    def _write_output(cls, value):
        with Workspace(cls.name) as ws:
            ws.inspect(_Path(cls.output_path))
            return super()._write_output(value)


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
    if not value or value.startswith('-') or '\x00' in value or '\n' in value or '\r' in value:
        raise ValueError('Invalid remote, branch or revision argument')
    return value

def git(args, cwd=None, timeout=120):
    env = os.environ.copy()
    # Do not inherit a caller-selected index/worktree or injected Git options.
    for key in list(env):
        if key.startswith('GIT_') and key not in {'GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSH_VARIANT'}:
            env.pop(key)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL='https:ssh:file', GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_EDITOR='true', GIT_MERGE_AUTOEDIT='no', GIT_LITERAL_PATHSPECS='1')
    try:
        p = subprocess.run(['git', '--no-pager', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false', '-c', 'submodule.recurse=false', '-c', 'fetch.recurseSubmodules=false', '-c', 'commit.gpgSign=false', *args], cwd=cwd, env=env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, encoding='utf-8', errors='replace')
        return Result(ok=p.returncode == 0, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired:
        return Result(ok=False, returncode=124, timed_out=True,
                      stderr='Git timed out; inspect repository state before retrying a mutation.')

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
    if any(x.lower() == '.git' for x in name.split('/')):
        workspace().deny('git_metadata_path_forbidden', name)
    return workspace().resolve(name, base=base)

"""Conservative checks for Git's implicit local paths and execution configuration."""
import re
from urllib.parse import urlsplit

_SAFE_CONFIG = re.compile(
    r'^(?:core\.(?:repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|eol|safecrlf|quotepath|compression|packedgitlimit|packedgitwindowsize|bigfilethreshold)|'
    r'user\.(?:name|email)|extensions\.objectformat|'
    r'remote\..+\.(?:url|pushurl|fetch|push|tagopt|prune|mirror)|'
    r'branch\..+\.(?:remote|pushremote|merge|rebase|description)|'
    r'pull\.(?:rebase|ff)|push\.(?:default|autosetupremote)|fetch\.prune|'
    r'init\.defaultbranch)$', re.I)

def local_or_network(value, virtual=False):
    ws = workspace()
    if not value or any(c in value for c in '\x00\n\r') or value.startswith('-'):
        ws.deny('git_remote_forbidden')
    if value.startswith(('https://', 'ssh://')):
        parsed = urlsplit(value)
        if not parsed.hostname: ws.deny('git_remote_forbidden')
        return value
    if re.match(r'^(?:[^/@:]+@)?[^/@:]+:.+', value) and not re.match(r'^[A-Za-z]:', value) and '::' not in value:
        return value  # SSH scp-style address, handled by trusted SSH configuration.
    if '://' in value or '::' in value:
        ws.deny('git_remote_forbidden')
    if virtual:
        path = ws.resolve(value)
    else:
        # Stored native Git URLs must be physical absolute paths inside the root.
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts: ws.deny('git_local_remote_outside_workspace')
        if not ws.contains(path): ws.deny('git_local_remote_outside_workspace')
        ws.inspect(path)
    return str(path)

def validate_repository(path, timeout=120, bare_ok=False, seen=None):
    ws = workspace()
    ws.tree(path)
    dotgit = path / '.git'
    if dotgit.is_file(): ws.deny('git_indirect_worktree_forbidden', ws.virtual(dotgit))
    storage = dotgit if dotgit.is_dir() else path if bare_ok else None
    if storage is None or not (storage / 'config').is_file():
        raise ValueError('Expected a Git working copy (linked worktrees are not supported)')
    for rel in ['commondir', 'objects/info/alternates', 'objects/info/http-alternates']:
        if (storage / rel).exists(): ws.deny('git_storage_redirection_forbidden')
    r = git(['config', '--no-includes', '--null', '--file', str(storage/'config'), '--list'], timeout=timeout)
    if not r.ok: raise ValueError('Invalid repository configuration')
    config = {}
    for item in r.stdout.split('\0'):
        if not item: continue
        key, _, value = item.partition('\n')
        if not _SAFE_CONFIG.fullmatch(key): ws.deny('git_config_forbidden')
        config.setdefault(key, []).append(value)
    seen = set() if seen is None else seen
    seen.add(path)
    names = {k[len('remote.'):].rsplit('.',1)[0] for k in config if k.startswith('remote.')}
    for key, values in config.items():
        if key.startswith('remote.') and key.endswith(('.url', '.pushurl')):
            for value in values:
                result = local_or_network(value)
                if Path(result).is_absolute():
                    other = Path(result)
                    if other not in seen and other.exists():
                        validate_repository(other, timeout, bare_ok=True, seen=seen)
        if key.startswith('branch.') and key.endswith(('.remote', '.pushremote')):
            if any(v != '.' and v not in names for v in values): ws.deny('git_remote_forbidden')
    return config

def configured_remote(path, name, timeout=120):
    atom(name)
    config = validate_repository(path, timeout)
    if name != '.' and 'remote.' + name + '.url' not in config:
        workspace().deny('git_remote_not_configured')
    return name

def check_tree(path, revision, timeout):
    r = git(['ls-tree', '-r', '-z', revision], path, timeout)
    if not r.ok: return r
    if any(record.startswith(b'120000 ') for record in r.stdout.encode('utf-8').split(b'\0')):
        workspace().deny('git_symlink_tree_forbidden')
    return Result(ok=True, returncode=0)

def scoped_clone(data):
    ws = workspace()
    destination = ws.resolve(data.destination)
    ws.protect_root(destination)
    source = local_or_network(data.url, virtual=True)
    if Path(source).is_absolute(): validate_repository(Path(source), data.timeout, bare_ok=True)
    args = ['clone', '--no-checkout', '--no-local']
    if data.branch: args += ['--branch', atom(data.branch)]
    if data.depth: args += ['--depth', str(data.depth)]
    r = git(args + ['--', source, str(destination)], timeout=data.timeout)
    if not r.ok: return r
    validate_repository(destination, data.timeout)
    head = git(['rev-parse', '--verify', 'HEAD'], destination, data.timeout)
    if head.ok:
        checked = check_tree(destination, head.stdout.strip(), data.timeout)
        if not checked.ok: return checked
        checked = git(['reset', '--hard', head.stdout.strip()], destination, data.timeout)
        if not checked.ok: return checked
    return r

def scoped_pull(data):
    path = root(data)
    config = validate_repository(path, data.timeout)
    remote, branch = data.remote, data.branch
    if remote is None:
        current = git(['symbolic-ref', '--quiet', '--short', 'HEAD'], path, data.timeout)
        if not current.ok: return current
        prefix = 'branch.' + current.stdout.strip()
        remote = config.get(prefix+'.remote', [None])[-1]
        branch = config.get(prefix+'.merge', [None])[-1]
        if remote is None or branch is None:
            return Result(ok=False, returncode=1, stderr='No upstream configured; supply remote and branch.')
    configured_remote(path, remote, data.timeout)
    fetched = git(['fetch', '--no-recurse-submodules', remote, atom(branch)], path, data.timeout)
    if not fetched.ok: return fetched
    target = git(['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], path, data.timeout)
    if not target.ok: return target
    checked = check_tree(path, target.stdout.strip(), data.timeout)
    if not checked.ok: return checked
    return git(['merge', '--ff-only', '--no-autostash', '--no-edit', target.stdout.strip()], path, data.timeout)


class Input(Repo):
    remote: str = Field(default='origin', description='Configured remote name.')
    prune: bool = Field(default=False, description='Remove stale remote-tracking refs.')
    tags: bool = Field(default=False, description='Fetch all tags.')

class GitTool(WorkspaceTransport, Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_fetch'
    version = '0.3.0'
    description = 'Fetch remote refs without changing working files.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt==1.0.0\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project'}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_fetch.input'
    input_schema_version = '2.0.0'
    output_schema_name = 'git.result'
    output_schema_version = '1.0.0'
    def biz(self, data):
        with Workspace(self.name) as ws:
            result = self.execute(data)
            result.stdout = ws.redact(result.stdout)
            result.stderr = ws.redact(result.stderr)
            return result

    def execute(self, data):
        args = ['fetch']
        if data.prune: args.append('--prune')
        if data.tags: args.append('--tags')
        base = root(data)
        configured_remote(base, data.remote, data.timeout)
        return git(args + [atom(data.remote)], base, data.timeout)

if __name__ == '__main__':
    GitTool.run()
