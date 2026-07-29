# 🏎️ F1 Analyzer

Plataforma de análisis de telemetría de Fórmula 1 basada en datos de FastF1.

Permite analizar el ritmo de carrera (race pace) considerando factores reales como:
- degradación de neumáticos
- carga de combustible
- tráfico
- evolución de pista

## 🚀 Características

- Arquitectura modular de análisis (plugin-based)
- API REST para consultas dinámicas
- Ingesta de datos desde FastF1
- Métricas avanzadas:
  - Pace por stint
  - Degradación de neumáticos (avanzada)
  - Pace ajustado (sin tráfico + corrección de combustible)
  - Vueltas en tráfico (heatmap), con vueltas de SC/VSC/bandera señalizadas
    y orden de pilotos por clasificación final real

## 🧱 Stack tecnológico

- Backend: Django + Django REST Framework
- Base de datos: SQLite en desarrollo (por defecto) / PostgreSQL en staging-producción
- Procesamiento: Pandas / NumPy
- Datos: FastF1
- Frontend de módulos: D3.js (SVG embebido vía iframe)

## 📁 Estructura del proyecto

```
f1_analyzer/
│
├── core/                   # Modelos de dominio (Team, Driver, Race, RaceResult, Stint, Lap)
│   ├── admin.py
│   ├── models.py
│   ├── services/
│   │   └── traffic.py      # Cálculo de tráfico por vuelta (telemetría FastF1)
│   └── management/commands/load_fastf1.py
│
├── analytics/              # Motor de análisis (API + módulos)
│   ├── views.py
│   ├── urls.py
│   └── modules/
│       ├── base.py
│       ├── registry.py
│       ├── pace_by_stint.py
│       ├── laps_in_traffic.py
│       ├── tyre_degradation_advanced.py
│       └── pace_adjusted.py
│
├── dashboard/              # Frontend base (título + menú + páginas por módulo)
│   ├── views.py
│   ├── urls.py
│   ├── templates/dashboard/base.html
│   └── static/dashboard/modules/
│       ├── pace_by_stint.html
│       ├── laps_in_traffic.html
│       └── blank.html
│
├── config/                 # Configuración Django (settings, urls, wsgi/asgi)
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

## 🏁 Modelo Race: nomenclatura Rxx

`Race` identifica una sesión de tipo **Race** o **Sprint** de un Gran Premio, y se
indexa de forma única por `year` + `round_number` + `session_type`:

- `year`: temporada (ej: 2026).
- `round_number`: número de ronda del campeonato según FastF1 (`session.event.RoundNumber`).
- `gp_name`: nombre corto del Gran Premio (`session.event.EventName`), ej: "Hungarian Grand Prix".
- `session_type`: `R` (Race) o `S` (Sprint).
- `round_code` (propiedad): nomenclatura `Rxx` de la ronda, ej: `R01`, `R13`.

Esto permite cargar tanto la sesión Race como la Sprint de un mismo fin de semana
sprint sin que se pisen entre sí.

## 🏆 Resultado final (RaceResult)

Cada piloto tiene, por carrera, un `RaceResult` con la posición final tal como la
reporta FastF1 (`session.results`):

- `position`: posición numérica final. `None` cuando FastF1 no reporta un número
  (retirado, descalificado, no arrancó, etc.).
- `classified_position_raw`: código tal cual vino de FastF1 en esos casos
  (ej: `"R"`, `"D"`, `"W"`, `"E"`).
- `status`: motivo/descripción (ej: `"Finished"`, `"Retired"`).

Se usa para ordenar charts según la clasificación real (ej: heatmap de
`laps_in_traffic`) en vez de aproximarla por cantidad de vueltas completadas.

## 🖥️ Frontend base

```
GET /
```

Página con el título "F1 Analyzer" y un menú oculto (☰ Menú) con selectores de
**año**, **Gran Premio**, **tipo de sesión** (Race/Sprint) y **funcionalidad**
(módulo de analytics). Al presionar "Cargar", se resuelve el `race_id`
correspondiente y se carga en un iframe la página estática del módulo elegido.

Los módulos que todavía no tienen una página de visualización propia cargan una
página en blanco (el endpoint `/api/analysis` sigue disponible igual).

## ⚙️ Instalación

### 1. Clonar repositorio

```bash
git clone <repo-url>
cd f1_analyzer
```

### 2. Crear entorno virtual

```bash
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
```

Por defecto el proyecto usa SQLite y funciona sin configurar nada más.
Para usar PostgreSQL, define `DATABASE_URL` en `.env`:

```
DATABASE_URL=postgres://f1user:f1pass@localhost:5432/f1
```

### 5. Ejecutar migraciones

```bash
python manage.py migrate
```

### 6. Cargar datos desde FastF1

```bash
python manage.py load_fastf1 --year 2026 --race "Hungarian" --session R
python manage.py load_fastf1 --year 2026 --race "Hungarian" --session S   # sesión Sprint
```

> ⚠️ La primera ejecución puede tardar debido a la descarga de datos.
> El comando es idempotente: puede volver a ejecutarse sin duplicar vueltas.
> Solo se admiten sesiones **Race** y **Sprint** (las únicas con datos de vueltas
> relevantes para el ritmo de carrera); no se soportan Practice/Qualifying.
>
> Si venís de una versión anterior a la incorporación de `RaceResult`, corré
> `migrate` y volvé a ejecutar `load_fastf1` sobre las sesiones ya cargadas:
> es idempotente, así que solo completa los `RaceResult` faltantes sin
> duplicar nada.

### 7. Ejecutar servidor

```bash
python manage.py runserver
```

## 📡 API

### Endpoint principal

```
GET /api/analysis
```

### Parámetros

| Parámetro | Requerido | Descripción                       |
| --------- | --------- | ---------------------------------- |
| module    | Sí        | Módulo de análisis                 |
| race_id   | Sí        | ID de la carrera                   |
| driver    | No        | Código de piloto (repetible)       |
| team      | No        | Nombre del equipo (repetible)      |
| compound  | No        | Compuesto de neumático (repetible) |

### Ejemplo

```
http://127.0.0.1:8000/api/analysis?module=pace_by_stint&race_id=1
```

## 🧩 Módulos disponibles

### 🔹 pace_by_stint

- Ritmo promedio por stint
- Consistencia
- Degradación básica

### 🔹 laps_in_traffic

- Heatmap piloto x vuelta: % de cada vuelta con gap < 2s al auto de adelante
- Un piloto se marca "en tráfico" si supera el 33% de la vuelta en esa condición
- Requiere telemetría de FastF1 (`car_data`); se calcula en `load_fastf1` y se
  persiste en `Lap.traffic_pct` / `Lap.gap_to_front` (ver `core/services/traffic.py`)
- Las vueltas bajo SC / VSC / bandera no tienen `traffic_pct`, pero se señalizan
  en el heatmap con fondo amarillo y la sigla del estado más severo
  (`Y`, `SC`, `VSC`, `R` — ver `Lap.track_status_label`) en vez de quedar en blanco
- Filas ordenadas por posición final real (`RaceResult.position`); si la sesión
  no fue reimportada después de agregarse `RaceResult`, cae a un orden
  aproximado por cantidad de vueltas completadas
- Página propia: `dashboard/static/dashboard/modules/laps_in_traffic.html`

### 🔹 tyre_degradation_advanced

- Segmentación del stint (warmup, estable, drop-off)
- Detección de "cliff"
- Curva de degradación real

### 🔹 pace_adjusted

- Corrección por combustible
- Filtrado de tráfico
- Corrección por evolución de pista
- Pace en aire limpio

## 🧠 Roadmap

- [ ] Simulador de estrategia de carrera
- [ ] Análisis por sectores
- [ ] Integración con telemetría completa
- [ ] Frontend interactivo (React + ECharts)
- [ ] Cache con Redis
- [ ] Despliegue con Docker

## ⚠️ Notas

- FastF1 usa cache local → se ignora en Git (`cache/`)
- SQLite es suficiente para desarrollo; para datasets grandes se recomienda PostgreSQL

## 🧪 Desarrollo

Para agregar un nuevo módulo de análisis:

1. Crear archivo en `analytics/modules/`
2. Heredar de `BaseAnalysisModule`
3. Implementar `get_queryset` y `transform`
4. Registrar en `analytics/modules/registry.py`
5. Si el módulo tiene página propia, agregarla en
   `dashboard/static/dashboard/modules/` y registrar su ruta en
   `MODULE_PAGES` (y su label en `MODULE_LABELS`) dentro de `dashboard/views.py`
   — si no, cae al placeholder `blank.html`.

Ejecutar los tests:

```bash
python manage.py test
```

## 📄 Licencia

MIT