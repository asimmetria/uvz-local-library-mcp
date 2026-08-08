$project-context-authoring

Работай только внутри текущего Git repository. Не запускай субагентов и не
выходи в соседние директории. Полностью подготовь repository для локального UVZ
RAG, не коммить изменения.

1. Прочитай инструкции и build descriptors. Найди все build roots и модули,
   включая independently consumable библиотеки внутри application repository и
   самостоятельные вложенные проекты без include из root settings.
2. Сначала составь полную очередь модулей. Последовательно обработай child
   libraries/support modules, затем application/root/library-suite.
3. Прочитай существующие project-context.yaml и связанные с ними usage-файлы.
   Обнови корректные файлы. Удали через штатный file-editing tool только явно
   устаревшие карточки и только те docs/usage/*.md, которые были связаны с ними;
   не трогай другие docs, source, tests, build files и migrations.
4. Создай отдельный project-context.yaml для каждой independently consumable
   library, deployable application и consumer-facing support-module строго по
   schema version 1. Дети `*-lib`, а также adapter/facade/model-shared —
   обязательные кандидаты, даже если root application их не подключает.
5. Создай 1–3 docs/usage/*.md только для подтверждённых golden paths. Для
   реального consumer-примера используй read-only MCP `find_library_usages`, а
   точный Gradle alias подтверждай через `suggest_dependency`.
6. Все пояснения пиши по-русски. Не переводи identifiers. Все evidence paths
   должны существовать и быть относительно Git root. Неподтверждённое записывай
   в unknowns; не выдумывай API, keys, aliases, versions и Bitbucket URL.
7. Создавай/изменяй/удаляй файлы только штатными file-editing tools. Запрещены
   shell heredoc/redirection, tee, sed/perl -i и скрипты для записи. Если запись
   вне workspace запрещена, остановись с `blocked_workspace` без обхода.
8. Не запускай shell-валидатор. Вызови read-only MCP `validate_project_context`
   для текущего Git root, исправь все ошибки и повторяй проверку до
   `VALIDATION_OK`. Runner независимо повторит проверку после session.

Верни краткий итог: discovered modules, созданные/изменённые/удалённые файлы,
evidence, unknowns и status (`successful` либо `blocked_workspace`).
