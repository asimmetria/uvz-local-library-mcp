# Roadmap

Цель: довести `uvz-local-library-mcp` до воспроизводимой локальной базы знаний,
которая помогает агенту правильно подключать и использовать внутренние
библиотеки, приложения, конфигурацию и Jimmer.

Roadmap выполняется сверху вниз. Новый этап начинается после прохождения тестов
и критериев готовности предыдущего.

## Текущая база

Уже реализовано:

- локальный stdio MCP и SQLite FTS5;
- индексирование source, docs, examples и YAML-конфигурации;
- строгий `project-context.yaml` schema version 1;
- приоритет `context → usage → docs → source`;
- `suggest_dependency` для `uvz-platform`;
- ingestion audit, retrieval evaluation и атомарная публикация;
- portable knowledge pack и установка одним проектом;
- authoring skill и возобновляемая workspace-кампания одного основного агента:
  без субагентов, с exact excludes, dirty-aware safety baseline, немедленным
  state update и максимум двумя попытками на repository.

## Этап 1. Cross-repository usage graph

Статус: engine и автоматический `dependency_cases` gate реализованы в schema
version 3; перед закрытием этапа требуется прогон минимум трёх positive cases
на рабочем knowledge pack.

Задача: показать агенту не только объявление библиотеки, но и реальные способы
её подключения в приложениях-потребителях.

Работы:

1. Структурно разобрать version catalogs `uvz-platform`.
2. Связать `libs.<alias>` с Maven coordinates и библиотекой-владельцем.
3. Найти использование aliases в `build.gradle(.kts)` всех repositories.
4. Связать consumer repository, Gradle module, alias и source path.
5. Добавить таблицы usage graph в SQLite.
6. Добавить MCP tool `find_library_usages`.
7. Расширить `suggest_dependency`: возвращать coordinates и реальные
   consumer examples.

Критерии готовности:

- по alias или имени библиотеки находятся её consumers;
- каждый результат содержит repository, module, path и commit;
- ложные совпадения из комментариев и generated/build directories исключены;
- есть unit tests и минимум три retrieval cases на реальные сценарии.

## Этап 2. Русскоязычный lexical retrieval

Задача: не терять результат из-за служебных слов, разных написаний и смешанных
русско-английских запросов.

Работы:

1. Нормализовать `camelCase`, `kebab-case`, точки и Gradle aliases.
2. Использовать aliases из `project-context.yaml` для расширения запроса.
3. Выполнять каскадный поиск: exact AND, затем relaxed OR.
4. Добавить небольшой проверяемый список русских/английских stop words.
5. Сохранить boosts для `context` и `usage`.
6. Показывать режим поиска и причину ranking в диагностике.

Критерии готовности:

- существующие exact cases не ухудшились;
- русские usage-вопросы находят нужный context/usage в top 5;
- relaxed search не возвращает результат для заведомо несуществующего API;
- Recall@5 и MRR проходят заданные thresholds.

## Этап 3. Coverage gate и автоматические evaluation cases

Задача: измерять, какая часть workspace действительно описана и доступна
агенту.

Работы:

1. Сопоставить discovered repositories/modules с context cards.
2. Найти missing cards, orphan usage, broken components и unused examples.
3. Ввести явные причины `no_context_required` и ignored modules.
4. Генерировать минимальные retrieval cases из `aliases`, `use_when` и
   `examples.summary`.
5. Объединять generated cases с ручными business cases.
6. Добавить coverage summary в audit и `index_status`.

Критерии готовности:

- отчёт содержит coverage по repository и module;
- каждый curated component имеет хотя бы один positive retrieval case;
- package build блокируется при broken references и падении thresholds;
- false-positive missing cards можно объяснимо исключить.

## Этап 4. Честный provenance

Задача: гарантировать, что path и commit из ответа действительно описывают
проиндексированный файл.

Работы:

1. По умолчанию блокировать публикацию dirty repositories.
2. Добавить явный `--allow-dirty` только для локальных экспериментов.
3. Сохранять remote URL, branch, commit SHA и commit time.
4. Отдельно показывать sync и provenance status каждого source.
5. Проверять, что `project-context.yaml` и usage входят в указанный commit.

Критерии готовности:

- verified pack нельзя собрать из незакоммиченных source files;
- каждый MCP-результат однозначно сопоставим с commit;
- dirty/branch/sync причины видны в audit.

## Этап 5. Возобновляемая workspace-кампания

Основа уже есть в authoring runner: один основной агент, последовательная
ownership-модель, resume-state, terminal limit и safety baseline. На этом этапе
она будет расширена до coverage-aware resume и агрегированного review-отчёта.

Задача: безопасно подготовить context для большой workspace за несколько
запусков агента.

Работы:

1. Добавить явный статус `no_context_required` с доказанной причиной.
2. Сохранять структурированный summary и unknowns после каждого repository.
3. Связать resume с coverage и изменением релевантных source/build файлов.
4. Формировать отдельный итоговый review-отчёт кампании.

Критерии готовности:

- прерванная кампания продолжается без повторной обработки successful repos;
- одновременно один repository принадлежит только одному worker;
- результат кампании воспроизводим и пригоден для review перед commit.

## Этап 6. После презентационного MVP

- точное моделирование `spring.config.import`, profiles и SSL bundles;
- подпись knowledge pack, а не только SHA-256 checksums;
- incremental indexing по file/content hash;
- MCP tool `explain_search`;
- delta packs или artifact registry для больших обновлений;
- сценарные тесты качества готовых ответов агента.

## Пока не делаем

- vector database и embeddings;
- удалённый общий MCP-сервис;
- web UI;
- сложную инфраструктуру обновления до появления измеримого выигрыша.

Сначала улучшаем curated context, реальные consumer usages и lexical
retrieval. К embeddings возвращаемся только если evaluation покажет устойчивый
пробел, который нельзя закрыть этими средствами.
