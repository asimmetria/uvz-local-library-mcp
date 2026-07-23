# Local Library MCP

Локальный MCP-сервер и SQLite FTS5-база знаний по используемым библиотекам.

## Цель

Агент работает с одним локальным MCP и получает подтверждённые ответы по
Jimmer, внутренним backend/frontend-библиотекам, конфигурации и стандартам.
Никакой удалённый MCP endpoint не требуется.

## Основные принципы

- индекс и исходные репозитории остаются на рабочем компьютере;
- каждое найденное утверждение имеет источник: pack, путь, commit и строки;
- перед публикацией pack проходит ingestion-audit и retrieval evaluation;
- skill содержит только workflow использования MCP, а не копии документации;
- internal packs содержат полный полезный контекст: код, документацию,
  конфигурацию, примеры и стандарты.

## Стартовый scope

Первый pack: `jimmer` — официальная документация, examples, curated use cases
и точный API index. После его quality gate добавляем внутренние packs по одному.

См. [knowledge-packs.md](docs/knowledge-packs.md) и
[ingestion-audit.md](docs/ingestion-audit.md),
[source-sync.md](docs/source-sync.md) and
[product-flow.md](docs/product-flow.md),
[configuration-model.md](docs/configuration-model.md) and
[curated-project-context.md](docs/curated-project-context.md).

`PyYAML` is installed only for maintainer runs with `--workspace`; обычному
developer с готовым pack он не нужен. Runtime MCP использует только стандартную
библиотеку Python, поэтому не требует Rust, Cargo или Xcode Command Line Tools.
Python 3.9+ подходит.

## Первая установка и индексация (maintainer)

Этот сценарий запускает только человек, который выпускает общий knowledge pack.
Все repositories, которые нужно проиндексировать, включая `jimmer`,
`jimmer-docs`, `jimmer-examples`, application repositories и вложенные library
modules, должны быть отдельными Git directories внутри одной workspace-папки.

На рабочем компьютере workspace уже определён:

```bash
PROJECTS=/path/to/projects
cd "$PROJECTS"
git clone git@github.com:asimmetria/uvz-local-library-mcp.git
cd uvz-local-library-mcp

./install.sh \
  --workspace "$PROJECTS" \
  --sync \
  --configuration-root "$PROJECTS/uvz-config"
```

Installer сначала использует `$GIGACODE_HOME/.venv/bin/python`, если он есть;
на рабочем окружении это Python GigaCode. При нестандартной установке можно
выбрать interpreter явно: `PYTHON_BIN=/path/to/python3.13 ./install.sh ...`.
При synthetic/non-writable `$HOME` installer ищет `.gigacode` в родительских
папках проекта и хранит runtime в `.mcp-runtime` рядом с самим MCP-проектом.
Пути можно переопределить через `GIGACODE_HOME` и `MCP_RUNTIME_HOME`.
Если в корпоративном Python есть `pip`, но нет `python3-venv`, installer
автоматически устанавливает зависимости в локальную `.mcp-runtime` через
`pip --target`; права `sudo` и пакет `python3-venv` не нужны.

`--workspace` сам находит **каждый Git repository** под `$PROJECTS` и передаёт
его в indexer один раз. Поэтому `jimmer-docs` отдельно указывать не нужно: если
он лежит рядом с остальными projects, он уже войдёт в pack.

`--configuration-root` не добавляет repository повторно. Он лишь сообщает, что
`uvz-config` — central configuration source: его вложенные папки становятся
отдельными `configuration_set` для `resolve_config`.

`--sync` для чистых checkout-ов делает `fetch`, определяет основную ветку из
`origin/HEAD` (с запасными вариантами `master`, затем `main`), переключается на
неё и выполняет `pull --ff-only`. Repository с локальными commits/изменениями
не изменяется; причина записывается в audit.

Чтобы не индексировать отдельные repositories, создай рядом с `install.sh`
локальный `index-exclude.txt`: по одному **точному имени Git-директории** на
строку, комментарии начинаются с `#`. Файл ignored Git и автоматически
применяется при `--workspace`; итоговый audit содержит `sources_excluded`.
Шаблон: `index-exclude.example.txt`. Для другого расположения используй
`--exclude-file /path/to/list.txt` или переменную `INDEX_EXCLUDE_FILE`.

После успешной сборки можно выполнить необязательную проверку качества:

```bash
python3 verify_index.py --db knowledge.db --expect fetcher
```

Затем maintainer публикует готовый pack:

```bash
python3 package_pack.py --version 2026.07.22
```

## Установка для разработчика

Для команды рекомендуется один закрытый Bitbucket-репозиторий-дистрибутив:
тот же код MCP и опубликованный `dist/knowledge-pack-<version>.zip` в нём.
Разработчик не клонирует projects и не запускает индексацию:

```bash
git clone <internal-bitbucket>/uvz-local-library-mcp.git
cd uvz-local-library-mcp
./install.sh
```

Без `--workspace` и `--knowledge-pack` installer сам выберет самый новый
`dist/knowledge-pack-*.zip`. Он ставит локальный stdio MCP и generic skill.
После перезапуска GigaCode агент использует готовую SQLite-базу.

### Необязательный skill для подготовки документации

`skills/project-context-authoring/` содержит personal skill для владельцев
библиотек: он создаёт `project-context.yaml` и `docs/usage`. Он намеренно не
устанавливается автоматически обычным developer. Владелец подключает его
вручную командой `./scripts/install-project-context-authoring.sh`; она создаёт
симлинк в `$GIGACODE_HOME/skills/project-context-authoring`. Его scripts
`list-gradle-projects.sh` и `run-project-context.sh` запускают GigaCode по
одному выбранному репозиторию, а не по всему workspace.

Maintainer добавляет новый pack в закрытый repository явно (`git add -f
dist/knowledge-pack-<version>.zip`), поскольку `dist/` намеренно ignored в
публичном исходном repository. Если pack распространяется отдельно, его можно
указать явно: `./install.sh --knowledge-pack /path/to/pack.zip`.

Для YAML доступны два разных инструмента: `search_config` показывает исходные
файлы, а `resolve_config` собирает leaf-values для `application`,
`configuration_set`, optional `module` и Spring `profile`. Его ответ всегда
содержит provenance. Базовый порядок объединения — central base → module base
→ central profile → module profile; его нужно один раз сверить с реальным
`spring.config.import` конкретного приложения.
