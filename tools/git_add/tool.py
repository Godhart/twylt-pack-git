from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, git, root, safe_path

class Input(Repo):
    paths: list[str] = Field(min_length=1, description='Literal relative paths; use ["."] to stage everything.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_add'
    version = '0.4.0'
    description = 'Stage explicitly selected paths, including modifications and deletions.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'paths': ['hello.py']}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_add.input'
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
        return git(['add', '--all', '--', *data.paths], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
