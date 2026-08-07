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

После установки перезапусти GigaCode. Открывай по одному Git repository, а не
всю workspace сразу.

### Готовый промт для полного пересоздания контекста

Перед запуском желательно иметь чистый working tree или отдельный commit.
Промт удаляет только старые карточки и usage-файлы, на которые они ссылаются.

```text
$project-context-authoring

Работай только внутри текущего Git repository. Не выходи в соседние проекты и
не коммить изменения. Цель — полностью пересоздать контекст repository по
schema_version: 1.

Сначала проверь, что тебе доступен инструмент запуска субагентов/Task. Если он
недоступен, остановись до удаления файлов и сообщи об этом.

Алгоритм:

1. Проверь git status. Если есть изменения, не относящиеся к старым
   project-context.yaml или docs/usage, остановись и перечисли их.

2. Найди все build roots и модули: settings.gradle(.kts), build.gradle(.kts),
   pom.xml, package.json и вложенные самостоятельные проекты. Учитывай
   библиотеки внутри application repository, даже если приложение их сейчас не
   подключает. Модули с суффиксами adapter, facade, model-shared и lib считай
   обязательными кандидатами, но классификацию подтверждай исходниками.

3. До удаления прочитай все старые project-context.yaml. Собери:
   - их пути;
   - все пути из examples в старом и новом формате;
   - связи library-suite → components.

4. Построй список целевых единиц. На каждую независимо подключаемую library,
   deployable application и consumer-facing support-module должна приходиться
   отдельная карточка. Внутренний технический модуль можно пропустить только с
   доказательством. db-scripts получает карточку support-module только если его
   подключают consumers для grants, DDL, fixtures или тестовой базы.

5. Только после построения списка удали:
   - все найденные project-context.yaml;
   - только те docs/usage/*.md, которые были указаны в examples удалённых
     карточек.
   Не удаляй README, исходники, build-файлы, тесты, миграции и другие docs.

6. Запусти отдельного субагента для каждой целевой единицы. Не запускай больше
   разрешённого системой числа одновременно; обрабатывай очередями. Каждый
   субагент владеет только директорией своего модуля и не изменяет файлы других
   модулей.

Передай каждому субагенту инструкцию:

   $project-context-authoring

   Исследуй только назначенный модуль. По исходникам, public API,
   auto-configuration, ConfigurationProperties, tests и реальным consumers
   определи kind. Создай project-context.yaml schema version 1 и 1–3
   docs/usage/*.md только для доказанных golden paths. Все пояснения пиши
   по-русски, технические identifiers не переводи. Evidence paths должны быть
   существующими и относительными корню Git repository. Не используй абсолютные
   пути. Не выдумывай API, configuration keys, ограничения, Bitbucket URL и
   dependency alias. Для внутренней Gradle dependency сначала вызови MCP
   suggest_dependency и используй только подтверждённый libs alias без версии.
   Неподтверждённое запиши в unknowns. Не меняй production-код, build-файлы,
   тесты или миграции. В конце верни список файлов, evidence и unknowns.

7. Сначала дождись карточек дочерних модулей. После этого отдельным субагентом
   создай root project-context.yaml. Для library-suite root-карточка должна
   только перечислять components и не дублировать их API, dependency,
   configuration и examples.

8. После завершения всех субагентов самостоятельно проверь:
   - одна independently consumable/deployable единица — одна карточка;
   - все component/example/evidence paths существуют;
   - usage содержит все обязательные разделы и реальный Evidence path;
   - нет абсолютных локальных путей;
   - весь пояснительный текст на русском;
   - Gradle aliases подтверждены uvz-platform;
   - production-файлы не изменены.

9. Найди рядом с загруженным skill скрипт
   scripts/validate-project-context.sh и запусти его для корня текущего
   repository. Исправь все ошибки. Не объявляй работу завершённой при failed
   validation.

10. В финале отчитайся:
    - сколько build roots и модулей найдено;
    - сколько карточек и usage-файлов создано;
    - какие модули пропущены и почему;
    - какие unknowns должен подтвердить владелец.
```

Такой сценарий безопаснее выполнять для одного repository за запуск. Субагенты
могут работать параллельно, потому что каждый изменяет только свою директорию;
root suite создаётся последней.

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
| `search_config` | Поиск исходных YAML/config-файлов |
| `resolve_config` | Расчёт effective configuration с provenance |
| `index_status` | Audit последней индексации |

## Проверка проекта MCP

```bash
python3 -m unittest discover -s tests -v
python3 smoke_test.py
```

## Дополнительная документация

- [Модель project context](docs/curated-project-context.md)
- [Quality gate](docs/ingestion-audit.md)
- [Knowledge packs](docs/knowledge-packs.md)
- [Retrieval evaluation](docs/retrieval-evaluation.md)
- [Конфигурация](docs/configuration-model.md)
- [Синхронизация исходников](docs/source-sync.md)
