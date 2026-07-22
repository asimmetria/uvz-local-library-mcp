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

`PyYAML` is installed into the maintainer's virtual environment only when it
runs `--workspace`; обычному developer с готовым pack он не нужен. Runtime MCP
проверяется при любой установке.
MCP SDK требует Python 3.10+; Python 3.13 на рабочем компьютере подходит.

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
Если корпоративная защита не даёт читать Python packages из `.gigacode`, runtime
можно вынести в обычную workspace-папку: `MCP_RUNTIME_HOME=/path/to/projects/.mcp-runtime`.

`--workspace` сам находит **каждый Git repository** под `$PROJECTS` и передаёт
его в indexer один раз. Поэтому `jimmer-docs` отдельно указывать не нужно: если
он лежит рядом с остальными projects, он уже войдёт в pack.

`--configuration-root` не добавляет repository повторно. Он лишь сообщает, что
`uvz-config` — central configuration source: его вложенные папки становятся
отдельными `configuration_set` для `resolve_config`.

`--sync` для чистых checkout-ов делает `fetch`, переключается на `master` и
выполняет `pull --ff-only`. Repository с локальными commits/изменениями или без
ветки `master` не изменяется; причина записывается в audit.

После успешной сборки можно выполнить необязательную проверку качества:

```bash
python3 verify_index.py --db knowledge.db --expect fetcher
```

Затем maintainer публикует готовый pack:

```bash
python3 package_pack.py --version 2026.07.22
```

## Установка готового pack (обычный developer)

Разработчик не клонирует projects и не запускает индексацию. Он скачивает
репозиторий MCP и опубликованный архив pack, затем выполняет:

```bash
cd uvz-local-library-mcp
./install.sh --knowledge-pack /path/to/knowledge-pack-2026.07.22.zip
```

Installer ставит локальный stdio MCP и generic skill. После перезапуска
GigaCode агент использует готовую SQLite-базу.

Для YAML доступны два разных инструмента: `search_config` показывает исходные
файлы, а `resolve_config` собирает leaf-values для `application`,
`configuration_set`, optional `module` и Spring `profile`. Его ответ всегда
содержит provenance. Базовый порядок объединения — central base → module base
→ central profile → module profile; его нужно один раз сверить с реальным
`spring.config.import` конкретного приложения.
