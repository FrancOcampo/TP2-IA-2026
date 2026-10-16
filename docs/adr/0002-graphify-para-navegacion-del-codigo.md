# ADR-0002 · graphify como grafo de conocimiento del proyecto, portable y acotado

- **Estado:** Aceptado
- **Fecha:** 2026-09-15
- **Relacionado:** —

## Contexto

- El sistema reparte la lógica entre `orchestrator/`, `agents/`, `tools/`, `rag/`, `interface/` y `tests/`,
  con contratos compartidos (`AgentState`, `MonitorAnalysis`, `TimeRange`), y el diseño vive en varios
  documentos (definición conceptual, artículo JIT, papers CONAIISI, plan de correcciones). El plan toca varios
  módulos por ítem y el trabajo se hace con asistentes de código (Claude Code), donde cada exploración
  "leyendo archivos" consume muchos tokens.
- `.claude/settings.json` ya estaba versionado con hooks de graphify que apuntaban a una ruta absoluta de Linux
  (`/home/franco/.local/bin/graphify`). En Windows esa ruta no existe, así que los hooks fallaban para
  cualquier integrante que no usara esa máquina.
- graphify tiene muchos forks con nombres parecidos. El paquete oficial es `graphifyy` en PyPI, cuyo repositorio
  es [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) (verificado contra los metadatos del
  paquete instalado y la página de PyPI).

## Decisión

1. Usar **graphify** (`graphifyy[office]` 0.9.61, el extra `office` convierte los `.docx` como el artículo JIT)
   instalado **a nivel proyecto**: skill en `.claude/skills/graphify/`, referencia en `.claude/CLAUDE.md` y reglas
   de uso en el `CLAUDE.md` raíz. Todo esto se versiona.
2. Los hooks `PreToolUse` de `.claude/settings.json` invocan `graphify` **por PATH**, sin rutas absolutas,
   para que funcionen en Windows, Linux y macOS.
3. `graphify-out/` **no se versiona** (ya estaba en `.gitignore`): el grafo, la wiki y el HTML son derivados y se
   regeneran.
4. El índice es **completo sobre el conocimiento del proyecto**: código por AST (local, determinístico, sin LLM)
   más un paso semántico sobre documentos, papers y diagramas hecho por subagentes del propio asistente
   (sin API keys de terceros). Se genera también la **wiki** (`graphify-out/wiki/index.md`) como punto de entrada
   para navegar sin leer archivos crudos.
5. **`.graphifyignore`** excluye lo que no es conocimiento del proyecto o duplica otro índice:
   `.claude/` (archivos de la skill), `data/guias/` (corpus del RAG, ~25 000 líneas ya indexadas en ChromaDB) y
   `docs/capturas/` (capturas de pantalla, una llamada de visión por imagen).

## Alternativas consideradas

- **No usar herramienta (búsqueda con grep/lectura directa)** — funciona, pero cada exploración recorre muchos
  archivos para reconstruir relaciones que el grafo ya tiene.
- **Instalación global por usuario** — no queda compartida con el equipo ni versionada con el repositorio.
- **Versionar `graphify-out/`** — genera ruido en los diffs y conflictos de merge sobre un artefacto regenerable.
- **Solo código (`--code-only`)** — gratis, pero deja fuera el diseño, el artículo y el plan, que son justamente lo
  que se consulta al implementar las correcciones.
- **Indexar también las guías clínicas** — duplica el RAG y multiplica el costo de extracción semántica.

## Consecuencias

- Primer índice (2026-09-15): 761 nodos, 1421 relaciones, 63 comunidades, wiki de 73 artículos. Costo de la
  extracción semántica: ~472 000 tokens de subagentes (26 archivos). Benchmark de graphify: **6,9× menos tokens
  por consulta** que leer el corpus (~7 300 vs. ~50 700).
- Chequeo de integridad: 108 relaciones apuntan a librerías externas importadas por el código (`pathlib`,
  `pymongo`, …) que graphify no modela como nodos; no afectan las consultas sobre el proyecto.
- Orientación rápida: `graphify query`, `graphify path`, `graphify explain`, `graphify god-nodes` y la wiki.
- Cada integrante debe instalar la herramienta (`uv tool install "graphifyy[office]"`). Sin ella, los hooks fallan
  con un error **no bloqueante** en cada lectura/búsqueda del asistente.
- Mantenimiento: `graphify update .` refresca el **código** (local, sin costo). Si cambian documentos, `/graphify .
  --update` re-extrae solo los archivos modificados (usa la caché semántica y el manifiesto de `graphify-out/`).
  Los git hooks automáticos (`graphify hook install`) quedan disponibles pero no se instalan por defecto.
- El índice semántico no viaja con el repositorio: otra máquina que clone el repo parte sin caché y, si quiere los
  documentos en el grafo, paga de nuevo la extracción semántica.
- Los hooks agregan contexto obligatorio ("usar graphify antes de leer archivos") en cada `Read`/`Grep` del
  asistente; si resulta invasivo se puede quitar el hook sin desinstalar la skill.
- La versión instalada queda registrada en `.claude/skills/graphify/.graphify_version`; actualizar con
  `uv tool upgrade graphifyy` y `graphify install --project --platform claude`.
