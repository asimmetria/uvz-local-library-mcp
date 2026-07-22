# Configuration model

Конфигурация может лежать одновременно в application/module repository и в
central configuration repository. В pack хранятся два представления.

## Raw source index

`search_config` ищет исходный YAML/YML (также TOML/properties) и возвращает
путь, commit, repository/module и configuration set. Это источник истины для
вопросов «где определяется этот ключ?» и для проверки результата.

Central configuration repository передаётся indexer как
`--configuration-root`. Для его YAML первая вложенная папка становится
`configuration_set`; варианты, лежащие рядом (`uvz-config`, `sbc-config`,
`drpa-kul-config`), поэтому не смешиваются.

## Effective YAML view

При maintainer-сборке `--workspace` installer ставит и проверяет `PyYAML`;
тогда indexer разбирает YAML documents и сохраняет leaf-values с полями:

- repository, Gradle module и relative path;
- configuration set;
- профиль из `spring.config.activate.on-profile`, `spring.profiles` или имени
  `application-<profile>.yml`;
- layer (`central` или `module`), key path и JSON value.

`resolve_config` принимает repository приложения, configuration set, optional
Gradle module и Spring profile. Для каждого итогового ключа он возвращает
provenance: какой слой и какой файл его дали.

Пока применяется явный консервативный порядок:

1. central base;
2. module base;
3. central selected profile;
4. module selected profile.

Это не попытка угадать универсальную семантику Spring Boot. У приложения может
быть иной `spring.config.import`; MCP указывает использованный порядок в самом
ответе. При подключении нового family приложений maintainer сверяет его с
bootstrap/import-цепочкой и добавляет соответствующую regression-query в
evaluation pack.

## Safety

Секретоподобные YAML/properties/toml значения редактируются до сохранения в
SQLite. Pack не является хранилищем паролей, private keys или сертификатов:
SSL bundle structure индексируется, но секретный материал не сохраняется.
