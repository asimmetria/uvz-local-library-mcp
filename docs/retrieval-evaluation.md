# Retrieval evaluation

`evaluation-cases.json` — воспроизводимый quality gate полнотекстового поиска.
Он запускается автоматически при maintainer-сборке и попадает в knowledge pack
вместе с итоговым отчётом.

## Формат

```json
{
  "version": 1,
  "top_k": 5,
  "thresholds": {
    "min_recall_at_k": 1.0,
    "min_mrr": 0.8,
    "min_negative_pass_rate": 1.0,
    "min_dependency_cases": 3,
    "min_dependency_pass_rate": 1.0
  },
  "cases": [
    {
      "id": "facade-usage",
      "query": "ReceiveInboundMessageFacade receive message",
      "filters": {"repository": "example-facade"},
      "expected_sources": [
        "example-facade:docs/usage/receive-inbound-message.md"
      ]
    },
    {
      "id": "unknown-api",
      "query": "DefinitelyMissingInternalApi",
      "expect_no_results": true
    }
  ],
  "dependency_cases": [
    {
      "id": "facade-real-consumer",
      "query": "receive inbound facade",
      "expected_aliases": ["receiveInboundFacade"],
      "expected_consumers": [
        {
          "repository": "consumer-service",
          "module": ":api",
          "path": "api/build.gradle.kts",
          "configuration": "implementation"
        }
      ]
    },
    {
      "id": "unknown-dependency",
      "query": "DefinitelyMissingDependencyAlias",
      "expect_no_results": true
    }
  ]
}
```

`expected_sources` использует точный формат `repository:relative/path` и может
содержать несколько допустимых альтернатив. Один positive case считается
найденным, когда хотя бы один ожидаемый source появляется в top K.
Для negative case поиск обязан вернуть пустой результат. Опциональные filters:
`repository`, `module`, `kind`, `language`.

`dependency_cases` проверяет не FTS-текст, а структурные таблицы usage graph.
`expected_aliases` содержит исходные aliases из version catalog.
`expected_consumers` — допустимые реальные подключения; достаточно совпадения
одной записи. У записи можно проверять любое подмножество полей `alias`,
`accessor`, `repository`, `module`, `path`, `configuration`, `commit`, `line`.
Evaluator дополнительно всегда требует корректный repository/module/path,
полный commit SHA и положительный номер строки у найденных consumers.

## Внутренние вопросы

Tracked-файл содержит публичные Jimmer fixtures. В рабочем окружении создай
ignored `evaluation-cases.local.json`, сохрани в нём Jimmer cases и добавь
важные сценарии отдела.

После первой сборки schema version 3 можно создать неперезаписываемый черновик
из реальных рёбер текущей БД:

```bash
python3 scripts/draft-dependency-cases.py \
  --db knowledge.db \
  --base evaluation-cases.json \
  --output evaluation-cases.local.json \
  --limit 3
```

Скрипт выбирает разные aliases с известной configuration, фиксирует одного
consumer для каждого и ставит `review_required: true`. Он не перезаписывает
существующий файл. Проверь каждый alias, module и path непосредственно в
исходном repository; поправь черновик, если выбранный consumer не является
хорошим эталоном, затем явно поставь `review_required: false`. Пока флаг равен
`true`, quality gate и упаковка не пройдут. Не генерируй файл заново перед
каждой сборкой — сохранённые
ожидания должны обнаруживать регрессии, а не повторять текущее состояние БД.

Для закрытия этапа usage graph нужны минимум три `dependency_cases` с разными
реальными библиотеками и consumers. Порог `min_dependency_cases` считает только
positive cases; negative проверки отсутствующих aliases полезны, но не заменяют
реальные сценарии. После review повтори сборку уже с зафиксированным definition:

```bash
./install.sh \
  --workspace /path/to/projects \
  --evaluation-cases evaluation-cases.local.json
```

Packager проверяет SHA-256 definition, evaluation, audit и SQLite. Изменение
вопросов после evaluation делает отчёт устаревшим и блокирует упаковку.
