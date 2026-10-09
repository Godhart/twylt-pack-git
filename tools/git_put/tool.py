from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
import os
import tempfile
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, root, safe_path

class Input(Repo):
    path: str = Field(min_length=1, description='Relative file path within repo.')
    content: str = Field(description='Complete UTF-8 file content; newlines are preserved.')
    overwrite: bool = Field(default=False, description='Explicitly allow replacement of an existing file.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_put'
    version = '0.4.0'
    description = 'Write one UTF-8 text file in a working copy; does not stage it.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'path': 'hello.py', 'content': 'print("hello")\n'}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': ['hello.py']}}]
    input_schema_name = 'git_put.input'
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
        target = safe_path(base, data.path)
        if target == base or (target.exists() and (not target.is_file())):
            raise ValueError('Target must be a regular file')
        if target.exists() and (not data.overwrite):
            raise ValueError('File exists; set overwrite=true to replace it')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not data.overwrite:
            with target.open('x', encoding='utf-8', newline='') as f:
                f.write(data.content)
        else:
            mode = target.stat().st_mode if target.exists() else None
            fd, temp = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                    f.write(data.content)
                if mode is not None:
                    os.chmod(temp, mode)
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return Result(ok=True, returncode=0, paths=[data.path])
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
