# Git TWYLT Pack 0.3.0

Десять небольших TWYLT-обёрток для агента: clone, fetch, pull, put, add,
commit, push, diff, status, log. Реальный Git CLI, TWYLT 1.0.0, Python 3.10+.

## Контроль рабочей области (изменение совместимости)

Обязателен `TWYLT_WORKSPACE_ROOT`; `repo`, destination и локальный clone.url теперь
виртуальные относительно него. Журнал JSONL настраивается через `TWYLT_INCIDENT_LOG`.
Описание общей политики и ограничений Git: [WORKSPACE.md](WORKSPACE.md).
Hooks, системная/пользовательская конфигурация и signing отключены; linked worktree,
внешние хранилища объектов и непроверенные настройки репозитория не поддерживаются.

## Установка и запуск

Git должен быть установлен и доступен через PATH. В каталоге распакованного набора:

```sh
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows cmd: .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
# Рабочая область и каталог журналов должны уже существовать:
export TWYLT_WORKSPACE_ROOT=/srv/agent/workspace
export TWYLT_INCIDENT_LOG=/srv/agent/logs/incidents.jsonl
python tools/git_diff/run.py '{"describe":"json_spec"}'
python tools/git_diff/run.py '{"repo":"/work/project"}'
```

Примеры команд с одинарными кавычками рассчитаны на shell Linux/macOS.
Для Windows и автоматизации проще передавать JSON через stdin с закрытием потока
после записи. Можно использовать первый аргумент JSON или стандартный файловый
режим TWYLT (`input.json` → `output.json`). Открытый stdin без EOF может ожидать
данные: это поведение транспорта TWYLT, не Git. Сам Git получает закрытый stdin.

## Toolpack-builder / ToolHub

Сканировать каталог `tools`, выбирать только `**/tool.py` (10 файлов),
не включать `run.py` одновременно. Каждый `tool.py` самодостаточен и содержит
буквальные name/version/requirements/few_shots, Pydantic-схемы и вызов `Tool.run()`.
Нет зависимости от файлов соседних инструментов или установленного пакета проекта.
`run.py` рядом — стандартный launcher `twylt.bootstrap.run_tool_file` для локального
запуска и dependency-independent discovery после установки TWYLT.
В ToolHub можно перенести содержимое соответствующего `tool.py` и получить
метаданные через `json_spec`. Python-зависимости указаны в requirements каждого
инструмента; системный Git устанавливается отдельно. Проверена самостоятельная
работа и discovery всех 10 обёрток; импорт в GUI ToolHub/toolpack-builder здесь
не выполнялся.

## Входы и примеры всех операций

Общий `timeout`: целое число секунд, по умолчанию 120, диапазон 1–3600.
`repo`: виртуальный путь к корню рабочей копии; bare repo не принимается
в операциях над рабочей копией. Неизвестные поля запрещены.

| Обёртка | Пример JSON | Дополнительные параметры |
|---|---|---|
| git_clone | `{"url":"https://host/team/repo.git","destination":"/work/repo"}` | `branch:"main"`, `depth:1` |
| git_fetch | `{"repo":"/work/repo"}` | `remote:"origin"`, `prune:false`, `tags:false` |
| git_pull | `{"repo":"/work/repo"}` | `remote:"origin", branch:"main"` — только вместе; иначе upstream |
| git_put | `{"repo":"/work/repo","path":"src/main.py","content":"print(42)\n"}` | `overwrite:true` для замены существующего файла |
| git_add | `{"repo":"/work/repo","paths":["src/main.py"]}` | `paths:["."]` — весь индексируемый набор изменений |
| git_commit | `{"repo":"/work/repo","message":"Add main"}` | Коммит только текущего индекса |
| git_push | `{"repo":"/work/repo","set_upstream":true}` | `remote:"origin"`, `branch:"main"` — ветка назначения |
| git_diff | `{"repo":"/work/repo"}` | `staged:true`, `base:"HEAD"`, `target:"HEAD~1"`, `paths:["src"]`, `context:3` |
| git_status | `{"repo":"/work/repo"}` | `untracked:"all"`, `paths:["src"]` |
| git_log | `{"repo":"/work/repo","limit":10}` | `skip:0`, `revision:"main"`, `paths:["src"]`, `oneline:true` |

Готовые примеры также лежат в `tools/git_*/example.json`.

Варианты diff:

```json
{"repo":"/work/repo"}
{"repo":"/work/repo","staged":true}
{"repo":"/work/repo","base":"HEAD"}
{"repo":"/work/repo","base":"HEAD~1","target":"HEAD","paths":["src"],"context":5}
```

Первый сравнивает рабочие файлы с индексом; второй — индекс с HEAD;
третий — рабочие файлы с HEAD; четвёртый — два коммита.
`target` требует `base` и несовместим со `staged`.
Untracked-файлы не входят в обычный Git diff: сначала `add`, затем `diff(staged=true)`.
Пути literal: glob/pathspec-магия не выполняется. Каталоги разрешены для add/diff.

## Результат и ошибки

```json
{"ok":true,"returncode":0,"stdout":"","stderr":"","timed_out":false,"paths":[]}
```

`stdout` содержит текст diff или вывод Git, `stderr` — диагностику, в том числе
обычные сообщения об успешном push/clone. `paths` заполняется для put.
**Агент обязан проверить `ok`**, а не только код процесса обёртки.
Ненулевой код Git возвращается как `ok:false` вместе с `returncode` и диагностикой;
процесс TWYLT при этом успешно выдал валидный результат и завершается с 0.
Таймаут: `ok:false, returncode:124, timed_out:true`; он не откатывает операцию.
Ошибки входного контракта и исключения Python оформляются стандартными ошибками
TWYLT в stderr (коды 2 и 5 соответственно).

## Поведение

- `put` пишет один UTF-8 файл целиком, создаёт родительские каталоги, сохраняет
  переводы строк. Не делает add/commit. Замена — через временный файл с сохранением
  существующих прав; без overwrite открывается в режиме exclusive create.
- Запись вне рабочей копии, через symlink и в `.git` запрещена. Это защита от
  случайных путей, не sandbox против конкурентного изменения файловой системы.
- `pull` выполняет fetch, проверяет дерево и делает ff-only merge без autostash: расхождение истории
  требует отдельного решения агента/пользователя. Автоматического разрешения нет.
- `push` отправляет HEAD только в одну ветку назначения, без force и auto-tags;
  detached HEAD отклоняется. Новая ветка может быть создана. Для настройки upstream
  использовать `set_upstream:true`.
- `commit` использует локальные Git user.name/user.email. Hooks и signing отключены.
  Авторизацию SSH настроить заранее через доверенный runner/SSH agent; global
  credential helpers отключены. Интерактивный HTTP-ввод выключен.
- Команды запускаются списком аргументов без shell; локальная конфигурация Git
  проходит строгую allowlist-проверку. Подробнее — WORKSPACE.md.
- Нет reset, clean, amend, rebase, force push, удаления файлов, двоичного put,
  управления ветками: намеренно только запрошенный базовый набор.
- Вывод не обрезается; для крупных diff используйте paths и меньший context.
  Таймаут применяется к каждому вызову Git, включая предварительные проверки.
  Завершение Git по таймауту не гарантирует завершения всех сторонних helpers.

Типичный цикл агента: clone → status → log → put → diff → add → diff(staged) → commit → push.
Для существующей копии: fetch → pull → put → … . Изменение файлов/индекса и
push выполняются только при явном вызове соответствующей обёртки.

## Разработка и тесты

```sh
python -m pip install -r requirements-dev.txt
python scripts/build_tools.py
python -m pytest -q
```

`src/workspace.py`, `src/git_policy.py`, `src/common.py` и `scripts/build_tools.py` — исходники генерации. Полученные
`tools/*/tool.py` включены в релиз: генерация для использования не требуется.
Тесты работают с временными локальными репозиториями, без внешнего сервера.
Проверяют все операции, discovery, удаление через add, literal paths, валидацию,
symlink/traversal, защиту от перезаписи, divergence, non-fast-forward push и timeout.
Архитектурные решения: `docs/adr/`.

## Status и log (0.2.0)

Оба инструмента используют общий Result, вывод находится в `stdout`.

`git_status` возвращает Git porcelain v1 с заголовком `##` о текущей ветке
и tracking-состоянии, если upstream настроен. В двух колонках `XY` первая
показывает изменения в индексе, вторая — в рабочей копии:

- `?? file` — неотслеживаемый файл;
- `A  file` — добавлен в индекс;
- ` M file` — изменён, но не добавлен в индекс;
- `M  file` — изменение добавлено в индекс;
- ` D file` — удалён в рабочей копии;
- `UU file` — конфликт с изменениями с обеих сторон.

Список не исчерпывает все комбинации Git. Даже чистая рабочая копия имеет
строку `##`; пустоту `stdout` нельзя использовать как проверку чистоты.
`untracked` по умолчанию `normal` (каталоги свёрнуты), `all` перечисляет каждый
файл, `no` скрывает неотслеживаемые пути. Игнорируемые файлы не выводятся.
Unicode отображается без ASCII-экранирования; имена с переводами строк/табуляцией
Git по-прежнему может заключать в кавычки и экранировать. Автоматического разбора
статуса в JSON-объекты в этом выпуске нет.

`git_log` по умолчанию показывает до 20 коммитов, полные hash, автора,
коммиттера, даты ISO и сообщения. `oneline:true` оставляет полный hash и тему
коммита. `limit` — 1–1000, `skip` — неотрицательное число для пагинации.
Для устойчивой пагинации при изменении ветки передайте один и тот же commit hash
в `revision`. Без него история начинается с HEAD. `revision` принимает одну
ветку/метку/коммит, не диапазоны `A..B` и не произвольные опции Git.
Фильтр `paths` показывает коммиты, затрагивающие указанные пути (обычное поведение
Git log, без follow для переименований). Нет коммитов в новом репозитории или
неизвестная revision — `ok:false` с диагностикой Git. Пустой результат фильтра
или исчерпанная страница — `ok:true, stdout:""`.

```json
{"repo":"/work/repo","untracked":"all","paths":["src"]}
{"repo":"/work/repo","limit":10,"skip":10,"oneline":true}
{"repo":"/work/repo","revision":"main","paths":["src/main.py"]}
```
