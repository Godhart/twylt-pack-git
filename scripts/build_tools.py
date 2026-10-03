from pathlib import Path
import json
BASE = Path(__file__).resolve().parents[1]
POLICY = (BASE/'src/workspace.py').read_text()
GIT_POLICY = (BASE/'src/git_policy.py').read_text()
COMMON = (BASE/'src/common.py').read_text().replace('from workspace import Workspace, WorkspaceDenied, WorkspaceTransport, workspace', POLICY).replace('from git_policy import validate_repository, configured_remote, scoped_clone, scoped_pull', GIT_POLICY)
SPECS = {
'clone': ('Clone a Git repository into a new working copy.', '''class Input(Common):
    url: str = Field(min_length=1, description='HTTPS/SSH URL or virtual local repository path inside workspace.')
    destination: str = Field(min_length=1, description='Virtual destination path inside configured workspace.')
    branch: str | None = Field(default=None, description='Optional branch to check out.')
    depth: int | None = Field(default=None, ge=1, description='Optional shallow clone depth.')
''', '''return scoped_clone(data)''', {'url':'https://example.com/team/project.git','destination':'/work/project'}),
'fetch': ('Fetch remote refs without changing working files.', '''class Input(Repo):
    remote: str = Field(default='origin', description='Configured remote name.')
    prune: bool = Field(default=False, description='Remove stale remote-tracking refs.')
    tags: bool = Field(default=False, description='Fetch all tags.')
''', '''args = ['fetch']
        if data.prune: args.append('--prune')
        if data.tags: args.append('--tags')
        base = root(data)
        configured_remote(base, data.remote, data.timeout)
        return git(args + [atom(data.remote)], base, data.timeout)''', {'repo':'/work/project'}),
'pull': ('Pull with fast-forward only; refuse divergent history.', '''class Input(Repo):
    remote: str | None = Field(default=None, description='Remote; omit with branch to use configured upstream.')
    branch: str | None = Field(default=None, description='Remote branch; requires remote.')
    @model_validator(mode='after')
    def pair(self):
        if (self.remote is None) != (self.branch is None):
            raise ValueError('Supply remote and branch together')
        return self
''', '''return scoped_pull(data)''', {'repo':'/work/project'}),
'put': ('Write one UTF-8 text file in a working copy; does not stage it.', '''class Input(Repo):
    path: str = Field(min_length=1, description='Relative file path within repo.')
    content: str = Field(description='Complete UTF-8 file content; newlines are preserved.')
    overwrite: bool = Field(default=False, description='Explicitly allow replacement of an existing file.')
''', '''base = root(data)
        target = safe_path(base, data.path)
        if target == base or (target.exists() and not target.is_file()):
            raise ValueError('Target must be a regular file')
        if target.exists() and not data.overwrite:
            raise ValueError('File exists; set overwrite=true to replace it')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not data.overwrite:
            with target.open('x', encoding='utf-8', newline='') as f: f.write(data.content)
        else:
            mode = target.stat().st_mode if target.exists() else None
            fd, temp = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f: f.write(data.content)
                if mode is not None: os.chmod(temp, mode)
                os.replace(temp, target)
            finally:
                if os.path.exists(temp): os.unlink(temp)
        return Result(ok=True, returncode=0, paths=[data.path])''', {'repo':'/work/project','path':'hello.py','content':'print("hello")\n'}),
'add': ('Stage explicitly selected paths, including modifications and deletions.', '''class Input(Repo):
    paths: list[str] = Field(min_length=1, description='Literal relative paths; use ["."] to stage everything.')
''', '''base = root(data)
        for path in data.paths: safe_path(base, path)
        return git(['add', '--all', '--', *data.paths], base, data.timeout)''', {'repo':'/work/project','paths':['hello.py']}),
'commit': ('Commit the current index with a message; does not implicitly add files.', '''class Input(Repo):
    message: str = Field(min_length=1, description='Commit message; configured Git author identity is used.')
''', '''if not data.message.strip(): raise ValueError('Commit message must not be blank')
        return git(['commit', '-m', data.message], root(data), data.timeout)''', {'repo':'/work/project','message':'Add hello example'}),
'push': ('Push the current branch without force, tags or mirror behavior.', '''class Input(Repo):
    remote: str = Field(default='origin', description='Configured remote name.')
    branch: str | None = Field(default=None, description='Destination branch; defaults to current branch.')
    set_upstream: bool = Field(default=False, description='Record tracking upstream for current branch.')
''', '''base = root(data)
        configured_remote(base, data.remote, data.timeout)
        current = git(['symbolic-ref', '--quiet', '--short', 'HEAD'], base, data.timeout)
        if not current.ok: return current
        branch = atom(data.branch or current.stdout.strip())
        checked = git(['check-ref-format', 'refs/heads/' + branch], base, data.timeout)
        if not checked.ok: return checked
        args = ['-c', 'remote.' + atom(data.remote) + '.mirror=false', 'push', '--no-force', '--no-follow-tags']
        if data.set_upstream: args.append('--set-upstream')
        return git(args + [data.remote, 'HEAD:refs/heads/' + branch], base, data.timeout)''', {'repo':'/work/project','set_upstream':True}),
'diff': ('Show unstaged, staged or revision differences; untracked files are not included.', '''class Input(Repo):
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
''', '''base = root(data)
        args = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-exit-code', '--unified=' + str(data.context)]
        if data.staged: args.append('--cached')
        for rev in [data.base, data.target]:
            if rev is not None:
                resolved = git(['rev-parse', '--verify', '--end-of-options', atom(rev) + '^{commit}'], base, data.timeout)
                if not resolved.ok: return resolved
                args.append(resolved.stdout.strip())
        for path in data.paths: safe_path(base, path)
        return git(args + ['--', *data.paths], base, data.timeout)''', {'repo':'/work/project','staged':True}),
'status': ('Show working-copy and index status in Git porcelain v1 format, with branch information.', '''class Input(Repo):
    untracked: Literal['no', 'normal', 'all'] = Field(default='normal', description='Show no untracked paths, collapsed directories, or all files.')
    paths: list[str] = Field(default_factory=list, description='Optional literal relative path filter.')
''', '''base = root(data)
        for path in data.paths: safe_path(base, path)
        return git(['-c', 'core.quotepath=false', '--no-optional-locks', 'status', '--porcelain=v1', '--branch', '--untracked-files=' + data.untracked, '--', *data.paths], base, data.timeout)''', {'repo':'/work/project','untracked':'all'}),
'log': ('Show recent commits with bounded output; optionally filter by revision and paths.', '''class Input(Repo):
    limit: int = Field(default=20, ge=1, le=1000, description='Maximum number of commits returned.')
    skip: int = Field(default=0, ge=0, description='Number of matching commits to skip for pagination.')
    revision: str | None = Field(default=None, description='Single starting revision, e.g. HEAD, main or a commit hash; defaults to HEAD.')
    paths: list[str] = Field(default_factory=list, description='Optional literal relative paths whose history is shown.')
    oneline: bool = Field(default=False, description='Return full commit hash and subject only; otherwise full author/committer metadata and message.')
''', '''base = root(data)
        for path in data.paths: safe_path(base, path)
        resolved = git(['rev-parse', '--verify', '--end-of-options', atom(data.revision or 'HEAD') + '^{commit}'], base, data.timeout)
        if not resolved.ok: return resolved
        args = ['log', '--no-color', '--no-decorate', '--no-show-signature', '--no-patch', '--date=iso-strict', '--max-count=' + str(data.limit), '--skip=' + str(data.skip)]
        args.append('--format=%H %s' if data.oneline else '--format=fuller')
        return git(args + [resolved.stdout.strip(), '--', *data.paths], base, data.timeout)''', {'repo':'/work/project','limit':10,'oneline':True}),
}
for op, (description, model, body, example) in SPECS.items():
    directory = BASE/'tools'/('git_'+op)
    directory.mkdir(parents=True, exist_ok=True)
    output = {'ok':True,'returncode':0,'stdout':'','stderr':'','timed_out':False,'paths':[example['path']] if op == 'put' else []}
    if op == 'status': output['stdout'] = '## main\n?? hello.py\n'
    if op == 'log': output['stdout'] = '0123456789abcdef0123456789abcdef01234567 Add hello example\n'
    code = COMMON + '\n' + model + f'''\nclass GitTool(WorkspaceTransport, Tool[Input, Result]):
    input_model = Input
    output_model = Result
    name = 'git_{op}'
    version = '0.3.0'
    description = {description!r}
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt==1.0.0\\npydantic>=2,<3\\n')
    few_shots = {[{'input':example,'output':output}]!r}
    input_schema_name = 'git_{op}.input'
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
        {body}

if __name__ == '__main__':
    GitTool.run()
'''
    (directory/'tool.py').write_text(code)
    (directory/'run.py').write_text('from pathlib import Path\nfrom twylt.bootstrap import run_tool_file\n\nif __name__ == "__main__":\n    run_tool_file(Path(__file__).with_name("tool.py"))\n')
    (directory/'example.json').write_text(json.dumps(example, ensure_ascii=False, indent=2)+'\n')
