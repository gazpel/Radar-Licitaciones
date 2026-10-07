# Radar de Licitaciones para PyMEs — Pruebas de concepto

> **Rama `pruebas-de-concepto`.** Este código corresponde a la **primera iteración** del proyecto y fue
> **generado con apoyo de IA (Claude, Anthropic)** para validar la factibilidad técnica en la Evaluación 1,
> tal como se declara en el informe (capítulo 6 y Anexo 2) y en el tablero AI Compass.
> El desarrollo del proyecto se reconstruye desde cero en la rama `main`.

Proyecto semestral TAVI 2026-2 (USACH). Asistente que revisa las licitaciones de Mercado Público
de un rubro (caso de estudio: colchonería), lee las bases y entrega requisitos, documentos,
garantías, plazos y criterios de evaluación, citando la página de donde sale cada dato.

## Qué se probó

| Prueba | Resultado |
|---|---|
| Consulta a la API de Mercado Público (03/10/2026) | 3 licitaciones de colchones activas |
| Extracción con Mistral 7B sobre bases sintéticas | 7 hallazgos, 7/7 citas verificadas, instrucción maliciosa ignorada |
| Extracción con IBM Granite 4.2 8B (razonamiento desactivado) | 9 hallazgos, 8/9 citas verificadas (una paráfrasis detectada por la verificación) |

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
python -m scripts.demo buscar                                    # licitaciones activas del rubro
python -m scripts.demo extraer data/bases/prueba_sintetica.pdf   # extracción de unas bases
uvicorn app.main:app --reload                                    # API web en http://localhost:8000/docs
```

## Estructura

- `app/mercadopublico.py` — cliente de la API de Mercado Público
- `app/pdf.py` — lectura de PDF por página
- `app/llm.py` — acceso al LLM (Ollama local)
- `app/extraccion.py` — extracción estructurada con verificación de citas
- `app/main.py` — API web (FastAPI)
- `scripts/demo.py` — mini-demo por consola
