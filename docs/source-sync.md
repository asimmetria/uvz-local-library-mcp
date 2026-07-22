# Source sync before indexing

Индекс должен отражать актуальную основную ветку repository. Есть два режима: maintainer может
явно обновить выбранную папку проектов, а обычная автоматическая сборка может
работать с отдельными index clones.

## Workspace sync (maintainer mode)

Команда `build --workspace /path/to/projects` может обновлять checkout-ы прямо
в указанной папке, если maintainer намеренно выбрал этот режим. Для каждого Git
root она проверяет чистый worktree и отсутствие локального расхождения, затем:

1. `git fetch origin --prune`;
2. определяет основную ветку из `origin/HEAD` (затем пробует `master` и `main`);
3. убеждается, что её local copy не опережает `origin/<branch>`;
4. переключается на эту ветку;
5. выполняет `git pull --ff-only origin <branch>`;
6. записывает resolved commit SHA в index run.

Dirty repository, отсутствующая branch, unpushed commits, конфликт или ошибка
сети не исправляются автоматически: repository помечается `sync_skipped` или
`sync_failed` и попадает в итоговый отчёт. Indexer не делает `reset --hard` и
не создаёт merge commits.

## Index clones (safe alternative)

Для автоматизированной сборки без изменения developer workspace можно создать
отдельную clone-копию каждого source, например в
`~/.gigacode/library-knowledge/sources/<source-id>`. Именно она служит входом
индексатора.

Перед indexing run:

1. если clone отсутствует — выполнить clone configured branch;
2. `git fetch origin --prune`;
3. переключиться на определённую основную ветку (`origin/HEAD`, затем `master`/`main`);
4. `git pull --ff-only origin <branch>`;
5. записать resolved commit SHA в index run.

При конфликте, отсутствии branch или ошибке сети source помечается
`sync_failed`, а предыдущая успешная версия pack остаётся доступной.

## Modules inside application repositories

После sync indexer обнаруживает все included Gradle modules внутри выбранного
workspace или index clone.
Поэтому library module внутри application repository обновляется вместе с
корнем repository и не требует отдельного Git clone.

Основная ветка определяется после `fetch`: Git-указатель `origin/HEAD` имеет
приоритет, затем используются `master` и `main`. Это поддерживает смешанный
workspace, но repository без указателя и без этих двух веток намеренно не
переключается автоматически.
