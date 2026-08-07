---
name: project-context-authoring
description: "Создаёт и проверяет project-context.yaml и docs/usage/*.md для локального RAG по приложениям, библиотекам, наборам библиотек и служебным модулям. Используй, когда нужно описать проект для агента, классифицировать модули, добавить подтверждённые примеры подключения или обновить устаревший контекст."
---

# Project Context Authoring

Создай компактный слой знаний, подтверждённый исходниками. Не заменяй README и
не меняй production-код, Gradle/Maven/npm-конфигурацию, тесты или миграции.

## Жёсткие правила

- Весь пояснительный текст пиши по-русски. Не переводи package/class/method,
  Gradle aliases, coordinates, configuration keys, команды, пути и код.
- Используй только schema version 1 из
  [project-context-schema.md](references/project-context-schema.md). Не
  придумывай поля и не сохраняй старый формат без `schema_version`.
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
8. Если доступен bundled script, запусти
   `scripts/validate-project-context.sh <корень-репозитория>` и исправь все
   ошибки. Не объявляй работу завершённой при failed validation.

## Dependency

Для внутренней Gradle-библиотеки сначала вызови MCP `suggest_dependency`.
Записывай `dependency.alias` и `dependency.declaration` только при однозначном
совпадении alias и coordinates со строкой `uvz-platform` version catalog.
Используй подтверждённый вид вроде `implementation(libs.sbertoneAdapter)` без
версии. Если alias не найден, опусти `dependency` и добавь вопрос в `unknowns`.

Для Maven/npm также не выдумывай coordinates/package и версию: используй только
build descriptor, registry metadata в репозитории или существующего consumer-а.

## Финальная проверка

- каждая карточка имеет `schema_version`, допустимый `kind`, `name`, русские
  `purpose`/`use_when` и хотя бы один структурированный `evidence`;
- каждый independently consumable child suite имеет собственную карточку;
- application не названа library только из-за facade-модуля внутри;
- entrypoints существуют в `src/main`, configuration keys существуют в source;
- каждый example ведёт в `docs/usage/*.md` и соответствует реальному API;
- relative evidence paths существуют, а абсолютных локальных путей нет;
- в примерах внутренних Gradle-зависимостей нет hardcoded version;
- в отчёте перечислены изменённые файлы, ключевые evidence и `unknowns`.
