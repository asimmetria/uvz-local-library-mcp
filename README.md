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
[configuration-model.md](docs/configuration-model.md).

`PyYAML` is installed into the maintainer's virtual environment only when it
runs `--workspace`; обычному developer с готовым pack он не нужен. Runtime MCP
проверяется при любой установке.
MCP SDK требует Python 3.10+; Python 3.13 на рабочем компьютере подходит.

## Первый работающий компонент

`catalog_generator.py` строит local skill catalog из manifest без доступа к
исходному коду. Это разделяет repository/module и смысловую knowledge entry:

```bash
python3 catalog_generator.py examples/manifest.example.json \
  --output /tmp/generated-catalog.md
```

## Первый vertical slice

Собрать pack из public Jimmer sources:

```bash
python3 knowledge_indexer.py --pack jimmer \
  --source /path/to/jimmer-docs \
  --source /path/to/jimmer-examples
```

Проверить, что в docs не осталась навигационная HTML-разметка, generated-code
не попал в index, а примеры реально находятся FTS-запросом:

```bash
python3 verify_index.py --db knowledge.db --expect fetcher --expect association
```

Установить MCP и одновременно собрать pack из Git repositories под текущей
workspace-папкой:

```bash
./install.sh --workspace . --sync \
  --configuration-root ./uvz-config
```

`--sync` изменяет только чистые Git checkout-ы и использует `pull --ff-only`.
Без него installer индексирует текущие локальные файлы без fetch/pull.

После успешного audit maintainer собирает переносимый pack:

```bash
python3 package_pack.py --version 2026.07.22
```

Developer без исходных repositories устанавливает опубликованный artifact:

```bash
./install.sh --knowledge-pack /path/to/knowledge-pack-2026.07.22.zip
```

Для YAML доступны два разных инструмента: `search_config` показывает исходные
файлы, а `resolve_config` собирает leaf-values для `application`,
`configuration_set`, optional `module` и Spring `profile`. Его ответ всегда
содержит provenance. Базовый порядок объединения — central base → module base
→ central profile → module profile; его нужно один раз сверить с реальным
`spring.config.import` конкретного приложения.
