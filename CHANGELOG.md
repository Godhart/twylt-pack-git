# 0.4.0 — 2026-10-08

- Replace copied workspace/transport checks with TWYLT >=1.1.1 APIs.
- Move shared business helpers into shared/git_common; keep tool-only code with its tool.
- Remove source-copy generation; deploy source tree without building a Python pack.
- Support optional nested transport cwd outside workspace and common network policy.
- Preserve existing scenarios, add actual builder launcher checks, refresh schemas and ADR.

# Changelog

## 0.3.0 — 2026-10-02

Несовместимое изменение: обязательный TWYLT_WORKSPACE_ROOT и виртуальные пути.
Общая политика ссылок/границ, preflight рекурсивных операций, защита файлового
транспорта TWYLT. Журнал инцидентов JSONL, внешний sink и fail-closed при ошибках.
В Git дополнительно ограничены remotes, конфигурация, hooks и служебные хранилища.
Сохранены регрессии прежних версий, обновлены ожидания для запрещённых ссылок;
добавлены проверки обходов и журналирования. См. WORKSPACE.md.

## 0.2.0 — 2026-10-01

Добавлены git_status (porcelain v1, branch, untracked, paths) и git_log
(limit, skip, revision, paths, oneline). Общая схема Result сохранена.
Обновлены примеры и README, сохранены все тесты 0.1.0, добавлены регрессии.

## 0.1.0 — 2026-10-01

Первый выпуск: восемь самостоятельных TWYLT-обёрток, примеры, ADR и интеграционные тесты.
