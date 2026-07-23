#!/usr/bin/env bash
# Run one GigaCode authoring session for exactly one repository.
set -Eeuo pipefail

PROJECT="${1:?Usage: $0 /path/to/one-project}"
PROJECT="$(cd "$PROJECT" && pwd)"

if ! command -v gigacode >/dev/null 2>&1; then
  echo "gigacode was not found in PATH" >&2
  exit 1
fi

PROMPT="$(cat <<'EOF'
$project-context-authoring

Работай только с текущим репозиторием. Подготовь его для локального UVZ RAG.

1. Найди корневой Gradle-проект, все include(...) подмодули и самостоятельные
   вложенные buildable-проекты. Не выходи за пределы текущего репозитория.
2. Для самого репозитория и каждого независимо подключаемого модуля создай или
   обнови project-context.yaml. Правильно классифицируй application, library,
   library-suite и support-module.
3. Создай или исправь подтверждённые docs/usage/*.md только по коду, тестам и
   существующей конфигурации. Не меняй production-код, Gradle-конфигурацию,
   миграции или тесты.
4. Все пояснения пиши по-русски. Не переводи технические идентификаторы, код,
   Gradle aliases, классы, методы, YAML-ключи и пути.
5. Для каждой внутренней Gradle-зависимости сначала вызови MCP-инструмент
   suggest_dependency с названием артефакта. Сверь alias и координаты с
   возвращённой точной строкой из uvz-platform/gradle/libs.versions.toml.
   Используй libs alias, например implementation(libs.sbertoneAdapter), только
   при однозначном совпадении. Никогда не выводи alias по имени артефакта. Если
   alias или строка catalog не подтверждены, не выдумывай их и не хардкодь
   group:name:version.
6. Evidence должен содержать относительный путь в репозитории и, если он
   достоверно известен, Bitbucket permalink на конкретный commit. Никогда не
   пиши абсолютные пути этого компьютера.
7. В конце перечисли созданные/изменённые файлы, доказательства и неизвестные
   моменты, которые должен подтвердить владелец проекта.
EOF
)"

cd "$PROJECT"
exec gigacode -p "$PROMPT" --approval-mode=auto-edit
