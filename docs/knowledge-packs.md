# Knowledge packs

Один SQLite-индекс может хранить записи с разными `pack_id`. Каждый chunk
содержит repository, Gradle module, относительный path, kind, language,
configuration set, commit SHA и реальный диапазон строк исходника. Версия
самого распространяемого pack и список source commits находятся в manifest.

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

Текущая локальная версия полностью пересобирает индекс во временный файл.
Существующий `knowledge.db` заменяется только после успешного завершения
сборки, поэтому ошибка чтения source не уничтожает предыдущий рабочий индекс.
Инкрементальная индексация по content hash остаётся задачей следующего этапа.

Каждая SQLite-база имеет явную версию схемы. Runtime, verifier, packager и
installer используют один schema contract. Pack не публикуется, если audit или
evaluation относятся к другой базе либо evaluation завершилась неуспешно.

Текущая schema version 3 добавляет структурный Gradle dependency graph:
`dependency_aliases` и `dependency_usages`. Pack старой схемы нельзя использовать
с новым runtime — maintainer должен выполнить полную переиндексацию и собрать
новый архив.

## Full-context internal packs

Internal pack должен включать весь полезный контекст: исходный код, Markdown,
API, Gradle-модули, YAML-конфигурацию, реальные примеры и инженерные стандарты.
Это позволяет агенту не только найти имя класса, но и объяснить корректный
способ её использования в существующем стеке.

Индексатор запускается на рабочем компьютере, а готовый pack публикуется во
внутреннее approved storage. Домашний компьютер используется только для engine
и public Jimmer fixtures; internal исходники туда не копируются.
