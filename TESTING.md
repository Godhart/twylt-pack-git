# Testing git 0.4.0

Python 3.12, TWYLT 1.1.1, 2026-10-08: 93 passed. No external network used.
All earlier behavioral scenarios are preserved. Policy tests now use TWYLT itself;
assertions were updated for code 6 and the centralized transport incident code.
Copied source packs are scanned by builder 0.4.1 and their actual generated
launcher runs in a nested cwd outside workspace using file transport.
Filesystem and Git exercise real operations; Docker tests use mock daemon APIs.
No pack Python distribution is installed. Whole tools/shared tree is required.

Base: https://github.com/Godhart/twylt-pack-git, commit 85057768e2d5ecc05f6e6f92d5674dfca014616f.
Archive includes a patch against this fresh GitHub checkout and SHA256SUMS.

```bash
python -m pip install -r requirements.txt
# Integration tests also need toolpack-builder 0.4.1.
python -m pytest -q tests
python scripts/export_schemas.py
```

## Previous release results (historical)

# Release validation — git-twylt-pack-0.3.0

2026-10-02, Linux, Python 3.12, TWYLT 1.0.0, Pydantic 2.13.5.

`python -m pytest -q`: **88 passed**.

Preserved the 28 previous regression cases; adjusted expected behavior for the
intentional virtual-path migration and strict symlink policy. New tests cover
mandatory configuration, virtual absolute/relative paths, traversal, symlinks,
hardlinks, FIFO, whole-tree mutation preflight, root protection, JSONL incidents,
parallel append, sink failures, every tool's fail-closed initialization, discovery
without configuration, and file-mode transport paths. Git tests additionally cover
local remotes, gitdir/alternates/config redirection, disabled hooks and symlink trees.

No external network/account/repository was used by tests. Windows/macOS, container
isolation, adversarial concurrent filesystem replacement and ToolHub GUI integration
were not tested; do not infer an OS sandbox guarantee from these results.
