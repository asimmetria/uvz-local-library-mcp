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
kind: library # or application
name: example-facade
modules: [":example-facade"]
purpose: One sentence describing the supported responsibility.
use_when: [When the caller needs example data.]
entrypoints: [com.example.ExampleFacade]
configuration: [example.client.url]
examples: [docs/usage/get-data.md]
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

## Planned indexer behaviour

1. A declared `kind` overrides naming heuristics for the generated catalog.
2. Context cards and usage examples are tagged and ranked above incidental code
   matches for usage questions.
3. `list_libraries` and `list_repositories` expose the declared purpose and
   examples.
4. Every curated library gets retrieval evaluation queries before a pack is
   published.

This is intentionally not implemented yet: first we will agree on a real
card/example from one internal library, then make the schema and indexer stable.
