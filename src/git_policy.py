"""Conservative checks for Git's implicit local paths and execution configuration."""
import re
from urllib.parse import urlsplit

_SAFE_CONFIG = re.compile(
    r'^(?:core\.(?:repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|eol|safecrlf|quotepath|compression|packedgitlimit|packedgitwindowsize|bigfilethreshold)|'
    r'user\.(?:name|email)|extensions\.objectformat|'
    r'remote\..+\.(?:url|pushurl|fetch|push|tagopt|prune|mirror)|'
    r'branch\..+\.(?:remote|pushremote|merge|rebase|description)|'
    r'pull\.(?:rebase|ff)|push\.(?:default|autosetupremote)|fetch\.prune|'
    r'init\.defaultbranch)$', re.I)

def local_or_network(value, virtual=False):
    ws = workspace()
    if not value or any(c in value for c in '\x00\n\r') or value.startswith('-'):
        ws.deny('git_remote_forbidden')
    if value.startswith(('https://', 'ssh://')):
        parsed = urlsplit(value)
        if not parsed.hostname: ws.deny('git_remote_forbidden')
        return value
    if re.match(r'^(?:[^/@:]+@)?[^/@:]+:.+', value) and not re.match(r'^[A-Za-z]:', value) and '::' not in value:
        return value  # SSH scp-style address, handled by trusted SSH configuration.
    if '://' in value or '::' in value:
        ws.deny('git_remote_forbidden')
    if virtual:
        path = ws.resolve(value)
    else:
        # Stored native Git URLs must be physical absolute paths inside the root.
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts: ws.deny('git_local_remote_outside_workspace')
        if not ws.contains(path): ws.deny('git_local_remote_outside_workspace')
        ws.inspect(path)
    return str(path)

def validate_repository(path, timeout=120, bare_ok=False, seen=None):
    ws = workspace()
    ws.tree(path)
    dotgit = path / '.git'
    if dotgit.is_file(): ws.deny('git_indirect_worktree_forbidden', ws.virtual(dotgit))
    storage = dotgit if dotgit.is_dir() else path if bare_ok else None
    if storage is None or not (storage / 'config').is_file():
        raise ValueError('Expected a Git working copy (linked worktrees are not supported)')
    for rel in ['commondir', 'objects/info/alternates', 'objects/info/http-alternates']:
        if (storage / rel).exists(): ws.deny('git_storage_redirection_forbidden')
    r = git(['config', '--no-includes', '--null', '--file', str(storage/'config'), '--list'], timeout=timeout)
    if not r.ok: raise ValueError('Invalid repository configuration')
    config = {}
    for item in r.stdout.split('\0'):
        if not item: continue
        key, _, value = item.partition('\n')
        if not _SAFE_CONFIG.fullmatch(key): ws.deny('git_config_forbidden')
        config.setdefault(key, []).append(value)
    seen = set() if seen is None else seen
    seen.add(path)
    names = {k[len('remote.'):].rsplit('.',1)[0] for k in config if k.startswith('remote.')}
    for key, values in config.items():
        if key.startswith('remote.') and key.endswith(('.url', '.pushurl')):
            for value in values:
                result = local_or_network(value)
                if Path(result).is_absolute():
                    other = Path(result)
                    if other not in seen and other.exists():
                        validate_repository(other, timeout, bare_ok=True, seen=seen)
        if key.startswith('branch.') and key.endswith(('.remote', '.pushremote')):
            if any(v != '.' and v not in names for v in values): ws.deny('git_remote_forbidden')
    return config

def configured_remote(path, name, timeout=120):
    atom(name)
    config = validate_repository(path, timeout)
    if name != '.' and 'remote.' + name + '.url' not in config:
        workspace().deny('git_remote_not_configured')
    return name

def check_tree(path, revision, timeout):
    r = git(['ls-tree', '-r', '-z', revision], path, timeout)
    if not r.ok: return r
    if any(record.startswith(b'120000 ') for record in r.stdout.encode('utf-8').split(b'\0')):
        workspace().deny('git_symlink_tree_forbidden')
    return Result(ok=True, returncode=0)

def scoped_clone(data):
    ws = workspace()
    destination = ws.resolve(data.destination)
    ws.protect_root(destination)
    source = local_or_network(data.url, virtual=True)
    if Path(source).is_absolute(): validate_repository(Path(source), data.timeout, bare_ok=True)
    args = ['clone', '--no-checkout', '--no-local']
    if data.branch: args += ['--branch', atom(data.branch)]
    if data.depth: args += ['--depth', str(data.depth)]
    r = git(args + ['--', source, str(destination)], timeout=data.timeout)
    if not r.ok: return r
    validate_repository(destination, data.timeout)
    head = git(['rev-parse', '--verify', 'HEAD'], destination, data.timeout)
    if head.ok:
        checked = check_tree(destination, head.stdout.strip(), data.timeout)
        if not checked.ok: return checked
        checked = git(['reset', '--hard', head.stdout.strip()], destination, data.timeout)
        if not checked.ok: return checked
    return r

def scoped_pull(data):
    path = root(data)
    config = validate_repository(path, data.timeout)
    remote, branch = data.remote, data.branch
    if remote is None:
        current = git(['symbolic-ref', '--quiet', '--short', 'HEAD'], path, data.timeout)
        if not current.ok: return current
        prefix = 'branch.' + current.stdout.strip()
        remote = config.get(prefix+'.remote', [None])[-1]
        branch = config.get(prefix+'.merge', [None])[-1]
        if remote is None or branch is None:
            return Result(ok=False, returncode=1, stderr='No upstream configured; supply remote and branch.')
    configured_remote(path, remote, data.timeout)
    fetched = git(['fetch', '--no-recurse-submodules', remote, atom(branch)], path, data.timeout)
    if not fetched.ok: return fetched
    target = git(['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], path, data.timeout)
    if not target.ok: return target
    checked = check_tree(path, target.stdout.strip(), data.timeout)
    if not checked.ok: return checked
    return git(['merge', '--ff-only', '--no-autostash', '--no-edit', target.stdout.strip()], path, data.timeout)
