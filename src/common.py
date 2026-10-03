"""Shared source, embedded by scripts/build_tools.py. Do not edit generated copies."""
from pathlib import Path
import os
import subprocess
import tempfile
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from twylt import Tool, Requirements
from workspace import Workspace, WorkspaceDenied, WorkspaceTransport, workspace

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

from git_policy import validate_repository, configured_remote, scoped_clone, scoped_pull
