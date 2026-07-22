# Generated library catalog

## Не «список проектов»

Все индексируемые проекты полезны для поиска, но перечислять их в skill как
библиотеки неверно: application, test project и repository с несколькими
Gradle modules имеют разную роль. Поэтому храним три уровня:

```text
repository → module/source → catalog entry
```

- **repository** — Git root, commit и локальный путь;
- **module/source** — Gradle module, docs folder, config tree или frontend
  package внутри repository;
- **catalog entry** — то, что разработчик вправе назвать агенту: library,
  configuration, standard, application или integration.

Discovery начинается от каждого Git root, но рекурсивно читает Gradle settings
и build files всех included modules. Библиотека может лежать внутри repository
прикладного сервиса; отдельный Git repository для неё не требуется и не
ожидается.

## Local manifest

Manifest хранится только на рабочей машине и не коммитится вместе с engine.
Indexer автоматически discovery-ит repositories и modules, а владелец добавляет
краткие entries только для важных предметных областей.

```yaml
sources:
  - repository: /work/repos/example-platform
    modules:
      - path: shared-model
        language: kotlin
      - path: facade
        language: kotlin
      - path: service-app
        language: kotlin

catalog:
  - id: example-model
    type: library
    source_modules: [example-platform:shared-model]
    aliases: [example model, model]
    capabilities: [api, examples]

  - id: example-facade
    type: library
    source_modules: [example-platform:facade]
    aliases: [example facade]
    capabilities: [api, examples]

  - id: example-service
    type: application
    source_modules: [example-platform:service-app]
    capabilities: [examples, configuration]
```

`service-app` всё ещё индексируется и ищется, но не выдаётся как library.

## Generated skill data

После успешного indexing run генератор пишет локальный `generated-catalog.md`:

```text
- example-facade [library, ready]
  aliases: example facade
  sources: example-platform:facade@abc1234
  capabilities: api, examples
```

Skill читает его только для routing. Ответы всегда подтверждаются результатами
MCP, а не текстом каталога.

## Автоматизация без ложных классификаций

Indexer может предлагать candidates: published Gradle modules, modules, на
которые ссылаются `implementation(project(...))`, или folders с документацией.
Нейминг даёт отдельный сигнал:

| Module suffix | Discovery result |
| --- | --- |
| `-adapter` | high-confidence `library` |
| `-model-shared` | high-confidence `library` |
| `-facade` | high-confidence `library` |
| `-lib` | `library-suite`: все child Gradle modules автоматически считаются libraries |

High-confidence entries могут автоматически попасть в generated catalog со
статусом `discovered`; владелец меняет его на `ready` после audit. Эвристика
работает одинаково для Java и Kotlin. Для `-lib` не надо выдавать один
безликий результат: сам контейнер остаётся группой, а каждый Gradle module
внутри него становится самостоятельной library entry — даже без известного
суффикса.

Нейминг оценивается по имени Gradle module и его directory path, а не только
по имени Git repository. Например, `applications/foo/:foo-facade` должен быть
найден так же, как standalone repository `foo-facade`.

Остальные modules остаются candidates до короткой декларации в local manifest.
