# Схема `project-context.yaml`

Создавай карточку по schema version 1. Все пути указывай относительно корня Git
repository. Все пояснения пиши по-русски, технические идентификаторы не
переводи.

## Library/application/support-module

```yaml
schema_version: 1
kind: library # application | library | support-module
name: example-facade
aliases:
  - example facade
modules:
  - :example-facade
purpose: Предоставляет поддерживаемый API для получения данных Example.
use_when:
  - Нужно получить данные Example из другого модуля.
do_not_use_when:
  - Изменение относится к внутренней реализации приложения-владельца.
entrypoints:
  - com.example.ExampleFacade
dependency:
  ecosystem: gradle
  alias: libs.exampleFacade
  declaration: implementation(libs.exampleFacade)
configuration:
  - key: example.client.url
    required: true
    description: Адрес приложения-владельца.
examples:
  - id: get-example
    path: docs/usage/get-example.md
    summary: Получение Example через facade.
evidence:
  - path: example-facade/src/main/java/com/example/ExampleFacade.java
    proves: Публичная точка входа facade.
related:
  - example-model-shared
unknowns:
  - Требуется подтверждение владельца по retry policy.
```

Обязательные поля: `schema_version`, `kind`, `name`, `purpose`, `use_when`,
`evidence`. Не добавляй пустые optional-поля.

Для Gradle `dependency` добавляй только после подтверждения точного alias через
`suggest_dependency`; укажи `ecosystem: gradle`. Если alias не подтверждён, не
выдумывай его: опусти `dependency` и запиши вопрос в `unknowns`. Для Maven/npm
используй соответственно `ecosystem: maven` + `coordinates` либо
`ecosystem: npm` + `package`, а также подтверждённую `declaration`; не добавляй
hardcoded version, если ей управляет platform/BOM/catalog.

В `configuration` добавляй только ключи, найденные в source или
`@ConfigurationProperties`. Никогда не записывай реальные значения secrets.

## Library suite

Для контейнера `*-lib`, дети которого подключаются независимо:

```yaml
schema_version: 1
kind: library-suite
name: example-lib
purpose: Объединяет независимо подключаемые библиотеки Example.
use_when:
  - Нужно выбрать библиотеку для интеграции с Example.
components:
  - module: :example-facade
    context: example-facade/project-context.yaml
  - module: :example-model-shared
    context: example-model-shared/project-context.yaml
evidence:
  - path: settings.gradle.kts
    proves: Состав independently buildable модулей.
```

Каждый independently consumable component получает собственную карточку. Не
объединяй его entrypoints, dependency и examples в suite-карточку.

## Evidence

Каждый элемент `evidence` обязан содержать существующий repository-relative
`path` и краткое `proves`. Bitbucket permalink можно добавить отдельным полем
`url`, но `path` остаётся обязательным. Запрещены `/home/...`, `/Users/...`,
`C:\...`, придуманные URL и ссылки только на локальный компьютер.
