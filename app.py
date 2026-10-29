from __future__ import annotations

import os
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from branca.colormap import LinearColormap
from dotenv import load_dotenv
from sqlalchemy import select
from streamlit_folium import st_folium

from running_dashboard.analytics import (
    activity_family, compute_segment_records, ensure_activity_columns, format_pace,
    haversine_m, is_running_type, monthly_summary, pace_min_km, prepare_points,
    seconds_to_hms, heart_rate_analysis,
)
from running_dashboard.db import (
    PROJECT_ROOT, activities, activity_points, clear_database, get_engine,
    get_table_df, init_db,
)
from running_dashboard.ingest import run_import
from running_dashboard.strava_zip import prepare_strava_zip

load_dotenv(PROJECT_ROOT / ".env")
STRAVA_ZIP_PATH = Path(os.getenv("STRAVA_ZIP_PATH", str(PROJECT_ROOT / "data" / "strava_export.zip"))).expanduser()
ACTIVITIES_CSV = Path(os.getenv("ACTIVITIES_CSV", str(PROJECT_ROOT / "data" / "processed" / "activities.csv"))).expanduser()
POINTS_CSV = Path(os.getenv("POINTS_CSV", str(PROJECT_ROOT / "data" / "processed" / "activity_points.csv"))).expanduser()

st.set_page_config(page_title="Gonzarun · Running Lab", page_icon="🏃", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
    :root {
        --ink: #14213d;
        --muted: #52627a;
        --soft: #f4f7fb;
        --panel: #ffffff;
        --line: #d7e0ec;
        --navy: #14213d;
        --teal: #087f75;
        --blue: #185adb;
    }
    html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .stApp { background: var(--soft); color: var(--ink); }
    [data-testid="stHeader"] { background: var(--soft); }
    [data-testid="stToolbar"] { visibility: visible; }
    .block-container { max-width: 1440px; padding: 2.2rem 3rem 4rem; }
    .hero {
        padding: 2rem 2.2rem;
        border-radius: 26px;
        background: var(--navy);
        color: #ffffff;
        margin-bottom: 1.4rem;
        border: 1px solid #263a5e;
        box-shadow: 0 16px 35px rgba(20,33,61,.16);
    }
    .hero h1 { color: #ffffff !important; font-size: 2.25rem; line-height: 1.05; margin: 0 0 .55rem; letter-spacing: -.045em; }
    .hero p { color: #dce8f8 !important; margin: 0; font-size: 1.02rem; }
    h1, h2, h3, h4, p, li, label, [data-testid="stMarkdownContainer"] { color: var(--ink); }
    h2, h3, h4 { letter-spacing: -.025em; }
    [data-testid="stCaptionContainer"], .small-muted { color: var(--muted) !important; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { color: var(--ink) !important; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"] > div,
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] [data-testid="stDateInput"] input {
        background: #ffffff !important; color: var(--ink) !important;
        border: 1px solid #b8c6d8 !important; border-radius: 10px !important;
        -webkit-text-fill-color: var(--ink) !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] span,
    [data-testid="stSidebar"] [data-baseweb="select"] input { color: var(--ink) !important; -webkit-text-fill-color: var(--ink) !important; }
    [data-testid="stSidebar"] [data-baseweb="tag"] { background: #dcefeb !important; color: #075e57 !important; }
    [data-testid="stSidebar"] [data-baseweb="tag"] span { color: #075e57 !important; }
    [data-testid="stSidebar"] [data-testid="stCheckbox"] label { color: var(--ink) !important; }
    div[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 16px 18px; box-shadow: 0 6px 18px rgba(20,42,80,.055); }
    div[data-testid="stMetricLabel"] { color: var(--muted) !important; font-size: .78rem; }
    div[data-testid="stMetricValue"], div[data-testid="stMetricDelta"] { color: var(--ink) !important; }
    div[data-testid="stMetricValue"] { font-weight: 750; }
    div[data-testid="stRadio"] [role="radiogroup"] { gap: .45rem; flex-wrap: wrap; background: #e4ebf5; padding: .35rem; border-radius: 14px; }
    div[data-testid="stRadio"] [role="radio"] { color: var(--muted) !important; background: transparent; border: 0; border-radius: 10px; padding: .65rem .9rem; }
    div[data-testid="stRadio"] [role="radio"][aria-checked="true"] { color: #ffffff !important; background: var(--navy); }
    div[data-testid="stRadio"] [role="radio"][aria-checked="true"] * { color: #ffffff !important; }
    [data-baseweb="input"], [data-baseweb="select"] > div, [data-testid="stDateInput"] input {
        background: #ffffff !important; color: var(--ink) !important; border-color: var(--line) !important;
    }
    [data-baseweb="input"] input, [data-baseweb="select"] input, [data-baseweb="select"] span,
    [data-testid="stDateInput"] input { color: var(--ink) !important; -webkit-text-fill-color: var(--ink) !important; }
    [data-baseweb="menu"], [data-baseweb="popover"] { background: #ffffff !important; color: var(--ink) !important; }
    [role="option"] { color: var(--ink) !important; }
    button[kind="primary"], button[kind="secondary"] { border-radius: 10px; font-weight: 650; }
    button[kind="primary"] { background: var(--teal) !important; border-color: var(--teal) !important; color: #ffffff !important; }
    button[kind="secondary"] { background: #ffffff !important; border-color: var(--line) !important; color: var(--ink) !important; }
    div[data-testid="stDataFrame"] { background: #ffffff; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
    div[data-testid="stAlert"], div[data-testid="stStatusWidget"] { border-radius: 14px; }
    .section-kicker { color: var(--teal) !important; font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; margin-bottom: .2rem; }
    .section-lead { color: var(--muted) !important; font-size: .98rem; margin-bottom: 1.2rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=180)
def cached_activities() -> pd.DataFrame:
    return ensure_activity_columns(get_table_df(activities))


@st.cache_data(ttl=180)
def cached_gps_activity_ids() -> tuple[str, ...]:
    with get_engine().connect() as conn:
        rows = conn.execute(select(activity_points.c.activity_id).distinct()).scalars().all()
    return tuple(str(x) for x in rows)


@st.cache_data(ttl=300)
def cached_points_for_activity(activity_id: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        needed_columns = [
            activity_points.c.point_id, activity_points.c.activity_id, activity_points.c.point_index,
            activity_points.c.timestamp, activity_points.c.latitude, activity_points.c.longitude,
            activity_points.c.altitude_m, activity_points.c.distance_m, activity_points.c.heart_rate,
            activity_points.c.cadence, activity_points.c.speed_mps, activity_points.c.power_w,
            activity_points.c.temperature_c, activity_points.c.grade_percent,
        ]
        df = pd.read_sql(
            select(*needed_columns).where(activity_points.c.activity_id == str(activity_id)).order_by(activity_points.c.point_index), conn
        )
    return prepare_points(df)


@st.cache_data(ttl=900)
def cached_points_for_records(activity_ids: tuple[str, ...]) -> pd.DataFrame:
    if not activity_ids:
        return pd.DataFrame()
    # Split IN clauses to stay below SQLite's parameter limit on large exports.
    results = []
    with get_engine().connect() as conn:
        for start in range(0, len(activity_ids), 500):
            subset = activity_ids[start:start + 500]
            statement = select(
                activity_points.c.activity_id, activity_points.c.point_index, activity_points.c.timestamp,
                activity_points.c.latitude, activity_points.c.longitude, activity_points.c.distance_m,
                activity_points.c.altitude_m, activity_points.c.heart_rate, activity_points.c.speed_mps,
            ).where(activity_points.c.activity_id.in_(subset))
            results.append(pd.read_sql(statement, conn))
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def fmt_km(value) -> str:
    return "—" if pd.isna(value) else f"{value:,.1f} km".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(value) -> str:
    return "—" if pd.isna(value) else f"{int(round(float(value))):,}".replace(",", ".")


def fmt_hours(value) -> str:
    return "—" if pd.isna(value) else f"{float(value):,.1f} h".replace(",", "X").replace(".", ",").replace("X", ".")


def apply_plot_style(fig, height: int = 320):
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=48, b=10),
        font=dict(family="Inter, Arial, sans-serif", color="#14213d"),
        title_font=dict(size=16, color="#14213d"),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, linecolor="#d7e0ec", tickfont_color="#52627a", title_font_color="#52627a")
    fig.update_yaxes(gridcolor="#e8eef5", zerolinecolor="#d7e0ec", tickfont_color="#52627a", title_font_color="#52627a")
    return fig


def metric_rows(df: pd.DataFrame) -> dict:
    distance = df["distance_km"].sum(min_count=1)
    duration = df["duration_s"].sum(min_count=1)
    elevation = df["elevation_gain_m"].sum(min_count=1)
    avg_pace = pace_min_km(distance, duration)
    dated_days = sorted(set(df["day"].dropna().tolist()))
    longest_streak = 0
    current_streak = 0
    for day in dated_days:
        if current_streak and (day - previous_day).days == 1:
            current_streak += 1
        else:
            current_streak = 1
        longest_streak = max(longest_streak, current_streak)
        previous_day = day
    family = df["activity_family"].mode().iloc[0] if "activity_family" in df and not df["activity_family"].mode().empty else "Correr"
    family_df = df[df["activity_family"] == family] if "activity_family" in df else df
    family_distance = family_df["distance_km"].sum(min_count=1)
    family_duration = family_df["duration_s"].sum(min_count=1)
    return {
        "distance": 0 if pd.isna(distance) else float(distance),
        "duration": 0 if pd.isna(duration) else float(duration),
        "elevation": 0 if pd.isna(elevation) else float(elevation),
        "avg_pace": pace_min_km(family_distance, family_duration) if family == "Correr" else None,
        "runs": len(df),
        "avg_hr": df["avg_hr"].mean(),
        "max_hr": df["max_hr"].max(),
        "calories": df["calories"].sum(min_count=1),
        "avg_distance": df["distance_km"].mean(),
        "longest": df["distance_km"].max(),
        "avg_duration": df["duration_s"].mean(),
        "effort": df["relative_effort"].sum(min_count=1),
        "power": df["avg_power_w"].mean(),
        "median_pace": df["pace_min_km"].median(),
        "active_days": len(dated_days),
        "longest_streak": longest_streak,
        "family": family,
    }


def _import_zip_in_app(zip_path: Path, label: str) -> None:
    with st.status(label, expanded=True) as status:
        try:
            st.write("Leyendo el ZIP y buscando actividades y recorridos GPS…")
            prepared = prepare_strava_zip(zip_path, force=True)
            result = run_import(
                Path(prepared["activities_csv"]),
                Path(prepared["points_csv"]),
                force=True,
            )
            st.write(
                f"{result['activities_imported']:,} actividades y "
                f"{result['points_imported']:,} puntos GPS importados.".replace(",", ".")
            )
            if prepared.get("errors"):
                st.warning(f"Se han omitido {len(prepared['errors'])} archivos de track con errores.")
            st.cache_data.clear()
            status.update(label="Sincronización completada", state="complete")
            st.rerun()
        except Exception as exc:
            st.error(f"No se ha podido completar la importación: {exc}")
            status.update(label="Error durante la sincronización", state="error")


def _import_csv_in_app() -> None:
    with st.status("Importando CSV existentes…", expanded=True) as status:
        try:
            result = run_import(ACTIVITIES_CSV, POINTS_CSV, force=True)
            st.write(
                f"{result['activities_imported']:,} actividades y "
                f"{result['points_imported']:,} puntos GPS importados.".replace(",", ".")
            )
            st.cache_data.clear()
            status.update(label="Sincronización completada", state="complete")
            st.rerun()
        except Exception as exc:
            st.error(f"No se ha podido completar la importación: {exc}")
            status.update(label="Error durante la sincronización", state="error")


def render_ingest() -> None:
    st.markdown("### Importar datos de Strava")
    st.caption("Carga el ZIP completo descargado de Strava. Se extraerán las actividades y los recorridos GPS antes de actualizar la base de datos.")

    upload_col, info_col = st.columns([1.35, 1])
    with upload_col:
        uploaded_zip = st.file_uploader(
            "Exportación completa de Strava (.zip)",
            type=["zip"],
            key="strava_export_uploader",
        )
        if st.button(
            "📦 Procesar ZIP de Strava",
            use_container_width=True,
            type="primary",
            disabled=uploaded_zip is None,
            key="process_strava_zip",
        ):
            STRAVA_ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
            with STRAVA_ZIP_PATH.open("wb") as target:
                target.write(uploaded_zip.getvalue())
            _import_zip_in_app(
                STRAVA_ZIP_PATH,
                "Procesando el ZIP completo de Strava…",
            )

        if STRAVA_ZIP_PATH.exists():
            st.caption(f"ZIP guardado: `{STRAVA_ZIP_PATH}`")
            if st.button("↻ Actualizar desde el ZIP guardado", use_container_width=True, key="refresh_saved_zip"):
                _import_zip_in_app(
                    STRAVA_ZIP_PATH,
                    "Actualizando desde el ZIP guardado…",
                )
        else:
            st.caption("Todavía no hay ningún ZIP guardado.")

    with info_col:
        st.info("La importación puede tardar varios minutos si el ZIP contiene muchos recorridos GPS. Puedes seguir usando el dashboard después de completar el proceso.")

    with st.expander("Avanzado: importar CSV ya procesados"):
        st.caption("Usa esta opción solo si ya generaste manualmente los CSV.")
        st.code(f"activities: {ACTIVITIES_CSV}\npuntos GPS: {POINTS_CSV}", language="text")
        if st.button("Importar CSV existentes", use_container_width=True, key="sync_existing_csv"):
            _import_csv_in_app()


def render_summary(df: pd.DataFrame, summary: dict) -> None:
    families = [family for family in ["Correr", "Bici", "Natación", "Andar", "Otros"] if family in set(df["activity_family"])]
    if len(families) > 1:
        tabs = st.tabs([f"{family} · {len(df[df['activity_family'] == family])}" for family in families])
        for tab, family in zip(tabs, families):
            with tab:
                family_df = df[df["activity_family"] == family].copy()
                render_summary(family_df, metric_rows(family_df))
        return
    family = summary.get("family", "Actividad")
    st.markdown(f"<div class='section-kicker'>Resumen · {family}</div>", unsafe_allow_html=True)
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Distancia acumulada", fmt_km(summary["distance"]))
    kpi2.metric("Actividades", fmt_int(summary["runs"]))
    kpi3.metric("Tiempo en movimiento", seconds_to_hms(summary["duration"]))
    kpi4.metric("Desnivel positivo", f"{fmt_int(summary['elevation'])} m")
    kpi5.metric("Ritmo global ponderado", format_pace(summary["avg_pace"]))
    kpi6, kpi7, kpi8, kpi9, kpi10 = st.columns(5)
    kpi6.metric("Distancia media", fmt_km(summary["avg_distance"]))
    kpi7.metric("Tirada más larga", fmt_km(summary["longest"]))
    kpi8.metric("FC media", f"{summary['avg_hr']:.0f} bpm" if pd.notna(summary["avg_hr"]) else "—")
    kpi9.metric("Calorías registradas", fmt_int(summary["calories"]))
    kpi10.metric("Esfuerzo relativo", fmt_int(summary["effort"]))
    a, b, c = st.columns(3)
    a.metric("Ritmo mediano", format_pace(summary["median_pace"]))
    b.metric("Días activos", fmt_int(summary["active_days"]))
    c.metric("Racha máxima", f"{fmt_int(summary['longest_streak'])} días")
    with st.expander("Más métricas de entrenamiento y fisiología", expanded=False):
        a, b, c, d = st.columns(4)
        a.metric("FC máxima registrada", f"{summary['max_hr']:.0f} bpm" if pd.notna(summary["max_hr"]) else "—")
        b.metric("Potencia media", f"{summary['power']:.0f} W" if pd.notna(summary["power"]) else "—")
        c.metric("Cadencia media", f"{df['avg_cadence'].mean():.0f}" if df["avg_cadence"].notna().any() else "—")
        d.metric("Duración media", seconds_to_hms(summary["avg_duration"]))

    monthly = monthly_summary(df)
    left, right = st.columns([1.45, 1])
    with left:
        if not monthly.empty:
            chart = px.line if len(monthly) <= 6 else px.area
            fig = chart(monthly, x="month", y="distance_km", markers=True, labels={"month": "Mes", "distance_km": "Kilómetros"}, title="Volumen mensual")
            fig.update_traces(line_color="#087f75", marker_color="#087f75", line_width=3, hovertemplate="%{x}<br>%{y:.1f} km<extra></extra>")
            apply_plot_style(fig, 340)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Todavía no hay actividades con fecha y distancia para dibujar el volumen mensual.")
    with right:
        if not df.empty and df["weekday"].notna().any():
            weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            weekday_es = {"Monday": "Lun", "Tuesday": "Mar", "Wednesday": "Mié", "Thursday": "Jue", "Friday": "Vie", "Saturday": "Sáb", "Sunday": "Dom"}
            wk = df.groupby("weekday").agg(km=("distance_km", "sum"), sesiones=("activity_id", "count")).reindex(weekday_order).fillna(0).reset_index()
            wk["día"] = wk["weekday"].map(weekday_es)
            fig = px.bar(wk, x="día", y="sesiones", title="¿Qué días entrenas más?", labels={"día": "Día", "sesiones": "Sesiones"})
            fig.update_traces(marker_color="#5276d0", marker_line_width=0, hovertemplate="%{x}<br>%{y:.0f} sesiones<extra></extra>")
            apply_plot_style(fig, 340)
            st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        if not df.empty and df["distance_km"].notna().any():
            fig = px.histogram(df.dropna(subset=["distance_km"]), x="distance_km", nbins=20, title="Distribución de distancias", labels={"distance_km": "Distancia (km)", "count": "Actividades"})
            fig.update_traces(marker_color="#e49a4a", marker_line_width=0)
            apply_plot_style(fig, 300)
            st.plotly_chart(fig, use_container_width=True)
    with right:
        hrdf = df.dropna(subset=["avg_hr", "pace_min_km"]).copy()
        if len(hrdf):
            hrdf["ritmo"] = hrdf["pace_min_km"].map(format_pace)
            fig = px.scatter(hrdf, x="avg_hr", y="pace_min_km", color="activity_type", hover_name="activity_name", hover_data={"activity_date": True, "distance_km": ":.1f", "pace_min_km": False, "ritmo": True}, title="Ritmo y frecuencia cardíaca", labels={"avg_hr": "FC media (bpm)", "pace_min_km": "Ritmo (min/km)", "activity_type": "Tipo"})
            fig.update_yaxes(autorange="reversed")
            fig.update_traces(marker={"size": 9, "opacity": .8})
            apply_plot_style(fig, 300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay suficientes datos de ritmo y frecuencia cardíaca para esta gráfica.")


def render_evolution(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No hay actividades con los filtros actuales.")
        return
    families = [family for family in ["Correr", "Bici", "Natación", "Andar", "Otros"] if family in set(df["activity_family"])]
    if len(families) > 1:
        tabs = st.tabs(families)
        for tab, family in zip(tabs, families):
            with tab:
                render_evolution(df[df["activity_family"] == family].copy())
        return
    st.markdown("### Volumen y consistencia")
    dated = df.dropna(subset=["activity_date"]).copy()
    if dated.empty:
        st.info("No se han podido interpretar fechas para analizar tendencias.")
        return
    dated["week_start"] = dated["activity_date"].dt.to_period("W-SUN").dt.start_time
    weekly = dated.groupby("week_start").agg(km=("distance_km", "sum"), sesiones=("activity_id", "count"), desnivel=("elevation_gain_m", "sum")).reset_index()
    weekly["media_4_sem"] = weekly["km"].rolling(4, min_periods=1).mean()
    fig = go.Figure()
    if len(weekly) <= 8:
        fig.add_trace(go.Scatter(x=weekly["week_start"], y=weekly["km"], name="Km por semana", mode="lines+markers", line=dict(color="#087f75", width=3)))
    else:
        fig.add_trace(go.Bar(x=weekly["week_start"], y=weekly["km"], name="Km por semana", marker_color="#8ac9c1"))
    fig.add_trace(go.Scatter(x=weekly["week_start"], y=weekly["media_4_sem"], name="Media móvil (4 semanas)", mode="lines", line=dict(color="#185adb", width=3)))
    fig.update_layout(title="Carga semanal de entrenamiento", xaxis_title="Semana", yaxis_title="Km")
    apply_plot_style(fig, 380)
    st.plotly_chart(fig, use_container_width=True)

    monthly = monthly_summary(dated)
    left, right = st.columns(2)
    with left:
        if not monthly.empty:
            monthly["km_acumulados"] = monthly["distance_km"].fillna(0).cumsum()
            fig = go.Figure()
            if len(monthly) <= 6:
                fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["distance_km"], name="Km del mes", mode="lines+markers", line=dict(color="#087f75", width=3)))
            else:
                fig.add_trace(go.Bar(x=monthly["month"], y=monthly["distance_km"], name="Km del mes", marker_color="#8ac9c1"))
            fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["km_acumulados"], name="Acumulado", yaxis="y2", line=dict(color="#f08a4b", width=3)))
            fig.update_layout(title="Km mensuales y acumulados", yaxis_title="Km por mes", yaxis2=dict(title="Km acumulados", overlaying="y", side="right", showgrid=False))
            apply_plot_style(fig, 340)
            st.plotly_chart(fig, use_container_width=True)
    with right:
        if "avg_pace" in monthly and monthly["avg_pace"].notna().any():
            pace = monthly.dropna(subset=["avg_pace"])
            fig = px.line(pace, x="month", y="avg_pace", markers=True, title="Evolución del ritmo medio de las sesiones", labels={"month": "Mes", "avg_pace": "Ritmo (min/km)"})
            fig.update_yaxes(autorange="reversed", tickformat=".1f")
            fig.update_traces(line_color="#7957c8", line_width=3, marker_size=7)
            apply_plot_style(fig, 340)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay datos suficientes para ver la evolución del ritmo.")

    left, right = st.columns(2)
    with left:
        hourly = dated.dropna(subset=["hour"]).groupby("hour").size().reindex(range(24), fill_value=0).rename("sesiones").reset_index()
        hourly.columns = ["hora", "sesiones"]
        fig = px.bar(hourly, x="hora", y="sesiones", title="Hora habitual de entrenamiento", labels={"hora": "Hora del día", "sesiones": "Sesiones"})
        fig.update_traces(marker_color="#5276d0")
        apply_plot_style(fig, 300)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        effort_cols = [c for c in ["relative_effort", "suffer_score"] if dated[c].notna().sum() > 0]
        if effort_cols:
            col = effort_cols[0]
            effort = dated.groupby("month")[col].sum(min_count=1).reset_index()
            fig = px.area(effort, x="month", y=col, title="Carga / esfuerzo registrado", labels={"month": "Mes", col: col.replace("_", " ").title()})
            fig.update_traces(line_color="#de795d", fillcolor="rgba(222,121,93,.2)")
            apply_plot_style(fig, 300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Tu exportación no contiene esfuerzo relativo ni Suffer Score para esta selección.")

    st.markdown("#### Resumen mensual")
    display = monthly.copy()
    if not display.empty:
        display["Ritmo medio"] = display["avg_pace"].map(format_pace)
        display = display.rename(columns={"month": "Mes", "distance_km": "Km", "runs": "Sesiones", "duration_h": "Horas", "elevation_m": "Desnivel (m)"})
        st.dataframe(display[["Mes", "Km", "Sesiones", "Horas", "Desnivel (m)", "Ritmo medio"]].round(1), use_container_width=True, hide_index=True)


def render_physiology(df: pd.DataFrame, key_suffix: str = "root") -> None:
    st.markdown("<div class='section-kicker'>Fisiología</div><h2>Frecuencia cardíaca y respuesta al esfuerzo</h2><p class='section-lead'>Estimaciones basadas en las muestras de FC y velocidad de tus recorridos GPS. Ajusta tu FC máxima para que las zonas sean personales.</p>", unsafe_allow_html=True)
    if df.empty:
        st.info("No hay actividades con los filtros actuales.")
        return
    families = [family for family in ["Correr", "Bici", "Natación", "Andar", "Otros"] if family in set(df["activity_family"])]
    if len(families) > 1:
        tabs = st.tabs(families)
        for tab, family in zip(tabs, families):
            with tab:
                render_physiology(df[df["activity_family"] == family].copy(), key_suffix=family.casefold())
        return
    render_physiology_for_selection(df, key_suffix=key_suffix)


def render_physiology_for_selection(df: pd.DataFrame, key_suffix: str) -> None:
    if df.empty:
        st.info("No hay actividades con los filtros actuales.")
        return
    gps_ids = tuple(sorted(set(df["activity_id"].dropna().astype(str)) & set(cached_gps_activity_ids())))
    points = cached_points_for_records(gps_ids)
    if points.empty or "heart_rate" not in points or "timestamp" not in points:
        st.info("No hay recorridos con muestras de frecuencia cardíaca y fecha disponibles.")
        return
    valid_points = points[
        pd.to_numeric(points["heart_rate"], errors="coerce").between(30, 240)
        & pd.to_datetime(points["timestamp"], errors="coerce", utc=True).notna()
    ]
    valid_ids = set(valid_points["activity_id"].dropna().astype(str))
    choices = df[df["activity_id"].astype(str).isin(valid_ids)].drop_duplicates("activity_id")
    choices = choices.sort_values("activity_date", ascending=False, na_position="last").copy()
    if choices.empty:
        st.info("No hay recorridos con muestras de frecuencia cardíaca y fecha disponibles.")
        return

    def label(aid: str) -> str:
        row = choices.loc[choices["activity_id"].astype(str) == str(aid)].iloc[0]
        date = row["activity_date"].strftime("%d/%m/%Y") if pd.notna(row["activity_date"]) else "sin fecha"
        return f"{row['activity_name']} · {date}"

    selected_id = st.selectbox(
        "Carrera para el análisis detallado",
        ["Todas las actividades"] + choices["activity_id"].astype(str).tolist(),
        format_func=lambda aid: "Resumen de la disciplina" if aid == "Todas las actividades" else label(aid),
        key=f"physiology_activity_{key_suffix}",
    )
    selected_df = df if selected_id == "Todas las actividades" else df[df["activity_id"].astype(str) == selected_id].copy()
    render_physiology_analysis(selected_df, key_suffix=key_suffix)


def render_physiology_analysis(df: pd.DataFrame, key_suffix: str) -> None:
    if df.empty:
        st.info("No hay actividades con datos para analizar.")
        return
    gps_ids = tuple(sorted(set(df["activity_id"].dropna().astype(str)) & set(cached_gps_activity_ids())))
    if not gps_ids:
        st.info("No hay recorridos GPS con frecuencia cardíaca para calcular estas métricas.")
        return
    observed_max = df["max_hr"].dropna()
    default_max = int(round(float(observed_max.max()))) if not observed_max.empty else 190
    max_hr = st.slider(
        "FC máxima de referencia (bpm)",
        150,
        230,
        min(230, max(150, default_max)),
        key=f"physiology_max_hr_{key_suffix}",
    )
    st.caption("Zonas usadas: Z1 <60%, Z2 60–70%, Z3 70–80%, Z4 80–90%, Z5 ≥90% de la FC máxima. Aeróbico = hasta 80%; anaeróbico = desde 90%.")
    with st.spinner("Analizando muestras de FC y velocidad…"):
        points = cached_points_for_records(gps_ids)
        analysis = heart_rate_analysis(points, max_hr)
    zones = analysis["zones"]
    states = analysis["states"]
    if zones.empty:
        st.warning("Hay GPS, pero no suficientes muestras válidas de frecuencia cardíaca.")
        return

    left, right = st.columns([1.1, 1])
    with left:
        zone_display = zones.copy()
        zone_display["Tiempo"] = zone_display["minutes"].map(seconds_to_hms)
        zone_display["Porcentaje"] = zone_display["percent"].map(lambda value: f"{value:.1f} %")
        st.markdown("#### Tiempo por zona de frecuencia cardíaca")
        st.dataframe(zone_display[["zone", "Tiempo", "Porcentaje"]].rename(columns={"zone": "Zona"}), use_container_width=True, hide_index=True)
    with right:
        plot = zones.copy()
        fig = px.bar(plot, x="zone", y="minutes", color="zone", title="Distribución del tiempo por zona", labels={"zone": "Zona", "minutes": "Minutos"}, color_discrete_sequence=["#9bd8cf", "#4fb3a7", "#087f75", "#f59e0b", "#dc2626"])
        fig.update_layout(showlegend=False)
        apply_plot_style(fig, 330)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Velocidad en estado aeróbico y anaeróbico")
    state_display = states.dropna(subset=["seconds"]).copy()
    state_display["Tiempo total"] = state_display["minutes"].map(lambda value: f"{value:.1f} min")
    state_display["Tiempo medio por actividad"] = state_display["avg_minutes_per_activity"].map(lambda value: f"{value:.1f} min" if pd.notna(value) else "—")
    state_display["Velocidad media"] = state_display["avg_speed_kmh"].map(lambda value: f"{value:.1f} km/h" if pd.notna(value) else "—")
    state_display["Velocidad mediana"] = state_display["median_speed_kmh"].map(lambda value: f"{value:.1f} km/h" if pd.notna(value) else "—")
    state_display["FC media"] = state_display["avg_hr"].map(lambda value: f"{value:.0f} bpm" if pd.notna(value) else "—")
    st.dataframe(state_display[["state", "Tiempo total", "Tiempo medio por actividad", "Velocidad media", "Velocidad mediana", "FC media"]].rename(columns={"state": "Estado"}), use_container_width=True, hide_index=True)

    drift = analysis["drift"]
    stabilization = analysis["stabilization"]
    drift_col, stable_col = st.columns(2)
    with drift_col:
        st.markdown("#### ¿Sube la FC manteniendo velocidad?")
        if not drift.empty:
            drift_valid = drift.dropna(subset=["delta_bpm"])
            mean_delta = drift_valid["delta_bpm"].mean()
            st.metric("Cambio medio de FC a velocidad comparable", f"{mean_delta:+.1f} bpm" if pd.notna(mean_delta) else "—")
            st.caption("Compara la primera y segunda mitad de cada actividad dentro de una banda de velocidad similar. Un valor positivo sugiere deriva cardíaca.")
            chart = drift_valid.sort_values("delta_bpm").tail(20).copy()
            activity_labels = df.drop_duplicates("activity_id").set_index("activity_id").apply(
                lambda row: f"{row['activity_name']} · {row['activity_date'].strftime('%d/%m/%Y') if pd.notna(row['activity_date']) else 'sin fecha'}",
                axis=1,
            )
            chart["actividad"] = chart["activity_id"].map(activity_labels).fillna("Recorrido sin identificar")
            fig = px.bar(chart, x="delta_bpm", y="actividad", orientation="h", title="Deriva cardíaca por actividad", labels={"delta_bpm": "Cambio de FC (bpm)", "actividad": "Recorrido"})
            fig.add_vline(x=0, line_color="#14213d")
            apply_plot_style(fig, 340)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay suficientes muestras con velocidad comparable para estimar la deriva.")
    with stable_col:
        st.markdown("#### Tiempo para estabilización")
        stable = stabilization.dropna(subset=["seconds"])
        if not stable.empty:
            st.metric("Mediana hasta estabilizar", seconds_to_hms(stable["seconds"].median()))
            st.caption("Primera ventana móvil de 60 s con desviación de FC ≤5 bpm. Es una estimación y depende de la calidad del sensor.")
            stable_display = stable.copy()
            stable_display["Estabilización"] = stable_display["seconds"].map(seconds_to_hms)
            activity_labels = df.drop_duplicates("activity_id").set_index("activity_id").apply(
                lambda row: f"{row['activity_name']} · {row['activity_date'].strftime('%d/%m/%Y') if pd.notna(row['activity_date']) else 'sin fecha'}",
                axis=1,
            )
            stable_display["Recorrido"] = stable_display["activity_id"].map(activity_labels).fillna("Recorrido sin identificar")
            st.dataframe(stable_display[["Recorrido", "Estabilización"]], use_container_width=True, hide_index=True)
        else:
            st.info("No hay suficientes puntos para estimar la estabilización de la FC.")


def render_records(df: pd.DataFrame) -> None:
    st.markdown("### Marcas personales y mejores sesiones")
    if df.empty:
        st.info("No hay actividades con los filtros actuales.")
        return
    families = [family for family in ["Correr", "Bici", "Natación", "Andar", "Otros"] if family in set(df["activity_family"])]
    if len(families) > 1:
        tabs = st.tabs(families)
        for tab, family in zip(tabs, families):
            with tab:
                render_records(df[df["activity_family"] == family].copy())
        return
    left, right, third = st.columns(3)
    long_row = df.loc[df["distance_km"].idxmax()] if df["distance_km"].notna().any() else None
    fastest = df.dropna(subset=["pace_min_km"])
    fastest = fastest.loc[fastest["distance_km"].fillna(0) >= 1] if not fastest.empty else fastest
    climb = df.loc[df["elevation_gain_m"].idxmax()] if df["elevation_gain_m"].notna().any() else None
    with left:
        st.metric("Tirada más larga", fmt_km(long_row["distance_km"]) if long_row is not None else "—")
        if long_row is not None:
            st.caption(f"{long_row['activity_name']} · {long_row['activity_date'].strftime('%d/%m/%Y') if pd.notna(long_row['activity_date']) else 'fecha desconocida'}")
    with right:
        st.metric("Ritmo más rápido en una actividad", format_pace(fastest["pace_min_km"].min()) if not fastest.empty else "—")
        if not fastest.empty:
            best = fastest.loc[fastest["pace_min_km"].idxmin()]
            st.caption(f"{best['activity_name']} · {fmt_km(best['distance_km'])}")
    with third:
        st.metric("Mayor desnivel positivo", f"{fmt_int(climb['elevation_gain_m'])} m" if climb is not None else "—")
        if climb is not None:
            st.caption(f"{climb['activity_name']} · {fmt_km(climb['distance_km'])}")

    gps_ids = tuple(sorted(set(df["activity_id"].dropna().astype(str)) & set(cached_gps_activity_ids())))
    st.markdown("#### Récords por distancia calculados con GPS")
    if gps_ids:
        with st.spinner("Calculando mejores segmentos GPS…"):
            points = cached_points_for_records(gps_ids)
            prs = compute_segment_records(points, df)
        if not prs.empty:
            display = prs.copy()
            display["Mejor tiempo"] = display["mejor_tiempo_s"].map(seconds_to_hms)
            display["Ritmo"] = display["ritmo_min_km"].map(format_pace)
            display["Fecha"] = pd.to_datetime(display["fecha"], errors="coerce", utc=True).dt.strftime("%d/%m/%Y")
            st.dataframe(display[["distancia", "Mejor tiempo", "Ritmo", "actividad", "Fecha"]].rename(columns={"distancia": "Distancia", "actividad": "Actividad"}), use_container_width=True, hide_index=True)
        else:
            st.info("Hay tracks GPS, pero no se han encontrado segmentos válidos con fechas y distancia acumulada para calcular marcas.")
    else:
        st.info("No hay actividades con GPS dentro de la selección actual.")

    st.markdown("#### Top 10 por distancia")
    top = df.dropna(subset=["distance_km"]).nlargest(10, "distance_km").copy()
    if not top.empty:
        top["Fecha"] = top["activity_date"].dt.strftime("%d/%m/%Y")
        top["Ritmo"] = top["pace_min_km"].map(format_pace)
        st.dataframe(top[["Fecha", "activity_name", "activity_type", "distance_km", "duration_s", "pace_min_km", "elevation_gain_m"]].rename(columns={"activity_name": "Actividad", "activity_type": "Tipo", "distance_km": "Km", "duration_s": "Tiempo", "pace_min_km": "Ritmo (min/km)", "elevation_gain_m": "Desnivel (m)"}).assign(Tiempo=lambda x: x["Tiempo"].map(seconds_to_hms)), use_container_width=True, hide_index=True)


def render_gps(df: pd.DataFrame) -> None:
    all_gps_ids = set(cached_gps_activity_ids())
    choices = df[df["activity_id"].astype(str).isin(all_gps_ids)].copy()
    choices = choices.drop_duplicates("activity_id").sort_values("activity_date", ascending=False, na_position="last")
    st.markdown("### Explora tus carreras con GPS")
    if choices.empty:
        st.warning("No hay actividades con GPS para los filtros seleccionados. Comprueba que activity_points.csv esté importado y que sus recorridos coincidan con las actividades.")
        return
    def label(aid: str) -> str:
        row = choices.loc[choices["activity_id"].astype(str) == str(aid)].iloc[0]
        date = row["activity_date"].strftime("%d/%m/%Y %H:%M") if pd.notna(row["activity_date"]) else "fecha desconocida"
        dist = fmt_km(row["distance_km"])
        return f"{row['activity_name']} · {date} · {dist}"
    selected_id = st.selectbox("Carrera (nombre · fecha · distancia)", choices["activity_id"].astype(str).tolist(), format_func=label, key="gps_activity")
    pts = cached_points_for_activity(selected_id)
    pts = pts.dropna(subset=["latitude", "longitude"]).sort_values("point_index").reset_index(drop=True)
    if len(pts) < 2:
        st.warning("Este track tiene menos de dos puntos GPS válidos.")
        return
    act = choices.loc[choices["activity_id"].astype(str) == str(selected_id)].iloc[0]
    distance_km = float(pts["distance_m"].max() / 1000) if pts["distance_m"].notna().any() else float("nan")
    duration = act["duration_s"]
    altitude_gain = act["elevation_gain_m"]
    avg_hr = pts["heart_rate"].mean() if "heart_rate" in pts else float("nan")
    elev_min, elev_max = pts["altitude_m"].min(), pts["altitude_m"].max()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Distancia GPS", fmt_km(distance_km))
    m2.metric("Tiempo registrado", seconds_to_hms(duration))
    m3.metric("Ritmo medio", format_pace(pace_min_km(distance_km, duration)))
    m4.metric("Desnivel actividad", f"{fmt_int(altitude_gain)} m" if pd.notna(altitude_gain) else "—")
    m5.metric("FC media en GPS", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "—")

    with st.expander("Control de detalle del mapa", expanded=False):
        default_stride = max(1, len(pts) // 70)
        stride = st.slider("Pintar un marcador cada N puntos GPS", min_value=1, max_value=max(1, min(500, len(pts))), value=min(max(1, default_stride), max(1, min(500, len(pts)))), help="El recorrido conserva la línea; este ajuste controla los marcadores con datos para evitar saturar el mapa.")
        all_markers = st.checkbox("Mostrar todos los marcadores (puede ralentizarse)", value=False)
        max_show_points = st.slider("Puntos visibles en la tabla de steps", min_value=100, max_value=max(100, min(20000, len(pts))), value=min(1000, max(100, len(pts))), step=100)

    selected_point_index = st.slider("Inspeccionar punto GPS / step", min_value=0, max_value=len(pts) - 1, value=0, help="Cada fila representa una muestra del FIT. Las métricas ausentes no siempre están disponibles en el dispositivo.")
    point = pts.iloc[selected_point_index]
    pcols = st.columns(6)
    point_values = [
        ("Step", str(int(point.get("point_index", selected_point_index)))),
        ("Hora", str(point.get("timestamp") or "—")),
        ("Distancia", f"{point['distance_m'] / 1000:.2f} km" if pd.notna(point.get("distance_m")) else "—"),
        ("Altitud", f"{point['altitude_m']:.0f} m" if pd.notna(point.get("altitude_m")) else "—"),
        ("FC", f"{point['heart_rate']:.0f} bpm" if pd.notna(point.get("heart_rate")) else "—"),
        ("Velocidad", f"{point['speed_mps'] * 3.6:.1f} km/h" if pd.notna(point.get("speed_mps")) else "—"),
    ]
    for col, (title, value) in zip(pcols, point_values):
        with col:
            st.metric(title, value)

    coords = list(zip(pts["latitude"].astype(float), pts["longitude"].astype(float)))
    # Keep the route detailed enough, while limiting the number of rendered vector points.
    route_step = max(1, len(coords) // 2500)
    line_coords = coords[::route_step]
    if line_coords[-1] != coords[-1]:
        line_coords.append(coords[-1])
    sampled_idx = list(range(0, len(pts), stride)) if not all_markers else list(range(len(pts)))
    if len(pts) - 1 not in sampled_idx:
        sampled_idx.append(len(pts) - 1)
    center = [float(pts["latitude"].mean()), float(pts["longitude"].mean())]

    map_col, alt_col = st.columns(2)
    with map_col:
        st.markdown("#### 🗺️ Recorrido")
        fmap = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap", control_scale=True)
        folium.PolyLine(line_coords, color="#2764d8", weight=5, opacity=0.9, tooltip=label(selected_id)).add_to(fmap)
        folium.Marker(coords[0], tooltip="Salida", icon=folium.Icon(color="green", icon="play")).add_to(fmap)
        folium.Marker(coords[-1], tooltip="Llegada", icon=folium.Icon(color="red", icon="flag")).add_to(fmap)
        for idx in sampled_idx:
            row = pts.iloc[idx]
            tooltip = f"Step {int(row['point_index'])} · {row['distance_m']/1000:.2f} km" if pd.notna(row.get("distance_m")) else f"Step {int(row['point_index'])}"
            folium.CircleMarker(coords[idx], radius=3, color="#2764d8", fill=True, fill_opacity=0.75, tooltip=tooltip).add_to(fmap)
        folium.CircleMarker(coords[selected_point_index], radius=7, color="#f97316", fill=True, fill_opacity=1, tooltip="Punto seleccionado").add_to(fmap)
        st_folium(fmap, use_container_width=True, height=450, key=f"route_map_{selected_id}")
    with alt_col:
        st.markdown("#### ⛰️ Recorrido por altitud")
        elevations = pts["altitude_m"].dropna()
        amap = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap", control_scale=True)
        if len(elevations):
            vmin, vmax = float(elevations.min()), float(elevations.max())
            if vmin == vmax:
                vmax = vmin + 1
            cmap = LinearColormap(["#2563eb", "#06b6d4", "#facc15", "#f97316", "#dc2626"], vmin=vmin, vmax=vmax, caption="Altitud (m)")
            alt_step = max(1, len(coords) // 2500)
            alt_indices = list(range(0, len(coords), alt_step))
            if alt_indices[-1] != len(coords) - 1:
                alt_indices.append(len(coords) - 1)
            for prev_idx, idx in zip(alt_indices[:-1], alt_indices[1:]):
                prev_alt = pts.iloc[prev_idx]["altitude_m"]
                current_alt = pts.iloc[idx]["altitude_m"]
                values = [v for v in (prev_alt, current_alt) if pd.notna(v)]
                avg_alt = sum(values) / len(values) if values else None
                color = cmap(float(avg_alt)) if avg_alt is not None else "#64748b"
                folium.PolyLine([coords[prev_idx], coords[idx]], color=color, weight=5, opacity=0.95).add_to(amap)
            cmap.add_to(amap)
            for idx in sampled_idx:
                alt = pts.iloc[idx].get("altitude_m")
                color = cmap(float(alt)) if pd.notna(alt) else "#64748b"
                folium.CircleMarker(coords[idx], radius=3, color=color, fill=True, fill_opacity=0.8, tooltip=f"Altitud: {alt:.0f} m" if pd.notna(alt) else "Altitud no registrada").add_to(amap)
        else:
            folium.PolyLine(line_coords, color="#64748b", weight=5).add_to(amap)
            st.caption("El FIT no incluye altitud; se muestra el trazado sin coloreado altimétrico.")
        folium.Marker(coords[0], tooltip="Salida", icon=folium.Icon(color="green", icon="play")).add_to(amap)
        folium.Marker(coords[-1], tooltip="Llegada", icon=folium.Icon(color="red", icon="flag")).add_to(amap)
        st_folium(amap, use_container_width=True, height=450, key=f"alt_map_{selected_id}")

    if pts["altitude_m"].notna().sum() > 1:
        profile = pts.dropna(subset=["altitude_m"]).copy()
        if profile["distance_m"].notna().sum() < 2:
            profile["distance_km_plot"] = range(len(profile))
        else:
            profile["distance_km_plot"] = profile["distance_m"] / 1000
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=profile["distance_km_plot"], y=profile["altitude_m"], mode="lines", line=dict(color="#d97706", width=2), fill="tozeroy", fillcolor="rgba(217,119,6,.15)", name="Altitud"))
        fig.update_layout(title="Perfil de altitud", xaxis_title="Distancia (km)", yaxis_title="Altitud (m)")
        apply_plot_style(fig, 300)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Datos de cada step / muestra GPS")
    show_points = pts.copy()
    show_points["distancia_km"] = show_points["distance_m"] / 1000
    show_points["velocidad_kmh"] = show_points["speed_mps"] * 3.6
    columns = [c for c in ["point_index", "timestamp", "distancia_km", "latitude", "longitude", "altitude_m", "heart_rate", "cadence", "velocidad_kmh", "power_w", "temperature_c", "grade_percent"] if c in show_points.columns]
    st.caption(f"Mostrando {min(len(show_points), max_show_points):,} de {len(show_points):,} puntos. Puedes descargar el track completo en CSV.".replace(",", "."))
    st.dataframe(show_points[columns].head(max_show_points).rename(columns={"point_index": "Step", "timestamp": "Fecha/hora", "distancia_km": "Distancia (km)", "latitude": "Latitud", "longitude": "Longitud", "altitude_m": "Altitud (m)", "heart_rate": "FC (bpm)", "cadence": "Cadencia", "velocidad_kmh": "Velocidad (km/h)", "power_w": "Potencia (W)", "temperature_c": "Temperatura (°C)", "grade_percent": "Pendiente (%)"}), use_container_width=True, hide_index=True)
    st.download_button("Descargar todos los puntos de esta carrera", data=show_points[columns].to_csv(index=False).encode("utf-8-sig"), file_name=f"gps_{selected_id}.csv", mime="text/csv")


def render_selected_runs(df: pd.DataFrame) -> None:
    st.markdown("<div class='section-kicker'>Explorador</div><h2>Tus carreras</h2><p class='section-lead'>Elige actividades concretas para revisar sus datos y compararlas lado a lado.</p>", unsafe_allow_html=True)
    families = [family for family in ["Correr", "Bici", "Natación", "Andar", "Otros"] if family in set(df["activity_family"])]
    selected_family = st.selectbox("Disciplina", families, key="run_comparison_family")
    choices = df[df["activity_family"] == selected_family].drop_duplicates("activity_id").sort_values("activity_date", ascending=False, na_position="last").copy()
    options = choices["activity_id"].astype(str).tolist()

    def label(aid: str) -> str:
        row = choices.loc[choices["activity_id"].astype(str) == str(aid)].iloc[0]
        date = row["activity_date"].strftime("%d/%m/%Y") if pd.notna(row["activity_date"]) else "sin fecha"
        return f"{date} · {row['activity_name']} · {fmt_km(row['distance_km'])}"

    selected_ids = st.multiselect(
        "Carreras seleccionadas",
        options,
        format_func=label,
        key="selected_runs",
        placeholder="Elige una o varias carreras…",
    )
    if not selected_ids:
        st.info("Selecciona al menos una carrera para ver sus métricas. Para comparar, elige dos o más.")
        return

    selected = choices[choices["activity_id"].astype(str).isin(selected_ids)].copy()
    selected["Etiqueta"] = selected["activity_id"].astype(str).map(label)
    selected["Fecha"] = selected["activity_date"].dt.strftime("%d/%m/%Y %H:%M")
    selected["Ritmo"] = selected["pace_min_km"].map(format_pace)
    selected["Tiempo"] = selected["duration_s"].map(seconds_to_hms)
    comparison = selected[[
        "Etiqueta", "activity_type", "distance_km", "Tiempo", "Ritmo",
        "elevation_gain_m", "avg_hr", "calories", "relative_effort",
    ]].rename(columns={
        "Etiqueta": "Carrera", "activity_type": "Tipo", "distance_km": "Distancia (km)",
        "elevation_gain_m": "Desnivel (m)", "avg_hr": "FC media", "calories": "Calorías",
        "relative_effort": "Esfuerzo",
    })
    st.dataframe(comparison, use_container_width=True, hide_index=True)

    if len(selected) >= 2:
        st.markdown("#### Comparativa")
        chart_col, pace_col = st.columns(2)
        chart_data = selected[["Etiqueta", "distance_km", "avg_hr", "elevation_gain_m"]].melt(
            id_vars="Etiqueta", var_name="metric", value_name="value",
        ).dropna(subset=["value"])
        with chart_col:
            fig = px.bar(
                chart_data[chart_data["metric"].isin(["distance_km", "elevation_gain_m"])],
                x="Etiqueta", y="value", color="metric", barmode="group",
                title="Distancia y desnivel", labels={"Etiqueta": "", "value": "Valor", "metric": "Métrica"},
                color_discrete_map={"distance_km": "#0f766e", "elevation_gain_m": "#f59e0b"},
            )
            apply_plot_style(fig, 320)
            st.plotly_chart(fig, use_container_width=True)
        with pace_col:
            pace_data = selected[["Etiqueta", "pace_min_km", "avg_hr"]].melt(
                id_vars="Etiqueta", var_name="metric", value_name="value",
            ).dropna(subset=["value"])
            fig = px.bar(
                pace_data, x="Etiqueta", y="value", color="metric", barmode="group",
                title="Ritmo y frecuencia cardíaca", labels={"Etiqueta": "", "value": "Valor", "metric": "Métrica"},
                color_discrete_map={"pace_min_km": "#2563eb", "avg_hr": "#e11d48"},
            )
            fig.update_yaxes(title="min/km · bpm")
            apply_plot_style(fig, 320)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Detalle de una carrera")
    detail_id = st.selectbox("Carrera a inspeccionar", selected_ids, format_func=label, key="detail_run")
    detail = selected.loc[selected["activity_id"].astype(str) == str(detail_id)].iloc[0]
    cards = st.columns(6)
    cards[0].metric("Distancia", fmt_km(detail["distance_km"]))
    cards[1].metric("Tiempo", seconds_to_hms(detail["duration_s"]))
    cards[2].metric("Ritmo", format_pace(detail["pace_min_km"]))
    cards[3].metric("Desnivel", f"{fmt_int(detail['elevation_gain_m'])} m")
    cards[4].metric("FC media", f"{detail['avg_hr']:.0f} bpm" if pd.notna(detail["avg_hr"]) else "—")
    cards[5].metric("Calorías", fmt_int(detail["calories"]))
    if pd.notna(detail["activity_date"]):
        st.caption(f"{detail['activity_name']} · {detail['activity_date'].strftime('%d/%m/%Y %H:%M')} · {detail['activity_type']}")
    st.download_button(
        "Descargar comparación",
        data=comparison.to_csv(index=False).encode("utf-8-sig"),
        file_name="comparacion_carreras.csv",
        mime="text/csv",
    )


def render_data(df: pd.DataFrame) -> None:
    st.markdown("### Explorador de actividades")
    st.caption("Tabla limpia con las métricas más útiles. Para inspeccionar o comparar carreras, usa la sección **Carreras**.")
    display = df.copy()
    display["Fecha"] = display["activity_date"].dt.strftime("%d/%m/%Y %H:%M")
    display["Ritmo"] = display["pace_min_km"].map(format_pace)
    columns = ["Fecha", "activity_name", "activity_type", "distance_km", "duration_s", "Ritmo", "elevation_gain_m", "avg_hr", "max_hr", "calories", "relative_effort", "avg_cadence", "avg_power_w"]
    display = display[[c for c in columns if c in display]].rename(columns={"activity_name": "Actividad", "activity_type": "Tipo", "distance_km": "Distancia (km)", "duration_s": "Tiempo (s)", "elevation_gain_m": "Desnivel (m)", "avg_hr": "FC media", "max_hr": "FC máx.", "calories": "Calorías", "relative_effort": "Esfuerzo relativo", "avg_cadence": "Cadencia", "avg_power_w": "Potencia media (W)"})
    display["Tiempo (s)"] = display["Tiempo (s)"].map(seconds_to_hms)
    st.dataframe(display, use_container_width=True, hide_index=True, height=520)
    st.download_button("Descargar selección de actividades", data=display.to_csv(index=False).encode("utf-8-sig"), file_name="activities_filtradas.csv", mime="text/csv")


def render_database_reset() -> None:
    reset_state_key = "database_reset_pending"
    if reset_state_key not in st.session_state:
        st.session_state[reset_state_key] = False
    st.markdown("#### Mantenimiento")
    st.caption("Borra las actividades, los puntos GPS y el estado de importación de esta instalación. El ZIP guardado no se elimina.")
    if not st.session_state[reset_state_key]:
        if st.button("Borrar base de datos", type="secondary", key="open_database_reset"):
            st.session_state[reset_state_key] = True
            st.rerun()
    else:
        st.warning("Esta acción no se puede deshacer. Tendrás que volver a subir un ZIP de Strava para recuperar las estadísticas.")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Sí, borrar todos los datos", type="primary", key="confirm_database_reset_button"):
                try:
                    clear_database()
                    st.cache_data.clear()
                    st.session_state[reset_state_key] = False
                    st.success("Base de datos borrada. Ya puedes importar un nuevo ZIP desde esta app.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se ha podido borrar la base de datos: {exc}")
        with cancel_col:
            if st.button("Cancelar", key="cancel_database_reset"):
                st.session_state[reset_state_key] = False
                st.rerun()


# ---------- App boot ----------
init_db()

st.markdown("""
<div class="hero">
  <div style="font-size:3rem;letter-spacing:.14em;text-transform:uppercase;color:#8ce0d4;font-weight:800;margin-bottom:.6rem">GONZARUN / RUNNING LAB</div>
</div>
""", unsafe_allow_html=True)

render_database_reset()

page = st.radio(
    "Sección del dashboard",
    ["Importar datos", "Resumen", "Carreras", "Fisiología", "Evolución", "Récords", "Explorar GPS", "Datos"],
    horizontal=True,
    label_visibility="collapsed",
)
if page == "Importar datos":
    render_ingest()
    st.stop()

try:
    raw_activities = cached_activities()
except Exception as exc:
    st.error(f"No se ha podido leer la base de datos: {exc}")
    st.stop()

if raw_activities.empty:
    st.warning("La base de datos todavía está vacía. Abre la sección **Importar datos** para cargar el ZIP completo de Strava.")
    st.code("python -m running_dashboard.ingest --zip data/strava_export.zip", language="bash")
    st.stop()

# Activity selection and date filters.
all_types = sorted(raw_activities["activity_type"].dropna().astype(str).unique().tolist())
run_type_defaults = [t for t in all_types if is_running_type(t)]
with st.sidebar:
    st.markdown("## Filtros")
    st.caption("Ajusta disciplina y fechas. Todas las vistas se actualizan.")
    all_families = ["Correr", "Bici", "Natación", "Andar", "Otros"]
    available_families = [family for family in all_families if family in set(raw_activities["activity_family"])]
    selected_families = st.multiselect(
        "Disciplina",
        available_families,
        default=available_families,
        key="filter_families",
    )
    family_types = sorted(
        raw_activities.loc[raw_activities["activity_family"].isin(selected_families), "activity_type"]
        .dropna().astype(str).unique().tolist()
    )
    selected_types = st.multiselect(
        "Tipo de actividad",
        family_types,
        default=family_types,
        key="filter_types",
    )
    st.divider()
    dated = raw_activities["activity_date"].dropna()
    if len(dated):
        min_date, max_date = dated.min().date(), dated.max().date()
        date_start = st.date_input("Desde", value=min_date, min_value=min_date, max_value=max_date)
        date_end = st.date_input("Hasta", value=max_date, min_value=min_date, max_value=max_date)
    else:
        date_start = date_end = None

filtered = raw_activities[
    raw_activities["activity_family"].isin(selected_families)
    & raw_activities["activity_type"].astype(str).isin(selected_types)
].copy()
if date_start is not None and date_end is not None:
    start_ts = pd.Timestamp(date_start, tz="UTC")
    end_ts = pd.Timestamp(date_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    filtered = filtered[filtered["activity_date"].between(start_ts, end_ts) | filtered["activity_date"].isna()]
filtered = filtered.sort_values("activity_date", ascending=False, na_position="last")

if filtered.empty:
    st.info("No hay actividades para los filtros seleccionados. Cambia el tipo o el periodo en Filtros.")
    st.stop()

summary = metric_rows(filtered)
if page == "Resumen":
    render_summary(filtered, summary)
elif page == "Carreras":
    render_selected_runs(filtered)
elif page == "Fisiología":
    render_physiology(filtered)
elif page == "Evolución":
    render_evolution(filtered)
elif page == "Récords":
    render_records(filtered)
elif page == "Explorar GPS":
    render_gps(filtered)
else:
    render_data(filtered)

st.markdown("---")
