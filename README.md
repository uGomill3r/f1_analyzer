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

## 🧱 Stack tecnológico

- Backend: Django + Django REST Framework
- Base de datos: SQLite en desarrollo (por defecto) / PostgreSQL en staging-producción
- Procesamiento: Pandas / NumPy
- Datos: FastF1

## 📁 Estructura del proyecto

```
f1_analyzer/
│
├── core/                   # Modelos de dominio (Team, Driver, Race, Stint, Lap)
│   ├── admin.py
│   ├── models.py
│   └── management/commands/load_fastf1.py
│
├── analytics/              # Motor de análisis (API + módulos)
│   ├── views.py
│   ├── urls.py
│   └── modules/
│       ├── base.py
│       ├── registry.py
│       ├── pace_by_stint.py
│       ├── tyre_degradation_advanced.py
│       └── pace_adjusted.py
│
├── config/                 # Configuración Django (settings, urls, wsgi/asgi)
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

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
```

> ⚠️ La primera ejecución puede tardar debido a la descarga de datos.
> El comando es idempotente: puede volver a ejecutarse sin duplicar vueltas.

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

Ejecutar los tests:

```bash
python manage.py test
```

## 📄 Licencia

MIT
