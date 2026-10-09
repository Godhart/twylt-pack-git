from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pydantic import Field, model_validator
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, atom, check_tree, configured_remote, git, root, validate_repository

def scoped_pull(data):
    path = root(data)
    config = validate_repository(path, data.timeout)
    remote, branch = (data.remote, data.branch)
    if remote is None:
        current = git(['symbolic-ref', '--quiet', '--short', 'HEAD'], path, data.timeout)
        if not current.ok:
            return current
        prefix = 'branch.' + current.stdout.strip()
        remote = config.get(prefix + '.remote', [None])[-1]
        branch = config.get(prefix + '.merge', [None])[-1]
        if remote is None or branch is None:
            return Result(ok=False, returncode=1, stderr='No upstream configured; supply remote and branch.')
    configured_remote(path, remote, data.timeout)
    fetched = git(['fetch', '--no-recurse-submodules', remote, atom(branch)], path, data.timeout)
    if not fetched.ok:
        return fetched
    target = git(['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], path, data.timeout)
    if not target.ok:
        return target
    checked = check_tree(path, target.stdout.strip(), data.timeout)
    if not checked.ok:
        return checked
    return git(['merge', '--ff-only', '--no-autostash', '--no-edit', target.stdout.strip()], path, data.timeout)

class Input(Repo):
    remote: str | None = Field(default=None, description='Remote; omit with branch to use configured upstream.')
    branch: str | None = Field(default=None, description='Remote branch; requires remote.')

    @model_validator(mode='after')
    def pair(self):
        if (self.remote is None) != (self.branch is None):
            raise ValueError('Supply remote and branch together')
        return self

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_pull'
    version = '0.4.0'
    description = 'Pull with fast-forward only; refuse divergent history.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project'}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_pull.input'
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
        return scoped_pull(data)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
