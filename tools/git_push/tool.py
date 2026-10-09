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
    branch: str | None = Field(default=None, description='Destination branch; defaults to current branch.')
    set_upstream: bool = Field(default=False, description='Record tracking upstream for current branch.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_push'
    version = '0.4.0'
    description = 'Push the current branch without force, tags or mirror behavior.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'repo': '/work/project', 'set_upstream': True}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_push.input'
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
        configured_remote(base, data.remote, data.timeout)
        current = git(['symbolic-ref', '--quiet', '--short', 'HEAD'], base, data.timeout)
        if not current.ok:
            return current
        branch = atom(data.branch or current.stdout.strip())
        checked = git(['check-ref-format', 'refs/heads/' + branch], base, data.timeout)
        if not checked.ok:
            return checked
        args = ['-c', 'remote.' + atom(data.remote) + '.mirror=false', 'push', '--no-force', '--no-follow-tags']
        if data.set_upstream:
            args.append('--set-upstream')
        return git(args + [data.remote, 'HEAD:refs/heads/' + branch], base, data.timeout)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
