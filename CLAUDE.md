## Proyecto

- Guía completa del proyecto (arquitectura, convenciones, estado): [docs/CLAUDE.md](docs/CLAUDE.md).
- Fuente de verdad de las correcciones pendientes: [docs/plan_correcciones.md](docs/plan_correcciones.md) (issues EAS-* en Linear).
- Toda decisión de arquitectura se registra como ADR en [docs/adr/](docs/adr/README.md), en el mismo cambio que la implementa.
- Ramas con Gitflow: `feature/<ISSUE-ID>-<slug>` desde `develop`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
