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

После установки перезапусти GigaCode и открой корень workspace. Один
координатор может автоматически обработать все repositories: он запускает по
одному субагенту на repository, а каждый субагент проходит модули своего
repository в строгой очереди.

### Готовый промт для всей workspace

Рекомендуется не больше трёх repository-субагентов одновременно. Это быстрее
полностью последовательного режима, но не смешивает контекст разных проектов.
Dirty repositories с посторонними изменениями пропускаются без удаления файлов.

```text
Ты координатор пересоздания project context во всей workspace.

Workspace: /path/to/projects
MCP repository: /path/to/projects/uvz-local-library-mcp

Не создавай контекст самостоятельно и не коммить изменения. Твоя задача —
построить очередь, запускать repository-субагентов и проверять их результат.

1. Проверь наличие инструмента Subagent/Task. Если он недоступен, остановись до
   удаления любых файлов и сообщи, что автоматический workspace-run невозможен.

2. Рекурсивно найди все Git roots внутри workspace. Не включай вложенный Git
   root повторно. Если в MCP repository есть index-exclude.txt, прочитай его и
   исключи перечисленные там имена. Также пропусти сам
   uvz-local-library-mcp, служебные runtime-папки и public repositories jimmer,
   jimmer-docs, jimmer-examples:
   для них project-context-authoring не требуется.

3. Для каждого repository проверь git status. Если есть изменения, не
   относящиеся к project-context.yaml или docs/usage/*.md, пометь repository как
   skipped_dirty и ничего в нём не удаляй.

4. Построй детерминированную очередь по имени repository. Запускай отдельного
   субагента на каждый clean repository, максимум по 3 одновременно. После
   завершения очередной тройки собери результаты и только затем запускай
   следующую. Один repository всегда принадлежит только одному субагенту.

5. Каждому repository-субагенту передай абсолютные пути repository и MCP, а
   также следующую инструкцию:

   $project-context-authoring

   Работай только внутри назначенного Git repository. Полностью пересоздай его
   project context по schema_version: 1. Не коммить изменения.

   а. Найди все build roots и модули по settings.gradle(.kts),
      build.gradle(.kts), pom.xml, package.json и вложенным самостоятельным
      проектам. Учитывай библиотеки внутри application repository, даже если
      приложение их сейчас не подключает. adapter, facade, model-shared и дети
      *-lib являются обязательными кандидатами.

   б. Составь очередь модулей и обрабатывай её последовательно: сначала
      independently consumable child libraries/support modules, затем
      application/root/library-suite. Не запускай несколько module writers,
      изменяющих один repository одновременно.

   в. До удаления прочитай все старые project-context.yaml и собери их examples
      paths в старом и новом формате. Затем удали все старые
      project-context.yaml и только те docs/usage/*.md, которые были указаны в
      их examples. Не удаляй другие docs, README, source, tests, build files и
      migrations.

   г. Для каждой independently consumable library, deployable application и
      consumer-facing support-module создай отдельный project-context.yaml.
      Внутренний технический модуль пропускай только с доказательством.
      db-scripts получает support-module card только если consumers подключают
      его для grants, DDL, fixtures или тестовой базы. Config/docs-only
      repository без поддерживаемого runtime-модуля не заставляй искусственно
      становиться library — отчитайся, что карточка не требуется.

   д. Создай 1–3 docs/usage/*.md только для доказанных golden paths. Все
      пояснения пиши по-русски. Не переводи technical identifiers. Evidence
      paths должны существовать и быть относительными корню Git repository.
      Не выдумывай API, configuration keys, ограничения, Bitbucket URL и
      dependencies. Для внутренней Gradle dependency сначала вызови MCP
      suggest_dependency и используй только подтверждённый libs alias без
      версии. Неподтверждённое занеси в unknowns.

   е. Root library-suite card создавай последней. Она только перечисляет
      components и не дублирует API, dependency, configuration и examples
      дочерних карточек.

   ж. Не меняй production code, build files, tests и migrations. Запусти
      "<MCP repository>/skills/project-context-authoring/scripts/validate-project-context.sh"
      "<repository>" и исправь все ошибки. При failed validation верни статус
      failed, а не successful.

   з. Верни координатору структурированный итог: repository, status,
      discovered_modules, created_cards, created_usage, skipped_modules,
      unknowns, validation_result и changed_files.

6. Если субагент вернул failed validation, отправь ему одну follow-up задачу на
   исправление. Если повторная проверка не прошла, пометь repository как failed
   и продолжай очередь; не удаляй результаты других repositories.

7. После завершения всей очереди не запускай индексацию и не коммить файлы.
   Выведи общую таблицу: successful, skipped_dirty, no_context_required,
   failed; число карточек и usage-файлов; unknowns и repositories, требующие
   ручной проверки.
```

Так maintainer запускает одну задачу на workspace. Параллельность применяется
между repositories, а модули внутри одного repository обрабатываются
последовательно — это исключает конфликты root/component cards.

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
не меняет, а причину записывает в audit.

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
