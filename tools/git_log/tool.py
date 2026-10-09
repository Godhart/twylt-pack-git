from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace
from git_common.common import Repo, Result, atom, git, root, safe_path

class Input(Repo):
    limit: int = Field(default=20, ge=1, le=1000, description='Maximum number of commits returned.')
    skip: int = Field(default=0, ge=0, description='Number of matching commits to skip for pagination.')
    revision: str | None = Field(default=None, description='Single starting revision, e.g. HEAD, main or a commit hash; defaults to HEAD.')
    paths: list[str] = Field(default_factory=list, description='Optional literal relative paths whose history is shown.')
    oneline: bool = Field(default=False, description='Return full commit hash and subject only; otherwise full author/committer metadata and message.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_log'
    version = '0.4.0'
    description = 'Show recent commits with bounded output; optionally filter by revision and paths.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'limit': 10, 'oneline': True}, 'output': {'ok': True, 'returncode': 0, 'stdout': '0123456789abcdef0123456789abcdef01234567 Add hello example\n', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_log.input'
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
        resolved = git(['rev-parse', '--verify', '--end-of-options', atom(data.revision or 'HEAD') + '^{commit}'], base, data.timeout)
        if not resolved.ok:
            return resolved
        args = ['log', '--no-color', '--no-decorate', '--no-show-signature', '--no-patch', '--date=iso-strict', '--max-count=' + str(data.limit), '--skip=' + str(data.skip)]
        args.append('--format=%H %s' if data.oneline else '--format=fuller')
        return git(args + [resolved.stdout.strip(), '--', *data.paths], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
