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
    "min_negative_pass_rate": 1.0
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
  ]
}
```

`expected_sources` использует точный формат `repository:relative/path` и может
содержать несколько допустимых альтернатив. Один positive case считается
найденным, когда хотя бы один ожидаемый source появляется в top K.
Для negative case поиск обязан вернуть пустой результат. Опциональные filters:
`repository`, `module`, `kind`, `language`.

## Внутренние вопросы

Tracked-файл содержит публичные Jimmer fixtures. В рабочем окружении создай
ignored `evaluation-cases.local.json`, сохрани в нём Jimmer cases и добавь
важные сценарии отдела. Запуск:

```bash
./install.sh \
  --workspace /path/to/projects \
  --evaluation-cases evaluation-cases.local.json
```

Packager проверяет SHA-256 definition, evaluation, audit и SQLite. Изменение
вопросов после evaluation делает отчёт устаревшим и блокирует упаковку.
