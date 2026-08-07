# Ingestion audit и quality gate

Индексация не считается успешной только потому, что SQLite создалась. Каждый
knowledge pack проходит четыре проверки.

## Локализованная документация

Для Docusaurus repository базовое дерево `docs/**` считается каноническим.
Переводы в `i18n/**` пропускаются, чтобы не получать дубли результатов на
разных языках. Их количество видно в audit как
`files_skipped_localized_docusaurus_docs`.

## 1. Чистота извлечения

Для каждого chunk сохраняются нормализованный текст, repository, относительный
путь, commit SHA и реальный диапазон строк. Raw source отдельно в pack не
дублируется: `get_source` возвращает сохранённый нормализованный chunk.

- Markdown/MDX: удаляются frontmatter, imports и известные JSX/HTML layout-теги;
  сохраняются заголовки, ссылки, таблицы и fenced code blocks.
- HTML: удаляются `script`, `style`, navigation и известные layout-теги;
  оставшиеся опасные raw tags останавливают quality gate.
- Код: сохраняются package/module и точный line range; большие файлы пока
  режутся по строкам и размеру, AST/symbol-aware chunking относится к следующему
  этапу.
- YAML/TOML/Gradle: хранить путь, profile/module и ключи; секреты редактировать
  до записи в index.

Автоматические стоп-сигналы текущей версии: raw layout HTML, пустой индекс,
generated paths, невалидные line ranges, непрочитанные файлы, пропущенный YAML
parser и возможные неотредактированные secrets. Дедупликация по content hash и
проверка существования исходного файла появятся вместе с incremental index.

## 2. Связь с источником

Каждый результат обязан открываться через `get_source` и содержать:
repository, path, commit SHA, line range, source type и pack version. При
обновлении источника старые chunks удаляются или помечаются устаревшими.

## 3. Валидация примеров

Для Jimmer examples фиксируются commit SHA и Gradle module. Целевой gate должен
проверять:

- файл существует и его snippet не обрезан посередине синтаксической единицы;
- imports и язык определены;
- если пример является runnable test/sample, выполняется его целевой Gradle
  task либо он отмечается как `not-runnable` с причиной;
- retrieval возвращает пример вместе с документацией, а не вместо неё.

## 4. Retrieval evaluation

Для каждого pack создаётся набор вопросов: вопрос, ожидаемый source path,
допустимые alternative sources и ожидаемый режим отказа. Метрики:

- Recall@5 источника;
- MRR;
- доля результатов с корректным commit/path;
- отсутствие HTML-мусора и секретов в результатах;
- корректные отказы, когда в pack нет ответа.

Первый Jimmer gate: 20 вопросов из use-case playbook, включая Fetcher, DTO,
SaveMode, associations, filters, pagination и вопросы вне документации.

В текущей локальной версии `verify_index.py` является обязательным gate и
проверяет schema version, `PRAGMA quick_check`, наличие chunks, generated paths,
line ranges, raw HTML, потенциальные секреты и заданные через `--expect`
лексические запросы. `evaluation-cases.json` дополнительно считает Recall@K,
MRR и долю корректных пустых результатов; packager принимает только успешный
отчёт и включает точный файл вопросов в архив. Полный сценарный benchmark с
оценкой сгенерированного агентом решения относится к следующему этапу.
