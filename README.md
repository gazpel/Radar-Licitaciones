# Radar de Licitaciones para PyMEs

> **Rama `main`: desarrollo del MVP.** El código es **generado con apoyo de IA (Claude, Anthropic)**,
> con la planificación, las decisiones y la revisión a cargo del autor, tal como se declara en el informe
> (distribución de tareas) y en el tablero AI Compass. La rama `pruebas-de-concepto` conserva la versión
> de la Evaluación 1.

Proyecto semestral TAVI 2026-2 (USACH). Asistente que revisa las licitaciones de Mercado Público
de un rubro (caso de estudio: colchonería), lee las bases y entrega requisitos, documentos,
garantías, plazos y criterios de evaluación, citando la página de donde sale cada dato.

## Avance y pruebas

| Prueba | Resultado |
|---|---|
| Consulta a la API de Mercado Público (03/10/2026) | 3 licitaciones de colchones activas |
| Extracción con Mistral 7B sobre bases sintéticas | 7 hallazgos, 7/7 citas verificadas, instrucción maliciosa ignorada |
| Extracción con IBM Granite 4.2 8B (razonamiento desactivado) | 9 hallazgos, 8/9 citas verificadas (una paráfrasis detectada por la verificación) |
| Ingesta con filtro por perfil (Sprint 1, 14/11/2026) | 5.266 activas → 6 candidatas por nombre → 5 relevantes; 2.ª ejecución sin duplicados |
| Extracción vía LangChain (`ChatOllama`) con Mistral 7B | 11 hallazgos, 11/11 citas verificadas |
| Descarga automática de bases desde la ficha web (spike) | No viable: la lista de adjuntos está protegida con reCAPTCHA → carga asistida |

Las bases usadas (`data/bases/prueba_sintetica.pdf`) son **ficticias**: un PDF de 4 páginas creado para la
prueba, con una instrucción maliciosa escondida para probar los guardrails. Los resultados están en
`data/resultados/`.

## Requisitos

- Python 3.12 o superior
- [Ollama](https://ollama.com) con un modelo local (`ollama pull granite4.2:8b` o `ollama pull mistral`)
- Ticket de la API de Mercado Público ([chilecompra.cl/api](https://www.chilecompra.cl/api/))

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # y completar MP_TICKET
```

En `.env`, `LLM_MODEL` elige el modelo y `LLM_THINK=false` desactiva el modo razonamiento de Granite.

## Uso

```bash
python -m scripts.ingesta                                        # trae, filtra y guarda las licitaciones del perfil
python -m scripts.ingesta --perfil                               # recarga el perfil desde data/empresa_colchoneria.json
uvicorn app.main:app --reload                                    # API web en http://localhost:8000/docs
python -m scripts.demo extraer data/bases/prueba_sintetica.pdf   # extracción de unas bases
pytest                                                           # pruebas automáticas
```

`scripts/ingesta_diaria.bat` ejecuta la ingesta y guarda el resultado en `data/logs/`; se puede programar
con el Programador de tareas de Windows.

## Estructura

- `app/db.py` — base de datos SQLite (SQLModel): empresa, licitaciones, ingestas y hallazgos
- `app/filtros.py` — filtro por reglas en dos etapas (nombre; rubro, región y monto), con el motivo de cada decisión
- `app/ingesta.py` — ingesta: trae, filtra y guarda sin duplicar
- `app/texto.py` — normalización de texto (tildes, mayúsculas, signos)
- `app/mercadopublico.py` — cliente de la API de Mercado Público (pausa y reintentos ante el error 429)
- `app/pdf.py` — lectura de PDF por página
- `app/llm.py` — acceso al LLM con LangChain (`ChatOllama`, local)
- `app/extraccion.py` — extracción estructurada con verificación de citas
- `app/main.py` — API web (FastAPI)
- `scripts/demo.py` — mini-demo por consola (Evaluación 1)
- `scripts/ingesta.py` — ingesta por consola
- `data/empresa_colchoneria.json` — perfil **sintético** de la empresa del caso de estudio
- `tests/` — pruebas del filtro y de la ingesta (con una API falsa, sin internet)
- `docs/diagramas/` — diagramas UML de casos de uso y de secuencia (draw.io)
