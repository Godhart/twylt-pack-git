from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from typing import Literal
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, git, root, safe_path

class Input(Repo):
    untracked: Literal['no', 'normal', 'all'] = Field(default='normal', description='Show no untracked paths, collapsed directories, or all files.')
    paths: list[str] = Field(default_factory=list, description='Optional literal relative path filter.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_status'
    version = '0.4.0'
    description = 'Show working-copy and index status in Git porcelain v1 format, with branch information.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'untracked': 'all'}, 'output': {'ok': True, 'returncode': 0, 'stdout': '## main\n?? hello.py\n', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_status.input'
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
        for path in data.paths:
            safe_path(base, path)
        return git(['-c', 'core.quotepath=false', '--no-optional-locks', 'status', '--porcelain=v1', '--branch', '--untracked-files=' + data.untracked, '--', *data.paths], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
