$project-context-authoring

Ты — единственный основной агент workspace-кампании. Не создавай и не запускай
субагентов. Последовательно обработай все repositories из campaign state.

## Управление очередью

Используй только MCP tools `project_context_campaign_next`,
`project_context_campaign_start`, `project_context_campaign_finish` и
`project_context_campaign_report`, а для schema-проверки —
`validate_project_context`. Во всех campaign-вызовах передавай абсолютный
`state_file`, указанный runner-ом в параметрах текущей кампании.

Для каждого repository строго выполни цикл:

1. Получи `next`. Если controller вернул `NO_ELIGIBLE_REPOSITORIES`, заверши
   кампанию.
2. Сразу вызови `start` для полученного абсолютного пути. Controller атомарно
   запишет `running` и увеличит число попыток. Не обрабатывай repository, если
   `start` отказал.
3. Прочитай `last_message`, возвращённый `next`: если там есть предыдущая ошибка
   validator-а, сначала исправь её. Обработай только этот repository по правилам
   скилла и не переходи к следующему до завершения текущего.
4. Вызови `validate_project_context` с абсолютным путём repository. При
   `VALIDATION_FAILED` исправь все перечисленные файлы и повтори вызов. Не ставь
   `successful`, пока последний результат не равен `VALIDATION_OK`.
5. Сразу после обработки обязательно вызови `project_context_campaign_finish`:
   - успех: `status=successful`, `message="краткий итог"`;
   - ошибка/блокировка: `status=failed`, `message="точная причина"`.
6. Только после `finish` снова вызови `next`.

State-файл — обязательный журнал кампании. Обновляй его controller-ом сразу
после каждого repository, даже если обработка неуспешна. На один repository
разрешено не больше двух попыток: controller запрещает третью. После первой
ошибки сделай одну последнюю попытку, если `next` снова вернул этот repository.

## Dirty repositories

Не проверяй dirty как условие допуска и никогда не пропускай repository из-за
`git status`. Не выполняй checkout, reset, clean, stash, restore или commit.
Сохраняй все существующие пользовательские изменения и редактируй только
`project-context.yaml` и `docs/usage/*.md`. Сначала прочитай существующий вариант
файла, затем внеси минимальное целевое изменение; ничего постороннего не
перезаписывай.

## Ограничения

- Обрабатывай только repositories, уже находящиеся в state: точные исключения
  из `index-exclude.txt` controller туда не добавляет.
- Не меняй сам state штатными file tools — только campaign MCP tools.
- Не используй heredoc, redirection, `tee`, `sed -i`, `perl -i` или скрипты для
  создания authoring-файлов.
- Не прекращай кампанию после одного неуспешного repository. Зафиксируй `failed`
  и продолжай очередь до исчерпания eligible repositories.
- В конце вызови `project_context_campaign_report` и верни краткие totals и пути
  repositories, завершившихся `failed` после двух попыток.
