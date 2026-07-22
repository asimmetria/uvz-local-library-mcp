# Knowledge packs

Один SQLite-индекс хранит несколько изолированных knowledge packs. Каждый
chunk обязательно имеет `pack_id`, `pack_version`, `source_type`, `path`,
`commit_sha`, `language`, `visibility` и диапазон строк исходника.

## Типы knowledge entries

Индексатор может читать любой repository, но не каждый repository должен
появляться в каталоге агента как «библиотека». Каталог строится из явно
описанных смысловых единиц:

| Type | Для чего |
| --- | --- |
| `library` | Переиспользуемый API, facade, shared model или starter |
| `configuration` | Конфиги, profiles, SSL bundles, Gradle versions |
| `standard` | Правила, conventions и инженерные гайды |
| `application` | Прикладной сервис; источник usage examples |
| `integration` | Адаптер к внешней системе или инфраструктуре |

Одна запись может ссылаться на module внутри большого repository. Например,
repository с backend, shared model и facade создаёт три source records, но в
catalog попадают только те modules, которые владелец пометил как самостоятельные
knowledge entries.

Подробнее: [catalog-design.md](catalog-design.md).

## Обновление

Локальный updater сверяет commit и content hash. Он переиндексирует только
изменённые файлы, сохраняет предыдущий успешный index run и не публикует pack,
если audit или evaluation не прошли.

## Full-context internal packs

Internal pack должен включать весь полезный контекст: исходный код, Markdown,
API, Gradle-модули, YAML-конфигурацию, реальные примеры и инженерные стандарты.
Это позволяет агенту не только найти имя класса, но и объяснить корректный
способ её использования в существующем стеке.

Индексатор запускается на рабочем компьютере, а готовый pack публикуется во
внутреннее approved storage. Домашний компьютер используется только для engine
и public Jimmer fixtures; internal исходники туда не копируются.
