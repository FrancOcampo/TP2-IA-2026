<!--
Contenido para el trabajo de INVESTIGADORES CONAIISI 2026, siguiendo
"Formato_Investigadores.doc" (plantilla A4, 2 columnas). Este archivo es SOLO
EL TEXTO: pasarlo al .doc/.docx oficial (o a la plantilla
"Pautas para autores CONAIISI A4 – Plantilla.dotx" del sitio del congreso)
respetando las indicaciones tipográficas entre paréntesis en cada bloque.

Checklist de maquetado en Word (no lo hace este Markdown):
- Página A4. Área de impresión 17,5 cm de ancho x 22,54 cm de alto.
- Dos columnas de 8,25 cm de ancho, con 8 mm de espacio entre ellas — TODO
  el cuerpo (texto, figuras, tablas), excepto título y autores.
- Título principal: empieza a 3,49 cm del borde superior de la hoja
  (solo primera página), centrado. Segunda página en adelante: margen
  superior e inferior de 3 cm.
- Fuente Times (o Times New Roman / Times Roman si no está disponible) en
  todo el documento; tamaños indicados en cada bloque.
- Cuerpo de texto: Times 10 pts, interlineado simple, sangría de 5 mm en
  cada párrafo, SIN línea en blanco entre párrafos, justificado en ambos
  márgenes.
- Dos líneas en blanco después del título, y dos líneas en blanco después
  de los datos de autor / antes del texto principal (y luego del Resumen).
- Extensión recomendada: 7 a 10 páginas totales.
- Figuras y tablas numeradas por separado ("Figura 1. ...", "Tabla 1. ...");
  pies/títulos en Helvética (o Sans-Serif) 9 pts negrita, primera letra
  mayúscula solamente. Título de tabla arriba, pie de figura abajo.
- Notas al pie: Times 9 pts, interlineado simple.
- Citas en el texto entre corchetes: [1], [2-4], [2, 5].
- Referencias: Times 9 pts, interlineado simple, al final.
- VERSIÓN DE EVALUACIÓN (doble ciego): el artículo NO debe contener nombres
  de autores, filiaciones institucionales ni ningún dato que revele la
  identidad de los autores. Esos datos se piden recién en la versión final
  (si el trabajo es aceptado). Enviar en ambas instancias en formato PDF.
-->

# Título Principal
<!-- Times, 14 pts, negrita, centrado. Mayúscula inicial en sustantivos,
     pronombres, verbos, adjetivos y adverbios (no en artículos,
     preposiciones ni conjunciones coordinantes, salvo que abran el
     título). Dos líneas en blanco después del título. -->

Soporte a la Decisión Clínica en Diabetes Tipo 2 Mediante un Sistema Multi-Agente con LLM, RAG y Análisis Determinístico de Umbrales

---

# Autor(es) y Filiaciones Institucionales
<!-- Times, 12 pts, estilo normal (SIN negrita), centrado debajo del
     título. Con autores múltiples: formato de doble/triple columna, con
     la filiación de cada autor centrada debajo de su nombre, en cursiva,
     e incluyendo el email. Dos líneas en blanco después de esta sección. -->

<<Nombre y apellido — Autor 1>>          <<Nombre y apellido — Autor 2>>

*<<Filiación institucional — Autor 1>>*          *<<Filiación institucional — Autor 2>>*

<<email Autor 1>>          <<email Autor 2>>

> **Nota (doble ciego):** los artículos remitidos para evaluación no deben
> contener nombres de autores, filiaciones institucionales ni ningún dato
> que permita identificar a los autores. Completar esta sección solo en la
> versión final (camera ready), si el trabajo resulta aceptado. Enviar en
> ambas instancias en formato **PDF**.

---

# Resumen
<!-- Título "Resumen": Times 12 pts, negrita, centrado en relación con la
     columna, solo inicial mayúscula. Cuerpo: Times 10 pts, CURSIVA,
     interlineado simple, JUSTIFICADO, ubicado arriba de la columna
     izquierda debajo de los datos de autor. Extensión máxima: 7,6 cm de
     largo (aprox. 100-120 palabras) — no es el mismo texto que el
     abstract extendido de la versión estudiantil. Dos líneas en blanco
     después del Resumen. -->

*Este trabajo presenta un sistema multi-agente de soporte a la decisión
clínica para el seguimiento de pacientes con diabetes tipo 2. Un
Orquestador infiere la intención del médico y coordina, vía LangGraph, un
Agente Monitor —que ejecuta herramientas determinísticas de cálculo
estadístico y detección de umbrales ADA— y un Agente Clínico, que
interpreta los hallazgos mediante RAG sobre guías clínicas y el historial
acumulado del paciente en MongoDB. Un loop de refinamiento acotado permite
volver a pedir análisis adicional. El sistema, implementado end-to-end y
evaluado con una batería de casos happy/edge/adversarial, muestra que
separar cálculo determinístico e interpretación en lenguaje natural produce
un sistema auditable y reproducible en su capa numérica, útil como soporte
sin emitir diagnósticos.*

---

# 1. Introducción
<!-- Título de primer nivel: Times 12 pts, negrita, primera inicial
     mayúscula, alineado a la izquierda, 24 pts de espacio anterior y
     12 pts posterior. -->

El seguimiento de pacientes con diabetes tipo 2 requiere el monitoreo
continuo de múltiples métricas clínicas cuya interpretación conjunta es
compleja y propensa a errores por omisión. Un médico que atiende a decenas
de pacientes crónicos necesita identificar rápidamente tendencias
preocupantes, valores fuera de rango y contexto clínico relevante antes de
cada consulta. Sin herramientas de soporte, ese análisis se realiza
manualmente a partir de registros dispersos, con riesgo de pasar por alto
señales de alerta — por ejemplo, un episodio puntual de hipoglucemia que un
promedio mensual normal termina ocultando.

La diabetes es, además, una condición con umbrales de diagnóstico y
control definidos con precisión por la American Diabetes Association
(ADA), lo que la vuelve un dominio propicio para combinar reglas
determinísticas (auditables, reproducibles) con razonamiento en lenguaje
natural (flexible, capaz de contextualizar). Esa combinación es
precisamente lo que motiva este trabajo: ¿cómo estructurar un sistema que
use un modelo de lenguaje (LLM) para lo que un LLM hace bien — inferir
intención, interpretar hallazgos, redactar en lenguaje clínico — sin
delegarle el cálculo numérico, que debe ser exacto y verificable?

Se propone un sistema multi-agente orientado al soporte clínico en el
seguimiento de pacientes con diabetes tipo 2. El sistema recibe el
historial de métricas clínicas de un paciente y lo analiza de forma
autónoma en dos etapas coordinadas por un agente orquestador: un Agente
Monitor que procesa los datos mediante herramientas de cálculo
determinístico para detectar anomalías y violaciones de umbral, y un
Agente Clínico que interpreta esos hallazgos consultando el historial
acumulativo del paciente y guías clínicas oficiales mediante RAG. El
resultado es un reporte estructurado con alertas, tendencias y preguntas
de seguimiento sugeridas, concebido estrictamente como soporte a la
decisión médica: el sistema no emite diagnósticos, y toda salida incluye
esa aclaración explícita.

El resto del trabajo se organiza así: la sección 2 describe la
arquitectura, los agentes, sus herramientas y la evaluación realizada; la
sección 3 discute trabajos relacionados; y la sección 4 cierra con las
conclusiones y líneas futuras.

# 2. Arquitectura del Sistema

El sistema implementa una arquitectura multi-agente orquestada con
**LangGraph**, elegido porque el flujo requiere ciclos condicionales entre
agentes (un loop de refinamiento, descripto más abajo) que un
encadenamiento lineal no puede expresar. **LangChain** provee las
integraciones con los servicios externos (LLM, embeddings, vector store).
Un estado compartido (`AgentState`, tipado con Pydantic) fluye entre los
nodos del grafo.

La arquitectura distingue tres actores: el médico, que inicia la
interacción; un **Agente Orquestador**, que decide cómo se procesa cada
consulta; y dos agentes especializados con foco distinto, el **Agente
Monitor** (¿qué dicen los números?) y el **Agente Clínico** (¿qué
significan?). El Orquestador no expone comandos explícitos: **infiere la
intención** a partir del mensaje del médico y del estado de la sesión
(¿hay un reporte previo?, ¿es una pregunta de seguimiento?, ¿se pide
reiniciar?) y enruta en consecuencia. Ante una consulta nueva ejecuta el
flujo completo Monitor → Clínico; ante una pregunta de seguimiento sobre
un reporte ya generado, deriva directamente al Clínico sin recalcular.

Tras la interpretación del Clínico, el sistema evalúa si la información
disponible alcanza para producir una respuesta de soporte, mediante una
señal explícita (`information_sufficient`). Si no alcanza, el control
vuelve al Monitor para ampliar el análisis — un **loop de refinamiento**
acotado a un máximo de 3 iteraciones (guardrail), que permite al sistema
corregir su propio recorrido en lugar de entregar una respuesta
incompleta.

Cada agente especializado consulta fuentes de datos propias, lo que
delimita su responsabilidad: el Monitor trabaja sobre los datos crudos del
historial clínico (EHR); el Clínico trabaja sobre conocimiento acumulado —
el historial de sesiones previas del paciente (MongoDB) y guías clínicas
de referencia indexadas para búsqueda semántica (ChromaDB). Esta
separación evita que el mismo agente mezcle cálculo exacto con
interpretación, y hace auditable cada paso: los logs registran, por
`patient_id`/`metric`/`timerange`, qué tool se invocó y con qué resultado.

## 2.1. Agentes y Herramientas
<!-- Título de segundo nivel: Times 11 pts, negrita, alineado a la
     izquierda, sin sangría, 6 pts de espacio anterior y posterior. -->

Los dos agentes especializados implementan el patrón **ReAct** (razonar →
actuar → observar) sobre modelos servidos vía API (Groq, `llama-3.3-70b`,
con branch alternativo a Gemini), bindeados a herramientas LangChain.
Cuando no hay credenciales de LLM disponibles, cada agente cae a un
**modo de fallback determinístico** que ejecuta las mismas tools sin
pasar por el modelo — decisión de diseño que permite levantar y probar el
sistema completo sin infraestructura externa, y que funciona además como
base de comparación para detectar si una corrida de evaluación
efectivamente usó el LLM o degradó al fallback.

**Agente Monitor.** No interpreta clínicamente: solo calcula. Sus
herramientas son **determinísticas** — dado el mismo input, siempre el
mismo output — y se invocan por `patient_id` (el LLM nunca transporta
arrays de datos, solo decide *qué* calcular y sobre *qué ventana
temporal*):

- `load_patient_data(patient_id)`: carga la serie completa del historial
  clínico.
- `calculate_stats(patient_id, metric, timerange)`: estadísticas
  clínicamente accionables por métrica — último valor, media, mínimo,
  máximo, delta y dirección (subiendo/bajando/estable, con banda muerta
  del 3 %). Se priorizaron los extremos frente a medidas como desvío
  estándar porque exponen eventos que la media diluye, como una
  hipoglucemia puntual en un promedio normal.
- `detect_threshold_violations(patient_id, metric, timerange)`: compara
  cada valor contra los umbrales ADA y devuelve alertas con fecha,
  severidad (moderada/severa) y descripción. Cubre tanto
  **hiperglucemia** (glucosa en ayunas ≥ 126 mg/dL, HbA1c ≥ 6.5 %,
  postprandial ≥ 200 mg/dL en el nivel severo) como **hipoglucemia**
  (< 70 mg/dL moderada, < 54 mg/dL severa) — esta última con frecuencia
  ausente en sistemas de monitoreo que solo vigilan valores altos.
- `get_medication_schedule(patient_id)`: medicación activa con dosis y
  frecuencia.

**Agente Clínico.** Recibe el output estructurado del Monitor e
interpreta los hallazgos, incorporando historial y guías:

- `get_patient_history(patient_id)`: recupera el documento completo del
  paciente desde MongoDB (diagnósticos, comorbilidades, medicación base,
  sesiones anteriores).
- `compare_with_previous_sessions(patient_id, metric, n_sessions)`:
  compara el valor actual con sesiones previas y clasifica la evolución
  (mejorando/estable/deteriorando), forzando un razonamiento longitudinal
  explícito y auditable.
- `search_clinical_guidelines(condition, value, context)`: búsqueda
  semántica (RAG) sobre ChromaDB, indexado con embeddings
  `nomic-embed-text`, contra guías de la ADA, la Sociedad Argentina de
  Diabetes y el Ministerio de Salud de la Nación. El parámetro `context`
  incorpora información clínica adicional que el médico ingresa en
  lenguaje libre (por ejemplo, una comorbilidad), lo que orienta la
  búsqueda.
- `update_patient_history(patient_id, session_data)`: persiste la sesión
  actual como un nuevo nodo del historial, **solo con confirmación
  explícita del médico** — el reporte generado por el agente no se
  registra automáticamente, para no introducir ruido no revisado en la
  base que alimenta sesiones futuras.

El historial del paciente se modela como **un documento por paciente en
MongoDB** (recuperación exacta por identificador) en lugar de indexarlo
también con RAG: cuando el Clínico necesita el historial, lo necesita
completo, y fragmentarlo introduciría el riesgo de recuperar fragmentos de
sesiones que contradicen el estado actual — o de otro paciente con perfil
similar. RAG queda reservado exclusivamente para las guías clínicas, donde
sí tiene sentido recuperar el fragmento más relevante entre un corpus
extenso y relativamente estático.

## 2.2. Interfaz, Observabilidad y Modo de Operación

La interacción del médico se implementó en una **interfaz web con
Gradio**, con una pestaña de *Consulta clínica* (selección de paciente,
perfil resumido, campos opcionales de orientación del análisis y contexto
clínico adicional, reporte con alertas y tendencias, y un chat de
seguimiento acotado al paciente activo) y una pestaña de *Observabilidad*
que expone, en modo desarrollo, la traza estructurada del grafo
(`node_start`, `routing`, y — en modo completo — `llm_*`/`tool_*` con
conteo de tokens y nombre de la herramienta invocada). Toda ejecución se
registra en consola y en `logs/agent.jsonl`, integrable con LangSmith.

Un aspecto operativo relevante para la reproducibilidad del trabajo es el
**modo básico**: sin `GROQ_API_KEY` ni servicios externos, el grafo
completo corre igual sobre fallbacks determinísticos y un fixture local de
cuatro pacientes sintéticos, cada uno ejercitando un caso distinto
(control adecuado, tendencia ascendente, episodio de hipoglucemia, datos
insuficientes). Esto permite validar la integridad del pipeline — mas no
la calidad del razonamiento del LLM — sin depender de infraestructura
externa, algo poco frecuente en sistemas basados en agentes LLM y que
facilitó la evaluación continua durante el desarrollo.

## 2.3. Evaluación

La estrategia de testing se organizó **por objetivo** en lugar de por la
taxonomía habitual unitario/integración, porque lo que interesa validar en
un sistema de este tipo es de naturaleza distinta según la capa: que las
**herramientas** calculen lo correcto (determinístico), que el **grafo**
coordine bien a los agentes (plomería, con un modo determinístico forzado
para el gate de integración continua y un modo estocástico con LLM real
para verificar el cableado), y que el **resultado final producido por la
IA** sea de buena calidad (inherentemente cualitativo).

Para este último eje se construyó un conjunto de 9 casos distribuidos en
tres categorías — *happy path*, *edge cases* y *adversarial* —
ejecutados con el LLM real mediante un script dedicado que vuelca un
artefacto con el resultado esperado frente al obtenido, consultable desde
la propia interfaz para comparación manual. Cada corrida queda etiquetada
como `ok`, `degraded` (el LLM falló y el grafo cayó al fallback
determinístico, por lo que la salida no refleja al modelo) o `error`,
distinción que resultó necesaria para no puntuar como fallo del
razonamiento algo que en realidad fue un problema de disponibilidad del
proveedor de LLM. Este esquema de comparación esperado-vs-obtenido
constituye una base directa para incorporar, como trabajo futuro, una capa
de evaluación automática tipo *LLM-as-judge*.

# 3. Trabajos Relacionados

El uso de LLM en salud ha sido explorado principalmente en dos
direcciones: modelos de propósito general evaluados sobre conocimiento
médico, como Med-PaLM, que muestran que un LLM puede responder con calidad
clínica aceptable preguntas de examen y consultas abiertas [1], y sistemas
de soporte a la decisión que combinan LLM con fuentes de conocimiento
externas para reducir alucinaciones y anclar las respuestas en evidencia
verificable. Este trabajo se ubica en la segunda categoría: en lugar de
confiar en el conocimiento paramétrico del modelo, ancla cada
interpretación clínica en fragmentos recuperados de guías oficiales.

La técnica de **Retrieval-Augmented Generation** (RAG), formalizada por
Lewis et al. [2], es la base de esa estrategia de anclaje: en vez de
depender de lo que el modelo "recuerda" de su entrenamiento, se recupera
contexto relevante de un corpus controlado (en este caso, guías
ADA/SAD/MSAL) y se lo incorpora al prompt antes de generar la respuesta. A
diferencia de aplicaciones típicas de RAG que indexan todo el conocimiento
disponible, este trabajo aplica RAG selectivamente — solo sobre las guías
clínicas, no sobre el historial del paciente —, lo que representa una
decisión de diseño explícita frente al patrón "indexar todo" habitual en
sistemas de recuperación aumentada.

En cuanto a la coordinación de agentes, el patrón **ReAct** (razonamiento
intercalado con acción) de Yao et al. [3] es el que estructura el loop
interno de cada agente especializado, y la literatura reciente sobre
sistemas **multi-agente** con LLM —por ejemplo, marcos como AutoGen
[4]— documenta beneficios similares a los observados en este trabajo al
dividir un problema complejo entre agentes con roles y fuentes de datos
delimitadas, en contraposición a un único agente monolítico con todas las
herramientas disponibles. La diferencia principal respecto de esos marcos
generales es que aquí la división de responsabilidades no es solo
organizativa sino epistemológica: el Monitor encapsula todo el cálculo
determinístico y el Clínico toda la interpretación, de forma que el
razonamiento estocástico del LLM nunca participa en una cuenta que deba
ser exacta y auditable — un requisito poco negociable en un dominio
clínico.

# 4. Conclusión y Trabajos Futuros

Este trabajo presentó un sistema multi-agente de soporte a la decisión
clínica para el seguimiento de pacientes con diabetes tipo 2, cuya
decisión de diseño central es separar estrictamente el cálculo
determinístico (a cargo de herramientas puras, testeables con listas de
valores) de la interpretación en lenguaje natural (a cargo del LLM),
coordinados por un agente orquestador que enruta por inferencia de
intención y gestiona un loop de refinamiento acotado. Esa separación
resultó clave para lograr un sistema auditable en su capa numérica — cada
estadística y cada alerta son reproducibles y verificables — sin resignar
la flexibilidad interpretativa que aporta un LLM al contextualizar un
hallazgo contra guías clínicas y el historial longitudinal del paciente.

Entre las limitaciones del trabajo se destacan: el alcance del historial
de métricas se restringió a mediciones puntuales del EHR, dejando el
monitoreo continuo de glucosa (CGM) como extensión definida pero no
implementada; el enrutamiento del Orquestador y la detección de
"información insuficiente" del Clínico dependen hoy de heurísticas sobre
texto libre del LLM, con el riesgo de fragilidad que eso implica si el
modelo cambia de fraseo; y la evaluación de calidad del razonamiento sigue
siendo mayormente manual.

Como trabajos futuros se plantea: (i) migrar las decisiones de control
(enrutamiento, señal de información insuficiente) de heurísticas de texto
libre a salida estructurada del LLM; (ii) incorporar una capa de
evaluación automática tipo LLM-as-judge que puntúe *faithfulness* del
reporte clínico contra los fragmentos RAG recuperados, para detectar
alucinaciones de forma sistemática y no solo por revisión manual; (iii)
implementar el nodo de persistencia de sesión que hoy está definido en el
diseño pero pendiente de integración en el grafo; y (iv) incorporar el
análisis de datos de monitoreo continuo de glucosa (CGM) como fuente
adicional para pacientes que dispongan del dispositivo.

# Agradecimientos
<!-- Times, 12 pts, negrita, alineado a la izquierda, 24 pts espacio
     anterior y 12 pts posterior. De corresponder: indicar Institución u
     Organismo que respalda el trabajo (nombre completo y siglas). -->

[Completar si corresponde.]

# Referencias
<!-- Times, 9 pts, interlineado simple. Citar en el texto entre corchetes,
     p. ej. [2-4], [2, 5], [1]. -->

[1] Singhal, K., Azizi, S., Tu, T., et al. (2023). "Large language models
encode clinical knowledge." *Nature*, 620, 172–180.

[2] Lewis, P., Perez, E., Piktus, A., et al. (2020). "Retrieval-Augmented
Generation for Knowledge-Intensive NLP Tasks." *Advances in Neural
Information Processing Systems (NeurIPS)*, 33.

[3] Yao, S., Zhao, J., Yu, D., et al. (2022). "ReAct: Synergizing
Reasoning and Acting in Language Models." *arXiv preprint
arXiv:2210.03629*.

[4] Wu, Q., Bansal, G., Zhang, J., et al. (2023). "AutoGen: Enabling
Next-Gen LLM Applications via Multi-Agent Conversation." *arXiv preprint
arXiv:2308.08155*.

[5] American Diabetes Association. (2024). "Standards of Care in
Diabetes—2024." *Diabetes Care*, 47 (Supplement 1).

[6] Sociedad Argentina de Diabetes (SAD). Guías de práctica clínica en
diabetes mellitus tipo 2.

[7] Ministerio de Salud de la Nación Argentina. Guía de práctica clínica
sobre diagnóstico y tratamiento de diabetes mellitus tipo 2.

[8] LangChain AI. (2024). "LangGraph Documentation."
https://langchain-ai.github.io/langgraph/
