# UVZ Local Library MCP

Локальная база знаний для GigaCode по Jimmer, внутренним библиотекам,
приложениям, конфигурации и инженерным стандартам.

Проект индексирует исходники в SQLite FTS5 и подключает их к агенту через
локальный stdio MCP. Внешняя сеть и удалённый MCP-сервер не нужны.

## Что получает агент

- поиск по Java, Kotlin, frontend-коду, документации и примерам;
- проверенные карточки `project-context.yaml` с назначением проекта;
- golden path примеры из `docs/usage/*.md`;
- точные Gradle aliases из `uvz-platform`;
- реальные Gradle consumers внутренних библиотек;
- YAML-конфигурацию из приложений и нескольких наборов `uvz-config`;
- source id, repository, commit, path и строки для каждого ответа.

При поиске приоритет такой:

1. `project-context.yaml` — назначение и границы использования;
2. `docs/usage/*.md` — рекомендуемый способ подключения;
3. документация и тестовые примеры;
4. исходный код и конфигурация.

## Как устроен процесс

```text
Исходные repositories
        ↓
project-context.yaml + docs/usage
        ↓
Индексация и quality gate
        ↓
knowledge-pack-<version>.zip
        ↓
./install.sh у разработчика
        ↓
GigaCode → local-library-mcp → SQLite
```

Есть две роли:

- **Maintainer** имеет все repositories, готовит контекст, строит и публикует
  knowledge pack.
- **Developer** получает этот проект с готовым pack и запускает только
  `./install.sh`.

## Требования

Для maintainer:

- Git;
- Python 3.9 или новее;
- GigaCode;
- доступ к индексируемым repositories.

Для developer достаточно Python 3.9+ и GigaCode. Docker, Node.js, Rust, Cargo и
Xcode Command Line Tools не нужны. Runtime MCP использует только стандартную
библиотеку Python.

## 1. Первая установка maintainer

Все индексируемые Git repositories должны находиться внутри одной workspace:

```text
/path/to/projects/
  uvz-local-library-mcp/
  jimmer/
  jimmer-docs/
  jimmer-examples/
  uvz-platform/
  uvz-config/
  schedulex/
  other-projects/
```

Клонируй MCP-проект:

```bash
PROJECTS=/path/to/projects
cd "$PROJECTS"
git clone git@github.com:asimmetria/uvz-local-library-mcp.git
cd uvz-local-library-mcp
```

Первичная индексация одновременно установит MCP и основной skill:

```bash
./install.sh \
  --workspace "$PROJECTS" \
  --sync \
  --configuration-root "$PROJECTS/uvz-config"
```

Если рабочая ОС использует нестандартные домашнюю папку и Python:

```bash
GIGACODE_HOME="/path/to/.gigacode" \
MCP_RUNTIME_HOME="/path/to/projects/.mcp-runtime" \
PYTHON_BIN="/path/to/.gigacode/.venv/bin/python" \
./install.sh \
  --workspace "/path/to/projects" \
  --sync \
  --configuration-root "/path/to/projects/uvz-config"
```

После установки перезапусти GigaCode.

### Что делает `--workspace`

- находит каждый Git repository рекурсивно и индексирует его один раз;
- обнаруживает Gradle-модули, в том числе библиотеки внутри приложений;
- отдельно индексирует Jimmer docs/examples;
- для Docusaurus пропускает переводы из `i18n`, если есть канонические docs;
- строит новый индекс во временной папке;
- заменяет рабочую базу только после успешных проверок.

`--configuration-root` не индексирует repository повторно. Он помечает
центральный конфигурационный repository и его наборы конфигураций.

## 2. Подготовка `project-context.yaml`

Authoring skill устанавливается только maintainer-у:

```bash
./scripts/install-project-context-authoring.sh
```

После установки перезапусти GigaCode. Workspace обрабатывает один основной
агент, без субагентов. Shell tool у него отключён, поэтому он не сможет обходить
file-editing policy через heredoc или перенаправление вывода.

### Последовательная обработка всей workspace

Перед запуском проверь через `/mcp`, что `local-library-mcp` подключён и
показывает campaign tools `project_context_campaign_next`, `start`, `finish` и
`report`. Затем запусти runner из MCP repository:

```bash
cd "/home/work/21498149@sigma.sbrf.ru/projects/uvz-local-library-mcp"
./skills/project-context-authoring/scripts/run-all-project-contexts.sh \
  "/home/work/21498149@sigma.sbrf.ru/projects"
```

Другой разработчик заменяет абсолютные пути на свои.

Runner:

- находит все Git repositories и передаёт их одному основному GigaCode-агенту;
- основной агент обрабатывает repositories строго последовательно и не запускает
  субагентов;
- включает `auto-edit` и заранее разрешает только read-only MCP tools
  `suggest_dependency`, `find_library_usages` и четыре campaign-state tools;
- полностью отключает agent/subagent и shell tools;
- не проверяет dirty как условие допуска: незакоммиченные repositories тоже
  обрабатываются, а существующие изменения запрещено сбрасывать или затирать;
- перед каждой попыткой controller сохраняет fingerprint файлов вне authoring
  scope; при изменении любого такого файла repository получает terminal
  `failed`, а третья попытка запрещена;
- сразу после каждого repository атомарно записывает `successful` или `failed`;
- делает не больше двух попыток на один repository;
- после agent session повторно запускает deterministic validator для всех
  успешных карточек.

State локален и игнорируется Git:

```text
.project-context-authoring-campaign.json
```

В файле видны имя, абсолютный путь, status, число попыток и время завершения
каждого repository. Он обновляется немедленно после обработки. После прерывания
просто повтори ту же команду: `successful` пропускаются, а `pending`/`failed`
возобновляются, пока не исчерпаны две попытки. Для сознательного полного
перезапуска используй `--restart`: старый state копируется в timestamped backup.

```bash
cd "/home/work/21498149@sigma.sbrf.ru/projects/uvz-local-library-mcp"
./skills/project-context-authoring/scripts/run-all-project-contexts.sh \
  "/home/work/21498149@sigma.sbrf.ru/projects" --restart
```

Если raw live JSON слишком шумный, переключи вывод на обычный текст:

```bash
cd "/home/work/21498149@sigma.sbrf.ru/projects/uvz-local-library-mcp"
PROJECT_CONTEXT_OUTPUT_FORMAT=text \
  ./skills/project-context-authoring/scripts/run-all-project-contexts.sh \
  "/home/work/21498149@sigma.sbrf.ru/projects"
```

Один repository можно обработать отдельно. В этом точечном режиме прежняя
строгая проверка не разрешает посторонние dirty-изменения:

```bash
./skills/project-context-authoring/scripts/run-project-context.sh \
  "/path/to/one-project"
```

### Проверка одного repository без индексации

```bash
python3 validate_project_contexts.py /path/to/project
```

Проверяются schema, русский текст, типы полей, структура suite, обязательные
разделы usage и существование всех относительных evidence paths.

Перед индексацией просмотри изменения и закоммить карточки в их repositories.
Индексатор читает текущий working tree, но provenance содержит commit `HEAD`,
поэтому для воспроизводимого pack контекст и usage должны входить в этот commit.

```bash
git status --short
git diff -- .
```

## 3. Полная переиндексация

После подготовки карточек повтори maintainer-команду:

```bash
cd /path/to/projects/uvz-local-library-mcp

./install.sh \
  --workspace "/path/to/projects" \
  --sync \
  --configuration-root "/path/to/projects/uvz-config"
```

Успешная сборка создаёт:

- `knowledge.db`;
- `audit-summary.json`;
- `evaluation-summary.json`;
- `evaluation-cases.built.json`;
- `skills/library-knowledge-workflow/generated-catalog.md`.

Если хотя бы одна карточка невалидна или quality gate не пройден, предыдущая
рабочая база не заменяется.

После первой сборки schema version 3 создай и вручную проверь три реальные
dependency graph cases, затем повтори сборку с локальным definition:

```bash
python3 scripts/draft-dependency-cases.py --limit 3

./install.sh \
  --workspace "/path/to/projects" \
  --sync \
  --configuration-root "/path/to/projects/uvz-config" \
  --evaluation-cases evaluation-cases.local.json
```

Генератор не перезаписывает `evaluation-cases.local.json`; подробный review-flow
описан в [retrieval evaluation](docs/retrieval-evaluation.md). После проверки
каждого consumer поставь `dependency_case_draft.review_required: false`, иначе
quality gate намеренно не пройдёт.

### Исключение repositories

Скопируй шаблон и укажи точные имена директорий, по одному на строку:

```bash
cp index-exclude.example.txt index-exclude.txt
```

Пример:

```text
old-project
experimental-service
```

`index-exclude.txt` не коммитится и автоматически применяется при индексации.

### Обновление исходников

Обычный `--sync` безопасен: dirty repositories и ветки с локальными commits он
не обновляет через Git, а причину записывает в audit. Это не исключает их из
индексации: после `sync_skipped_dirty` индексатор читает текущий working tree,
включая незакоммиченные `project-context.yaml` и `docs/usage/*.md`. Строка
`done — ... files, ... chunks` подтверждает, что repository проиндексирован.

Принудительное обновление всех repositories выполняется отдельно:

```bash
./scripts/force-sync-all.sh /path/to/projects
./scripts/force-sync-all.sh /path/to/projects --apply
```

Первая команда — dry run. Вторая переключает каждый repository на
`origin/master` или `origin/main` и удаляет локальные tracked-изменения. Она
ничего не push-ит и не удаляет untracked-файлы.

## 4. Создание knowledge pack

После успешной индексации:

```bash
python3 package_pack.py --version YYYY.MM.DD
```

Результат:

```text
dist/knowledge-pack-YYYY.MM.DD.zip
```

Pack содержит SQLite, catalog, manifest, audit, evaluation и точный набор
retrieval cases. Упаковка блокируется, если отчёты относятся к другой базе или
quality gate не пройден.

Внутренний индекс содержит производные от исходников данные. Публикуй pack
только во внутренний Bitbucket/artifact storage. Не добавляй внутренний pack в
публичный GitHub repository.

Рекомендуемый способ распространения — положить versioned ZIP в `dist/` этого
же проекта во внутреннем Bitbucket. Тогда разработчик клонирует только один
repository.

## 5. Установка у разработчика

Внутренний repository уже должен содержать `dist/knowledge-pack-<version>.zip`:

```bash
git clone <internal-bitbucket>/uvz-local-library-mcp.git
cd uvz-local-library-mcp
./install.sh
```

Installer автоматически:

1. выбирает самый новый bundled pack;
2. проверяет schema, размеры и SHA-256;
3. атомарно устанавливает SQLite и отчёты;
4. добавляет `local-library-mcp` в GigaCode settings;
5. устанавливает основной `library-knowledge-workflow` skill;
6. запускает настоящий stdio MCP smoke test.

После установки перезапусти GigaCode и проверь `/mcp`.

Проверочный промт:

```text
Используя local-library-mcp, найди пример Jimmer Fetcher. Назови repository,
source id, path, commit и кратко объясни, что делает пример. Не отвечай без
ссылки на источник из локальной базы.
```

Developer не запускает индексацию и не устанавливает authoring skill.

## MCP-инструменты

| Инструмент | Назначение |
| --- | --- |
| `search_knowledge` | Поиск context, usage, docs, examples и source |
| `get_source` | Чтение полного найденного chunk |
| `list_libraries` | Каталог библиотек, приложений и возможностей |
| `list_repositories` | Все repositories и количество проиндексированных данных |
| `suggest_dependency` | Подтверждённый `libs.<alias>` из `uvz-platform` |
| `find_library_usages` | Реальные consumer repositories/modules для библиотеки |
| `search_config` | Поиск исходных YAML/config-файлов |
| `resolve_config` | Расчёт effective configuration с provenance |
| `index_status` | Audit последней индексации |

## Проверка проекта MCP

```bash
python3 -m unittest discover -s tests -v
python3 smoke_test.py
```

## Дополнительная документация

- [План развития](ROADMAP.md)
- [Dependency usage graph](docs/dependency-usage-graph.md)
- [Retrieval и dependency graph evaluation](docs/retrieval-evaluation.md)
- [Модель project context](docs/curated-project-context.md)
- [Quality gate](docs/ingestion-audit.md)
- [Knowledge packs](docs/knowledge-packs.md)
- [Retrieval evaluation](docs/retrieval-evaluation.md)
- [Конфигурация](docs/configuration-model.md)
- [Синхронизация исходников](docs/source-sync.md)
