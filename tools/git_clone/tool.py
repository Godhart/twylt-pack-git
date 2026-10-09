from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from pathlib import Path
from pydantic import Field
from twylt import Tool, Requirements
from twylt.guardrails import Workspace, workspace, check_network
from git_common.common import Common, Result, atom, check_tree, git, local_or_network, validate_repository

def scoped_clone(data):
    ws = workspace()
    destination = ws.resolve(data.destination)
    ws.protect_root(destination)
    source = local_or_network(data.url, virtual=True)
    if not Path(source).is_absolute():
        check_network('git_clone')
    if Path(source).is_absolute():
        validate_repository(Path(source), data.timeout, bare_ok=True)
    args = ['clone', '--no-checkout', '--no-local']
    if data.branch:
        args += ['--branch', atom(data.branch)]
    if data.depth:
        args += ['--depth', str(data.depth)]
    r = git(args + ['--', source, str(destination)], timeout=data.timeout)
    if not r.ok:
        return r
    validate_repository(destination, data.timeout)
    head = git(['rev-parse', '--verify', 'HEAD'], destination, data.timeout)
    if head.ok:
        checked = check_tree(destination, head.stdout.strip(), data.timeout)
        if not checked.ok:
            return checked
        checked = git(['reset', '--hard', head.stdout.strip()], destination, data.timeout)
        if not checked.ok:
            return checked
    return r

class Input(Common):
    url: str = Field(min_length=1, description='HTTPS/SSH URL or virtual local repository path inside workspace.')
    destination: str = Field(min_length=1, description='Virtual destination path inside configured workspace.')
    branch: str | None = Field(default=None, description='Optional branch to check out.')
    depth: int | None = Field(default=None, ge=1, description='Optional shallow clone depth.')

class GitTool(Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_clone'
    version = '0.4.0'
    description = 'Clone a Git repository into a new working copy.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.1,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'url': 'https://example.com/team/project.git', 'destination': '/work/project'}, 'output': {'ok': True, 'returncode': 0, 'stdout': '', 'stderr': '', 'timed_out': False, 'paths': []}}]
    input_schema_name = 'git_clone.input'
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
        return scoped_clone(data)
TOOL = GitTool
if __name__ == '__main__':
    GitTool.run()
