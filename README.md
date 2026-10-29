# Gonzarun · Running Lab

Dashboard de Streamlit para analizar tu historial de carrera, récords, tendencias y recorridos GPS. El flujo principal parte directamente del **ZIP completo que descargas desde Strava**: no tienes que descomprimirlo manualmente ni ejecutar el conversor FIT por separado.

## Flujo de datos

1. Desde Strava, solicita la exportación completa de tu cuenta y descarga el ZIP cuando recibas el correo.
2. En la barra lateral de Streamlit, sube ese ZIP y pulsa **Procesar ZIP de Strava**.
3. El importador localiza `activities.csv` y los archivos de track en `activities/`.
4. Descomprime dentro del proceso los tracks `.fit.gz`, `.gpx.gz` y `.tcx.gz`; también acepta `.fit`, `.gpx` y `.tcx` sin compresión.
5. Lee los FIT para extraer cada registro con GPS y métricas disponibles (hora, latitud, longitud, altitud, distancia acumulada, frecuencia cardíaca, cadencia, velocidad, potencia y temperatura). Se incluye la corrección defensiva para los campos temporales que algunas exportaciones FIT entregan como tuplas.
6. Normaliza los datos en `data/processed/activities.csv` y `data/processed/activity_points.csv` y los importa a SQLite.
7. Streamlit consulta la base de datos; no vuelve a procesar los archivos FIT al cambiar de pestaña o filtro.

El ZIP original se guarda en `data/strava_export.zip`. Los CSV intermedios y un manifiesto de procesamiento quedan en `data/processed/`. El programa **no extrae ciegamente todo el ZIP al disco**: lee solo el CSV de actividades y los tracks pertinentes, por lo que evita descomprimir fotos y otros contenidos que no hacen falta para el dashboard.

Strava suele incluir `activities.csv` y una carpeta `activities/` con archivos de actividad en su formato original, a menudo `.fit.gz`; puede haber GPX o TCX en exportaciones mixtas. Véase la guía oficial: https://support.strava.com/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export

## Instalación en macOS

Desde Terminal, entra en esta carpeta:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # solo si todavía no existe .env
```

Si el archivo `.env` ya existe, no hace falta sustituirlo; comprueba que contenga al menos:

```dotenv
STRAVA_ZIP_PATH=data/strava_export.zip
ACTIVITIES_CSV=data/processed/activities.csv
POINTS_CSV=data/processed/activity_points.csv
DATABASE_URL=
```

Arranca el dashboard:

```bash
streamlit run app.py
```

### Compartir la aplicación

Para crear un paquete limpio para otra persona, sin incluir tu base de datos, tu ZIP de Strava ni el entorno virtual:

```bash
./scripts/package_app.sh
```

El archivo `gonzarun_dashboard_app.zip` se crea junto a la carpeta del proyecto. La persona que lo reciba debe:

1. Descomprimirlo.
2. Crear un entorno virtual e instalar `requirements.txt`.
3. Ejecutar `streamlit run app.py`.
4. Subir su propio ZIP completo de Strava desde **Importar datos**.

El paquete no contiene datos personales del exportador original.

En la sección **Importar datos**, elige el ZIP que descargaste de Strava y pulsa **Procesar ZIP de Strava**. La aplicación conserva una copia en `data/strava_export.zip`, procesa el archivo dentro de la propia app y refresca las estadísticas automáticamente. Los ZIP grandes pueden tardar varios minutos. El límite de subida de Streamlit se ha elevado a 2 GB en `.streamlit/config.toml`; el límite real también depende de la memoria disponible en el equipo.

## Procesamiento por terminal

También puedes colocar el archivo ZIP en `data/strava_export.zip` y ejecutar:

```bash
source .venv/bin/activate
python -m running_dashboard.ingest --zip data/strava_export.zip
```

Forzar que se vuelva a procesar el ZIP y se reimporten los datos:

```bash
python -m running_dashboard.ingest --zip data/strava_export.zip --force
```

Si ya dispones de los CSV procesados y solo quieres importar esos archivos, usa:

```bash
python -m running_dashboard.ingest --csv-only \
  --activities data/processed/activities.csv \
  --points data/processed/activity_points.csv
```

## Actualización periódica desacoplada

La actualización automática no puede pedir por sí sola una nueva exportación a Strava: hay que descargar un ZIP nuevo desde Strava y reemplazar el archivo guardado. Una vez actualizado `data/strava_export.zip`, el importador puede programarse sin abrir Streamlit. Ejemplo de `cron` diario a las 06:00:

```cron
0 6 * * * /RUTA/ABSOLUTA/gonzarun_dashboard/scripts/refresh_db.sh >> /RUTA/ABSOLUTA/gonzarun_dashboard/data/ingest.log 2>&1
```

Si el ZIP no ha cambiado, un hash SHA-256 permite saltarse la extracción y conversión de tracks. Si cambia, se reconstruyen los CSV normalizados y se sincroniza la base de datos. El dashboard sigue siendo un proceso independiente.

## Base de datos

- Por defecto usa SQLite en `data/running.db`, sin servidor adicional.
- Para PostgreSQL, instala `pip install 'psycopg[binary]'` y configura `DATABASE_URL` en `.env`, por ejemplo:

```dotenv
DATABASE_URL=postgresql+psycopg://usuario:contraseña@host:5432/gonzarun
```

Tanto el dashboard como el importador utilizan la misma configuración de base de datos.

## Qué se puede extraer

- `activities.csv`: nombre, fecha, tipo, distancia, duración, desnivel y las demás métricas que Strava haya incluido en el CSV.
- FIT: puntos GPS y campos disponibles en el registro, por ejemplo altitud, distancia, timestamp, FC, cadencia, velocidad, potencia y temperatura.
- GPX/TCX: coordenadas, timestamps y altitud; otros campos dependen del contenido del archivo.

Los campos que no existan en el archivo original se dejan vacíos. No se infieren métricas fisiológicas ausentes. Los archivos con formato inválido se registran en la salida de importación; el resto del archivo puede seguir procesándose.

## Dashboard

- Resumen: volumen, duración, desnivel, ritmo, frecuencia cardíaca, calorías y esfuerzo relativo.
- Evolución: volumen semanal/mensual, consistencia y tendencias.
- Récords: mejores actividades y segmentos GPS cuando hay distancia acumulada y marcas de tiempo suficientes.
- Explorador GPS: selector por nombre y fecha, recorrido en mapa, mapa de altitud, perfil de elevación e inspección de steps con marcadores espaciados por defecto.
- Datos: tabla de actividades y métricas disponibles.

## Estructura

```text
app.py
running_dashboard/
  db.py            # Esquema y conexión a SQLite/PostgreSQL
  ingest.py        # Importación desacoplada a la base de datos
  strava_zip.py    # ZIP Strava -> CSV normalizados y puntos GPS
  analytics.py     # Métricas y récords
scripts/refresh_db.sh
data/               # ZIP, CSV intermedios y base de datos (no se versionan)
```
