# Curated project context: decision record

## Problem

Code and full-text search answer where a symbol is declared, but usually do not
explain a library's intended boundary, supported integration path or minimal
working setup. This makes an agent produce plausible but weakly grounded usage
advice.

## Decision

Keep raw source indexing, but add a small curated layer maintained next to the
source of each important library or application:

```text
project-context.yaml
docs/usage/*.md
README.md
```

`README.md` remains human-facing and optional for RAG routing. The contract is
the other two paths.

### `project-context.yaml`

It is a concise, structured card with at least:

```yaml
schema_version: 1
kind: library # or application
name: example-facade
modules: [":example-facade"]
purpose: Предоставляет поддерживаемый API для получения данных Example.
use_when: [Нужно получить данные Example из другого модуля.]
entrypoints: [com.example.ExampleFacade]
configuration:
  - key: example.client.url
    required: true
    description: Адрес приложения-владельца.
examples:
  - id: get-data
    path: docs/usage/get-data.md
    summary: Получение данных через facade.
evidence:
  - path: example-facade/src/main/java/com/example/ExampleFacade.java
    proves: Подтверждает public entrypoint.
related: [example-model-shared]
```

For an application, describe its responsibility, published modules and
integration/configuration boundaries instead of pretending it is a reusable
library.

For a `*-lib` library suite whose Gradle child modules can be connected
independently, use a root `kind: library-suite` card as a map and create one
`project-context.yaml` inside each consumable child module. The suite card
links to child contexts; it must not combine their entrypoints and examples
into one ambiguous API contract.

DDL, grants, test fixtures and auto-configuration modules are consumable
`kind: support-module` entries when clients use them to provision integration
tests or environments. Give each one its own context card and a usage example
that states the scope and invocation; do not hide it as an internal module.

### `docs/usage/*.md`

Each document is a short, reviewed golden path: dependency, imports, minimal
code, required configuration, expected result and common pitfalls. Examples
should be executable tests or be kept beside an executable test where possible.

Полный контракт находится в
`skills/project-context-authoring/references/project-context-schema.md`.

## Поведение индексатора

1. Каждая карточка проверяется по schema version 1 до публикации pack. Сборка
   отклоняет неизвестный `kind`, английский explanatory text, неправильную
   структуру и абсолютные/несуществующие evidence/example/component paths.
   Ссылочный `docs/usage` обязан иметь полный набор стандартных разделов и
   хотя бы один существующий repository-relative Evidence path.
2. Валидные карточки индексируются как `kind=context`, а Markdown под
   `docs/usage/` — как `kind=usage`; оба типа ранжируются выше случайных
   совпадений в коде и общей документации.
3. Карточка заменяет naming heuristic соответствующего модуля в generated
   catalog. `list_libraries` показывает её purpose, use cases и examples;
   `list_repositories` показывает количество context/usage chunks.
4. Invalid card останавливает атомарную сборку, поэтому ранее опубликованная
   база остаётся рабочей. Retrieval cases по важным библиотекам по-прежнему
   добавляются maintainer-ом перед публикацией pack.
