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
