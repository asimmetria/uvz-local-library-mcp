---
name: project-context-authoring
description: "Создаёт и проверяет project-context.yaml и docs/usage/*.md для локального RAG по приложениям, библиотекам, наборам библиотек и служебным модулям. Используй, когда нужно описать проект для агента, классифицировать модули, добавить подтверждённые примеры подключения или обновить устаревший контекст."
---

# Project Context Authoring

Создай компактный слой знаний, подтверждённый исходниками. Не заменяй README и
не меняй production-код, Gradle/Maven/npm-конфигурацию, тесты или миграции.

## Жёсткие правила

- Не запускай субагентов. В одиночном режиме обрабатывай ровно один Git
  repository. В workspace-режиме оставайся единственным основным агентом и
  строго последовательно проходи campaign state по правилам
  [workspace-campaign-prompt.md](references/workspace-campaign-prompt.md).
- Для workspace используй bundled `scripts/run-all-project-contexts.sh`. Он
  включает все найденные Git repositories независимо от dirty-статуса и
  исключает только точные имена из `index-exclude.txt`.
- В workspace-режиме перед каждой попыткой вызывай campaign `start`, а сразу
  после repository — `finish`, чтобы state-файл обновлялся немедленно. Не
  превышай две попытки: controller технически запрещает третью. `successful`
  повторно не обрабатывай.
- Dirty не является причиной пропуска. Никогда не выполняй checkout, reset,
  clean, stash, restore или commit. Сохраняй существующие изменения; разрешённая
  область authoring остаётся только `project-context.yaml` и `docs/usage/*.md`.
- Создавай, изменяй и удаляй файлы только штатными file-editing tools агента.
  Не используй shell redirection, heredoc, `tee`, `sed -i`, `perl -i` или
  Python/Node scripts как обход запрета на запись. Если file tool сообщает, что
  путь вне workspace или запись запрещена, остановись со статусом
  `blocked_workspace`; не проси shell обойти sandbox.
- Весь пояснительный текст пиши по-русски. Не переводи package/class/method,
  Gradle aliases, coordinates, configuration keys, команды, пути и код.
- Используй только schema version 1 из
  [project-context-schema.md](references/project-context-schema.md). Не
  придумывай поля и не сохраняй старый формат без `schema_version`.
- Всегда заключай пояснительные YAML-строки в двойные кавычки, особенно каждый
  элемент `use_when`, `do_not_use_when` и `unknowns`. Строка с `: ` без кавычек
  разбирается YAML как mapping и не соответствует schema.
- Все `evidence.path`, `examples.path` и `components.context` указывай
  относительно корня Git-репозитория. Проверь существование каждого пути.
  Запрещены `/home/...`, `/Users/...`, `C:\\...` и URL без relative path.
- Не выдумывай public API, назначение, configuration keys, dependency alias,
  ограничения и Bitbucket URL. Неподтверждённое вынеси в `unknowns`.
- Не записывай пароли, токены, сертификаты, private keys и реальные secret
  values.

## Порядок работы

1. Найди границы Git-репозитория и прочитай его инструкции, README,
   `settings.gradle(.kts)`, `build.gradle(.kts)`, `pom.xml`, `package.json` и
   другие build descriptors.
2. Составь полный список самостоятельных build roots и модулей, включая
   вложенные/соседние проекты, не подключённые к корневому приложению.
3. Для каждого кандидата найди доказательства: public API, application
   entrypoint, auto-configuration, `@ConfigurationProperties`, version catalog,
   тесты и реальные consumer usages.
4. Классифицируй и создай карточки:
   - `application` — запускается/deploy-ится и владеет business capability;
   - `library` — подключается consumer-ом;
   - `library-suite` — контейнер независимо подключаемых компонентов;
   - `support-module` — DDL, grants, fixtures, test kit или auto-configuration,
     которую подключает consumer.
5. Создай отдельный `project-context.yaml` для каждой независимо подключаемой
   или разворачиваемой единицы. Root suite-карточка только перечисляет
   `components`; API, dependency и examples находятся в карточках детей.
6. Для каждой важной библиотеки подготовь 1–3 golden paths по шаблону
   [usage-template.md](references/usage-template.md). Бери вызов из consumer/test
   либо собирай минимальный пример только из подтверждённого public API. Если
   корректный вызов доказать нельзя, не создавай фиктивный пример и запиши
   пробел в `unknowns`.
7. Повторно открой созданные файлы и выполни финальную проверку ниже.
8. В workspace-режиме вызови read-only MCP `validate_project_context` для
   текущего repository. Исправь каждую ошибку и повторяй проверку, пока tool не
   вернёт `VALIDATION_OK`. Только после этого вызови campaign `finish` со
   статусом `successful`. При невозможности исправить вызови `finish` со
   статусом `failed` и точной ошибкой. Не запускай shell-валидатор: внешний
   runner независимо повторит проверку после agent session.

## Dependency

Для внутренней Gradle-библиотеки сначала вызови MCP `suggest_dependency`.
Это read-only MCP tool; bundled runner разрешает его заранее вместе с
`find_library_usages`, поэтому отдельное подтверждение не требуется.
Записывай `dependency.alias` и `dependency.declaration` только при однозначном
совпадении alias и coordinates со структурной записью `uvz-platform` catalog.
Используй подтверждённый вид вроде `implementation(libs.sbertoneAdapter)` без
версии. Если alias не найден, опусти `dependency` и добавь вопрос в `unknowns`.

Для Maven/npm также не выдумывай coordinates/package и версию: используй только
build descriptor, registry metadata в репозитории или существующего consumer-а.

## Финальная проверка

- каждая карточка имеет `schema_version`, допустимый `kind`, `name`, русские
  `purpose`/`use_when` и хотя бы один структурированный `evidence`;
- `use_when`, `do_not_use_when` и `unknowns` являются списками непустых строк,
  а не YAML mappings;
- каждый independently consumable child suite имеет собственную карточку;
- application не названа library только из-за facade-модуля внутри;
- entrypoints существуют в `src/main`, configuration keys существуют в source;
- каждый example ведёт в `docs/usage/*.md` и соответствует реальному API;
- relative evidence paths существуют, а абсолютных локальных путей нет;
- в примерах внутренних Gradle-зависимостей нет hardcoded version;
- в отчёте перечислены изменённые файлы, ключевые evidence и `unknowns`.

## Workspace-кампания

Для большого каталога repositories запусти
`scripts/run-all-project-contexts.sh /path/to/projects`. Один основной агент
читает очередь из `.project-context-authoring-campaign.json`, не создаёт
субагентов и сразу сохраняет результат каждого repository. При прерывании
повторный запуск продолжает `pending` и `failed` с числом попыток меньше двух.
Точные исключения задаются по одному имени директории на строку в
`index-exclude.txt`. Запуск с `--restart` создаёт backup state и начинает новую
кампанию.
