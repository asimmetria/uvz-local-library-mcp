# Ingestion audit и quality gate

Индексация не считается успешной только потому, что SQLite создалась. Каждый
knowledge pack проходит четыре проверки.

## Локализованная документация

Для Docusaurus repository базовое дерево `docs/**` считается каноническим.
Переводы в `i18n/**` пропускаются, чтобы не получать дубли результатов на
разных языках. Их количество видно в audit как
`files_skipped_localized_docusaurus_docs`.

## 1. Чистота извлечения

Для каждого документа сохраняются raw source, normalised text и audit record.

- Markdown/MDX: удалить frontmatter, imports и JSX/HTML layout; сохранить
  заголовки, ссылки, таблицы и fenced code blocks.
- HTML: извлекать текст DOM-парсером, удалить `script`, `style`, navigation и
  cookie banners; не пропускать raw tags в searchable text.
- Код: выделять package/module, class/interface/function и line range;
  не смешивать несвязанные символы в один chunk.
- YAML/TOML/Gradle: хранить путь, profile/module и ключи; секреты редактировать
  до записи в index.

Автоматические стоп-сигналы: raw `<script`, `<div`, `class=`, пустые chunks,
слишком короткие chunks, дубликаты по content hash, невалидные line ranges,
ссылки на несуществующие source files.

## 2. Связь с источником

Каждый результат обязан открываться через `get_source` и содержать:
repository, path, commit SHA, line range, source type и pack version. При
обновлении источника старые chunks удаляются или помечаются устаревшими.

## 3. Валидация примеров

Для Jimmer examples фиксируются commit SHA и Gradle module. Проверяем:

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
