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
- Код: сохраняются package/module и точный line range; большие файлы режутся
  по размеру около paragraph и top-level symbol boundaries.
- YAML/TOML/properties: хранятся path, profile/module и keys; secrets редактируются
  до записи в index.

Автоматические стоп-сигналы текущей версии: raw layout HTML, пустой индекс,
generated paths, невалидные line ranges, непрочитанные файлы, пропущенный YAML
parser, возможные неотредактированные secrets и невалидный
`project-context.yaml`. Content-hash deduplication уже используется при выдаче,
а schema version 1 проверяет существование evidence/example/component paths.

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

Текущий public Jimmer gate содержит пять positive cases по Fetcher, DTO,
SaveMode, associations и pagination, а также один negative case по
несуществующему API. Набор расширяется по мере добавления сценариев.

В текущей локальной версии `verify_index.py` является обязательным gate и
проверяет schema version, `PRAGMA quick_check`, наличие chunks, generated paths,
line ranges, raw HTML, потенциальные секреты и заданные через `--expect`
лексические запросы. `evaluation-cases.json` дополнительно считает Recall@K,
MRR и долю корректных пустых результатов; packager принимает только успешный
отчёт и включает точный файл вопросов в архив. Полный сценарный benchmark с
оценкой сгенерированного агентом решения относится к следующему этапу.
