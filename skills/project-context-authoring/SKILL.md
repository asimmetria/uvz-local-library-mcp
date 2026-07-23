---
name: project-context-authoring
description: "Create or improve `project-context.yaml` and curated `docs/usage/*.md` for a repository so a local library RAG can understand applications, libraries and support modules: their role, supported boundaries, configuration and verified integration examples. Use when asked to document a project for the RAG, create agent context, add usage examples, or classify a project."
---

# Project Context Authoring

Create a small, source-grounded context layer; do not replace existing README
or generate generic documentation.

## Mandatory output language: Russian

Write **all natural-language content that you create or update in Russian**.
This is mandatory for `project-context.yaml` values and explanations in
`docs/usage/*.md`, so Russian natural-language queries retrieve them reliably.
Do not write these descriptions in English. Keep technical identifiers exactly
as in source: Gradle aliases, coordinates, package and class names, method
names, configuration keys, file paths, command lines and code snippets. Do
not duplicate whole documents in two languages unless the repository explicitly
requires maintained bilingual documentation.

## Workflow

1. Read repository instructions, README, build descriptors, module settings,
   public API packages, configuration files and existing tests/examples.
2. Discover independently buildable projects before classifying them. Inspect
   the repository tree for nested build descriptors (`settings.gradle(.kts)`,
   `build.gradle(.kts)`, `pom.xml`, `package.json`, or an equivalent), including
   sibling directories that the root application does not currently depend on.
   Treat a nested project as a separate candidate; do not assume an unreferenced
   directory is internal implementation.
3. Decide whether the repository/module is an `application`, `library`,
   `library-suite` or `support-module` from evidence. An application is
   deployable and owns a business capability; a library is consumed by other
   modules; a suite groups independently consumable libraries; a support module
   supplies test infrastructure, DDL, grants or auto-configuration. If evidence
   conflicts, ask the user instead of guessing.
4. Create or update root `project-context.yaml`. Preserve confirmed existing
   facts and never include secrets or real credential values.
5. Add one to three concise `docs/usage/*.md` golden paths only when existing
   code, tests or user-provided information proves them. Prefer linking to a
   runnable test or real source path.
6. Report the evidence used and the important unknowns that need an owner to
   confirm.

## Context card

Use this shape; omit empty optional fields rather than inventing values:

```yaml
kind: library # application, library, library-suite or support-module
name: example-facade
modules:
  - :example-facade
purpose: One factual sentence about the supported responsibility.
use_when:
  - A concrete caller need.
entrypoints:
  - com.example.ExampleFacade
configuration:
  - example.client.url
examples:
  - docs/usage/get-data.md
related:
  - example-model-shared
```

For an application, use `purpose`, its published `modules`, integration
boundaries and configuration; do not describe it as a reusable API merely
because it contains a facade module.

## Library suites

Use `kind: library-suite` for a `*-lib` container only when its child Gradle
modules can be connected independently. Keep its root card as a map of the
suite, not a combined API contract:

```yaml
kind: library-suite
name: example-lib
purpose: Groups reusable modules for example capability.
components:
  - module: :example-facade
    context: example-facade/project-context.yaml
  - module: :example-model-shared
    context: example-model-shared/project-context.yaml
```

Create a separate `project-context.yaml` in every independently consumable
child module. Put that module's entrypoints, dependency/configuration and
golden-path examples in its own card.

## Nested projects beside an application

Apply the same rule when a library or another buildable project sits beside an
application in one repository but is absent from the application's current
dependency graph. Give it its own `project-context.yaml` and usage examples
when evidence shows it can be consumed independently. Do not merge its API
into the application's card, and do not omit it merely because no current
application module depends on it. If the repository root is a genuine suite,
list the sibling project in its `components`; otherwise keep separate cards at
their natural project roots and explain the relationship only when verified.

## Support modules

Create a separate `kind: support-module` card when a module is consumed by a
client to provision test tables, grants, DDL, fixtures or Spring
auto-configuration. It is part of the supported integration path even when it
does not expose a business API. Its usage example must state the target scope
(`test`, local development or production migration), invocation method and
cleanup/constraints. Omit only a genuinely build-internal module that no client
uses.

## Golden path format

Each usage document should answer one developer task and contain only the
necessary pieces:

```markdown
# Get data through Example Facade

## When to use

## Dependency and imports

## Minimal call

## Required configuration

## Expected result

## Constraints and pitfalls

## Evidence
`path/to/ExistingTest.kt` or `path/to/RealUsage.java`
```

Use real package names, dependency coordinates and configuration keys. In an
`Evidence` section, prefer a Bitbucket permalink to the exact file revision:
discover the browser base from `origin` or existing repository links, resolve
the commit SHA, and link to the repository-relative file path at that SHA. Do
not guess a Bitbucket host, project key, repository slug, or URL shape. Always
write the repository-relative path beside the link, for example
`schedulex-core/src/test/.../SchedulerTest.java` — MCP can resolve it against
the indexed repository and commit. If a reliable Bitbucket URL is unavailable,
write only this relative path and report the missing mapping. Never write an
absolute local path such as `/home/...`, `/Users/...` or `C:\\...`: it is not
portable and must not enter the knowledge pack. Mark a section as needing
confirmation when there is no evidence; never fill it with plausible-looking
API calls.

## Gradle dependency aliases

When documenting a Gradle consumer in the UVZ ecosystem, inspect the consumer
`settings.gradle(.kts)` and the indexed `uvz-platform` version catalog before
writing a dependency. Call `suggest_dependency` with the artifact name and use
an alias only when its exact catalog line confirms both the alias and the
coordinates. Never derive `libs.<alias>` mechanically from an artifact name.
If the project imports that catalog as `libs`, use the confirmed alias only,
for example `implementation(libs.sbertoneAdapter)`. Never write a direct
`group:name:version` for a library managed by the catalog: the version belongs
in `uvz-platform`, not in a usage document. State the catalog-import
prerequisite when it is relevant. If no alias is confirmed, do not invent one
or fall back to a guessed version; mark the dependency detail as needing
platform-owner confirmation.

## Quality bar

- Keep the card under roughly 50 lines and a usage document focused on one path.
- Describe supported use, not every implementation detail.
- Do not copy generated code, build output, private keys or passwords.
- Keep examples aligned with the currently checked-out source and update their
  evidence link when refactoring changes it.

## One-repository GigaCode runs

For a controlled rollout, use `scripts/list-gradle-projects.sh <workspace>` to
list candidate Git roots, then launch exactly one session with
`scripts/run-project-context.sh <project>`. The runner instructs GigaCode to
change context files and usage documentation only inside that repository; it
does not batch-run across the workspace.
