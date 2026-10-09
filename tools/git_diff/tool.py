from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pydantic import Field, model_validator
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, atom, git, root, safe_path

class Input(Repo):
    staged: bool = Field(default=False, description='Compare index instead of working files.')
    base: str | None = Field(default=None, description='Optional base revision, e.g. HEAD.')
    target: str | None = Field(default=None, description='Optional target revision; requires base, excludes staged.')
    paths: list[str] = Field(default_factory=list, description='Optional literal relative path filter.')
    context: int = Field(default=3, ge=0, le=100, description='Lines of patch context.')

    @model_validator(mode='after')
    def combination(self):
        if self.target and (not self.base or self.staged):
            raise ValueError('target requires base and staged=false')
        return self

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_diff'
    version = '0.4.0'
    description = 'Show unstaged, staged or revision differences; untracked files are not included.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'staged': True}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_diff.input'
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
        base = root(data)
        args = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-exit-code', '--unified=' + str(data.context)]
        if data.staged:
            args.append('--cached')
        for rev in [data.base, data.target]:
            if rev is not None:
                resolved = git(['rev-parse', '--verify', '--end-of-options', atom(rev) + '^{commit}'], base, data.timeout)
                if not resolved.ok:
                    return resolved
                args.append(resolved.stdout.strip())
        for path in data.paths:
            safe_path(base, path)
        return git(args + ['--', *data.paths], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
