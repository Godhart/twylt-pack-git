from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, atom, configured_remote, git, root

class Input(Repo):
    remote: str = Field(default='origin', description='Configured remote name.')
    prune: bool = Field(default=False, description='Remove stale remote-tracking refs.')
    tags: bool = Field(default=False, description='Fetch all tags.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_fetch'
    version = '0.4.0'
    description = 'Fetch remote refs without changing working files.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
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
        if data.prune:
            args.append('--prune')
        if data.tags:
            args.append('--tags')
        base = root(data)
        configured_remote(base, data.remote, data.timeout)
        return git(args + [atom(data.remote)], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
