# Dependency usage graph

Usage graph связывает version catalog `uvz-platform` с реальными Gradle
consumer-модулями.

## Что индексируется

Из каждого `uvz-platform/**/libs.versions.toml` структурно извлекаются:

- исходный alias и type-safe accessor `libs.*`;
- Maven group и artifact;
- `version.ref` и разрешённое значение version;
- catalog path и commit;
- repository/module владельца, если он однозначно определяется по
  `project-context.yaml`, имени repository или Gradle module.

В `build.gradle` и `build.gradle.kts` находятся только исполняемые обращения к
`libs.*`. Использования в line/block comments и строковых литералах не входят в
граф. Для каждого consumer сохраняются repository, Gradle module, build path,
configuration, line и commit.

Каждое usage-ребро связано с конкретным catalog path, поэтому одинаковые alias
из разных catalog-файлов не смешивают provenance и consumer examples.

Generated/build directories исключаются общими правилами ingestion.

## MCP tools

`suggest_dependency` отвечает, как подключить библиотеку: возвращает
подтверждённые alias, declaration, coordinates, catalog provenance, owner и до
трёх consumer examples.

`find_library_usages` отвечает, где библиотека уже используется. Искать можно
по alias, `libs.*`, artifact id или owner repository. Опциональный фильтр
`repository` ограничивает выдачу одним consumer.

Пример запроса агенту:

```text
Найди реальные использования sbertone-adapter. Покажи Gradle alias,
consumer repository/module, build path, configuration, строку и commit.
```

## Ограничения текущего этапа

- источником aliases считается `uvz-platform`;
- граф строится по type-safe `libs.*` accessors;
- Gradle bundles/plugins пока не разворачиваются в отдельные library edges;
- owner может остаться `not resolved`, но catalog и consumer provenance при
  этом сохраняются.
