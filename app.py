# ╔══════════════════════════════════════════════════════════════════╗
# ║  CEPARD – Crecimiento y Maduración                              ║
# ║  Lee el Excel original de 11 columnas y calcula todo en Python  ║
# ╚══════════════════════════════════════════════════════════════════╝

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from datetime import datetime
import time, io, os
import re
import unicodedata

# ── Configuración de página ────────────────────────────────────────
st.set_page_config(
    page_title="CEPARD – Crecimiento y Maduración",
    page_icon="🏅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS (réplica visual del Power BI) ─────────────────────────────
st.markdown("""
<style>
  .stApp { background-color: #0e1117; }
  .block-container { padding: 0.8rem 1.5rem 0rem 1.5rem !important; }
  section[data-testid="stSidebar"] { background-color: #141929; border-right:1px solid #1e2d4a; }
  section[data-testid="stSidebar"] label, 
  section[data-testid="stSidebar"] p { color:#c0c8e0 !important; font-size:0.82rem; }
  div[data-testid="metric-container"] {
    background: linear-gradient(145deg,#0f1e36,#1a2f50);
    border:1px solid #2e4a7a; border-radius:10px; padding:14px 18px;
  }
  div[data-testid="metric-container"] label { color:#7eb8f7 !important; font-size:0.78rem; }
  div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color:#fff !important; font-size:1.7rem; font-weight:800; }
  .sec-title {
    background:linear-gradient(90deg,#122040,#0a1628);
    border-left:4px solid #4a9eff; color:#d0e8ff;
    padding:7px 14px; border-radius:0 6px 6px 0;
    font-size:0.82rem; font-weight:700; margin-bottom:6px;
    letter-spacing:0.6px; text-transform:uppercase;
  }
  .sync-ok   { background:#0e3320; color:#00d4aa; border:1px solid #00d4aa; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:700; }
  .sync-warn { background:#3a2000; color:#f6c90e; border:1px solid #f6c90e; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:700; }
  .sync-err  { background:#3a0010; color:#ff6b8a; border:1px solid #ff6b8a; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:700; }
  #MainMenu,footer,header { visibility:hidden; }
  hr { border-color:#1e2d4a !important; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
#  FÓRMULAS DE MADURACIÓN
#  Exactamente las mismas que usa Power BI internamente
# ══════════════════════════════════════════════════════════════════

def calcular_todas_las_medidas(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Recibe el Excel original con 11 columnas y calcula
    todas las medidas que Power BI genera internamente.
    """
    df = df_raw.copy()

    # ── Normalizar nombres de columna (minimiza errores por acentos/espacios)
    def _normalize(col: str) -> str:
        s = str(col).strip().lower()
        s = unicodedata.normalize('NFKD', s)
        s = ''.join(ch for ch in s if not unicodedata.combining(ch))
        s = re.sub(r"[^a-z0-9]", "", s)
        return s

    expected = {
        'nombreyapellido': 'Nombre y Apellido',
        'dni': 'DNI',
        'sexo': 'Sexo',
        'deporte': 'Deporte',
        'fechadenacimiento': 'Fecha de Nacimiento',
        'fechadeevaluacion': 'Fecha de Evaluacion',
        'alturadepie': 'Altura de Pie',
        'altura sentado': 'Altura sentado',
        'alturasentado': 'Altura sentado',
        'peso': 'Peso',
        'alturadelpadre': 'Altura del padre',
        'alturadelamadre': 'Altura de la madre',
    }

    # Renombrar columnas en el DataFrame según coincidencia normalizada.
    col_map = {}
    for col in df.columns:
        key = _normalize(col)
        if key in expected:
            col_map[col] = expected[key]
    df = df.rename(columns=col_map)

    required_cols = [
        'Nombre y Apellido', 'Sexo', 'Deporte',
        'Fecha de Nacimiento', 'Fecha de Evaluacion',
        'Altura de Pie', 'Altura sentado', 'Peso',
        'Altura del padre', 'Altura de la madre'
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Faltan columnas requeridas en el Excel: {missing}")

    df['Nombre y Apellido'] = df['Nombre y Apellido'].astype(str).str.strip()
    df['Sexo']              = df['Sexo'].astype(str).str.strip().str.upper()
    col_altura  = 'Altura de Pie'
    col_sentado = 'Altura sentado'
    col_peso    = 'Peso'

    # ── Fechas
    df['Fecha de Nacimiento'] = pd.to_datetime(df['Fecha de Nacimiento'], errors='coerce')
    df['Fecha de Evaluacion'] = pd.to_datetime(df['Fecha de Evaluacion'], errors='coerce')

    # ── Edad decimal y edad legible
    df['Edad_Decimal'] = ((df['Fecha de Evaluacion'] - df['Fecha de Nacimiento'])
                          .dt.days / 365.25).round(3)
    df['Edad_Actual']  = df['Edad_Decimal'].round(1)

    # ── Longitud de piernas
    df['Pierna'] = df[col_altura] - df[col_sentado]

    # ────────────────────────────────────────────────────────────
    #  MATURITY OFFSET  (Mirwald et al., 2002)
    #  El indicador central del dashboard
    # ────────────────────────────────────────────────────────────
    def _mo(row):
        edad    = row['Edad_Decimal']
        altura  = row[col_altura]
        sentado = row[col_sentado]
        pierna  = row['Pierna']
        peso    = row[col_peso]
        sexo    = row['Sexo']
        if pd.isna(edad) or pd.isna(altura) or altura == 0:
            return np.nan
        if sexo == 'M':
            return (-9.236
                    + 0.0002708  * (pierna * sentado)
                    - 0.001663   * (edad   * pierna)
                    + 0.007216   * (edad   * sentado)
                    + 0.02292    * (peso   / altura  * 100))
        else:  # F
            return (-9.376
                    + 0.0001882  * (pierna * sentado)
                    + 0.0022     * (edad   * pierna)
                    + 0.005841   * (edad   * sentado)
                    - 0.002658   * (edad   * peso)
                    + 0.07693    * (peso   / altura  * 100))

    df['Maturity_Offset_Actual']         = df.apply(_mo, axis=1).round(3)
    df['Maturity_Offset_Actual_Scatter'] = df['Maturity_Offset_Actual']
    df['Maturity_Offset_años']           = df['Maturity_Offset_Actual'].round(1)

    # ── Edad al PHV (Peak Height Velocity)
    df['Age_at_PHV_Final'] = (df['Edad_Decimal'] - df['Maturity_Offset_Actual']).round(3)

    # ── Altura adulta predicha (mid-parent + corrección por sexo)
    df['PAH'] = np.where(
        df['Sexo'] == 'M',
        (df['Altura del padre'] + df['Altura de la madre'] + 13) / 2,
        (df['Altura del padre'] + df['Altura de la madre'] - 13) / 2
    )

    # ── Altura en el momento del PHV (estimación)
    #    Usamos regresión lineal inversa: 
    #    altura_actual / (1 + tasa_crecimiento_restante)
    df['PHV_Height_cm']                    = (df[col_altura] / (1 + df['Maturity_Offset_Actual'].clip(0) * 0.02)).round(1)
    df['Altura_Adulta_Predicha_Actual_cm'] = df['PAH'].round(1)
    df['Altura_Pie_Actual_cm']             = df[col_altura]
    df['Peso_Actual_kg']                   = df[col_peso]

    # ── % de altura adulta predicha
    df['PHV_Porcentaje']        = ((df[col_altura] / df['PAH']) * 100).round(2)
    df['PHV_Porcentaje_Actual'] = df['PHV_Porcentaje']

    # ────────────────────────────────────────────────────────────
    #  GROWTH TEMPO  (velocidad de crecimiento cm/año)
    # ────────────────────────────────────────────────────────────
    df = df.sort_values(['Nombre y Apellido', 'Fecha de Evaluacion']).reset_index(drop=True)

    df['Altura_prev'] = df.groupby('Nombre y Apellido')[col_altura].shift(1)
    df['Fecha_prev']  = df.groupby('Nombre y Apellido')['Fecha de Evaluacion'].shift(1)
    df['Dias_diff']   = (df['Fecha de Evaluacion'] - df['Fecha_prev']).dt.days

    df['Growth_Tempo'] = np.where(
        (df['Dias_diff'] > 0) & df['Altura_prev'].notna(),
        ((df[col_altura] - df['Altura_prev']) / df['Dias_diff'] * 365.25).round(2),
        np.nan
    )
    # Para la primera evaluación de cada deportista, usar el promedio de sus valores futuros
    medias_gt = df.groupby('Nombre y Apellido')['Growth_Tempo'].transform('mean')
    df['Growth_Tempo'] = df['Growth_Tempo'].fillna(medias_gt).round(2)

    # Growth Tempo ponderado (media de las últimas 2 mediciones disponibles)
    def _gt_pond(grupo):
        vals = grupo['Growth_Tempo'].dropna().values
        if len(vals) == 0:   return pd.Series(np.nan, index=grupo.index)
        if len(vals) == 1:   return pd.Series(vals[0], index=grupo.index)
        # Ponderado: última medición tiene peso 2, penúltima peso 1
        pond = (vals[-1]*2 + vals[-2]*1) / 3 if len(vals) >= 2 else vals[-1]
        return pd.Series(round(pond, 2), index=grupo.index)

    df['Growth_Tempo_Ponderado_cm_año'] = (
        df.groupby('Nombre y Apellido', group_keys=False).apply(_gt_pond)
    )

    # Tasa de crecimiento (igual que growth tempo, col alternativa)
    df['Tasa_Crecimiento_cm_año'] = df['Growth_Tempo']

    # ── Edad biológica
    #    Bio_Age = Age_at_PHV_población_media + Maturity_Offset
    #    Medias poblacionales: ♂ ~13.8 años, ♀ ~11.8 años
    bio_media = np.where(df['Sexo'] == 'M', 13.8, 11.8)
    df['Edad_Biologica_Actual'] = (bio_media + df['Maturity_Offset_Actual']).round(2)

    # ────────────────────────────────────────────────────────────
    #  CATEGORÍAS Y GRUPOS
    # ────────────────────────────────────────────────────────────
    df['Categoria_Maduracion_Unificada'] = df['Maturity_Offset_Actual'].apply(
        lambda x: 'PRE-PHV' if x < -0.5 else ('CIRCUM-PHV' if x <= 0.5 else 'POST-PHV')
        if pd.notna(x) else '—'
    )
    df['Maturation_Group'] = df['Maturity_Offset_Actual'].apply(
        lambda x: 'Tardío' if x < -1 else ('Promedio' if x <= 1 else 'Temprano')
        if pd.notna(x) else '—'
    )
    df['Categoria_Growth_Tempo'] = df['Growth_Tempo_Ponderado_cm_año'].apply(
        lambda x: 'Acelerado' if x > 7 else ('Normal' if x > 3 else 'Desacelerado')
        if pd.notna(x) else '—'
    )

    # ────────────────────────────────────────────────────────────
    #  ALERTAS Y DECISIONES DE ENTRENAMIENTO
    # ────────────────────────────────────────────────────────────
    def _alerta_cuadrante(row):
        mo = row['Maturity_Offset_Actual']
        gt = row['Growth_Tempo_Ponderado_cm_año']
        if pd.isna(mo) or pd.isna(gt): return '—'
        if   mo < 0 and gt > 7:  return 'PRE-PHV · Alta velocidad'
        elif mo > 0 and gt > 7:  return 'POST-PHV · Alta velocidad – Riesgo sobrecarga'
        elif mo < 0 and gt <= 3: return 'PRE-PHV · Baja velocidad – Atención'
        else:                    return 'POST-PHV · Baja velocidad'

    def _decision(row):
        cat = row['Categoria_Maduracion_Unificada']
        gt  = row['Growth_Tempo_Ponderado_cm_año']
        if cat == 'PRE-PHV':
            return 'Carga moderada · Énfasis en técnica y coordinación'
        elif cat == 'CIRCUM-PHV':
            return 'Reducir volumen · Alta sensibilidad a lesiones'
        else:
            return 'Aumentar carga · Pico de adaptación neural' if (pd.notna(gt) and gt > 5) else 'Fuerza y potencia · Monitorear continuamente'

    def _alerta_phv(row):
        mo  = row['Maturity_Offset_Actual']
        pct = row['PHV_Porcentaje_Actual']
        if pd.isna(mo): return '—'
        if abs(mo) < 0.3:       return '⚠️ Circum-PHV · Mayor riesgo de lesión'
        elif pct < 88:          return 'ℹ️ Lejos de talla adulta'
        elif pct > 99:          return '✅ Cerca de talla adulta'
        return 'Sin alerta'

    df['Alerta_Cuadrante']       = df.apply(_alerta_cuadrante, axis=1)
    df['Decision_Entrenamiento'] = df.apply(_decision,         axis=1)
    df['Alerta_PHV']             = df.apply(_alerta_phv,       axis=1)

    # ── Iniciales (para los scatter charts)
    df['Iniciales'] = df['Nombre y Apellido'].apply(
        lambda n: ''.join(p[0].upper() for p in str(n).split()[:2])
    )

    # ── Columna de altura alternativa (usada en scatter INSIGHT)
    df['Altura de Pie'] = df[col_altura]

    # Limpiar columnas temporales
    df.drop(columns=['Pierna','Altura_prev','Fecha_prev','Dias_diff','PAH'],
            errors='ignore', inplace=True)

    return df


# ══════════════════════════════════════════════════════════════════
#  CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════
# Ruta relativa: el Excel debe estar en la misma carpeta que app.py
LOCAL_FILE = Path(__file__).parent / "Plantilla_Crecimiento_y_Maduracion.xlsx"


def _leer_excel(source) -> pd.DataFrame:
    """Lee Excel (ruta o bytes) y calcula todas las medidas."""
    if isinstance(source, (str, Path)):
        df_raw = pd.read_excel(source)
    else:
        df_raw = pd.read_excel(io.BytesIO(source))
    return calcular_todas_las_medidas(df_raw)


@st.cache_data(ttl=300, show_spinner=False)
def cargar_local(path: str):
    df = _leer_excel(path)
    mtime = os.path.getmtime(path)
    ts = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M:%S")
    return df, ts


@st.cache_data(ttl=300, show_spinner=False)
def cargar_onedrive(url: str):
    import urllib.request
    if "1drv.ms" in url or "sharepoint.com" in url or "onedrive.live.com" in url:
        if "download=1" not in url:
            url = (url.replace("?e=", "?download=1&e=") if "?" in url else url + "?download=1")
    if "drive.google.com" in url and "export=download" not in url:
        fid = url.split("/d/")[1].split("/")[0] if "/d/" in url else ""
        if fid:
            url = f"https://drive.google.com/uc?export=download&id={fid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    df = _leer_excel(data)
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return df, ts


# ══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🏅 CEPARD")
    st.markdown("**Crecimiento y Maduración**")
    st.divider()

    st.markdown("### 📡 Fuente de datos")
    fuente = st.radio("Origen", ["📁 Archivo local", "☁️ OneDrive / URL"],
                      label_visibility="collapsed")

    df_raw = None
    ts_carga = "—"
    fuente_ok = False

    if fuente == "☁️ OneDrive / URL":
        default_url = ""
        try:
            default_url = st.secrets.get("ONEDRIVE_URL", "")
        except Exception:
            pass
        url_input = st.text_input("URL del Excel:", value=default_url,
                                  placeholder="https://1drv.ms/x/s!...")
        c1, c2 = st.columns(2)
        with c1:
            intervalo = st.selectbox("Auto-refresh",
                ["5 min","15 min","30 min","1 hora","Desactivado"])
        with c2:
            if st.button("🔄 Ahora", use_container_width=True):
                cargar_onedrive.clear()
                st.rerun()

        if url_input:
            with st.spinner("Descargando..."):
                try:
                    df_raw, ts_carga = cargar_onedrive(url_input)
                    fuente_ok = True
                    st.markdown(f'<span class="sync-ok">✅ {ts_carga}</span>',
                                unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<span class="sync-err">❌ {str(e)[:60]}</span>',
                                unsafe_allow_html=True)

        # Auto-refresh
        if intervalo != "Desactivado" and url_input and fuente_ok:
            mins = {"5 min":5,"15 min":15,"30 min":30,"1 hora":60}[intervalo]
            if "last_refresh" not in st.session_state:
                st.session_state.last_refresh = time.time()
            if (time.time() - st.session_state.last_refresh)/60 >= mins:
                cargar_onedrive.clear()
                st.session_state.last_refresh = time.time()
                st.rerun()
    else:
        uploaded = st.file_uploader("Subir Excel actualizado:", type=["xlsx"])
        if st.button("🔄 Recargar", use_container_width=True):
            cargar_local.clear()
            st.rerun()
        if uploaded:
            try:
                df_raw   = _leer_excel(uploaded.read())
                ts_carga = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                fuente_ok = True
                st.markdown(f'<span class="sync-ok">✅ {ts_carga}</span>',
                            unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error: {e}")
        elif LOCAL_FILE.exists():
            try:
                df_raw, ts_carga = cargar_local(str(LOCAL_FILE))
                fuente_ok = True
                st.markdown(f'<span class="sync-warn">📂 Local: {ts_carga}</span>',
                            unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")
        else:
            st.warning("⚠️ No se encontró el archivo Excel.\nColocá el archivo en la misma carpeta que app.py")

    if df_raw is None:
        st.stop()

    st.divider()
    st.markdown("### 🔎 Filtros")

    todos = sorted(df_raw["Nombre y Apellido"].unique().tolist())
    dep_sel = st.multiselect("👤 DEPORTISTAS", options=todos, default=todos)
    if not dep_sel:
        dep_sel = todos

    deportes = sorted(df_raw["Deporte"].unique().tolist())
    dep_deporte = st.multiselect("⚽ Deporte", options=deportes, default=deportes)
    if not dep_deporte:
        dep_deporte = deportes

    sexos = sorted(df_raw["Sexo"].unique().tolist())
    dep_sexo = st.multiselect("⚧ Sexo", options=sexos, default=sexos)
    if not dep_sexo:
        dep_sexo = sexos

    grupos_mad = sorted(df_raw["Categoria_Maduracion_Unificada"].unique().tolist())
    dep_mad = st.multiselect("🧬 Maduración", options=grupos_mad, default=grupos_mad)
    if not dep_mad:
        dep_mad = grupos_mad

    st.divider()
    st.markdown("### 🗂️ Vista")
    pagina = st.radio("Vista",
        ["🏃 DEPORTISTAS", "👤 PERFIL", "💡 INSIGHT"],
        label_visibility="collapsed")

    st.divider()
    n_dep = df_raw["Nombre y Apellido"].nunique()
    st.caption(f"📊 {len(df_raw)} evaluaciones | {n_dep} deportistas")
    st.caption(f"🕒 {ts_carga}")


# ══════════════════════════════════════════════════════════════════
#  FILTRADO GLOBAL
# ══════════════════════════════════════════════════════════════════
mask = (
    df_raw["Nombre y Apellido"].isin(dep_sel) &
    df_raw["Deporte"].isin(dep_deporte) &
    df_raw["Sexo"].isin(dep_sexo) &
    df_raw["Categoria_Maduracion_Unificada"].isin(dep_mad)
)
df = df_raw[mask].copy()

# Última evaluación por deportista
df_last = (df.sort_values("Fecha de Evaluacion")
             .groupby("Nombre y Apellido").last().reset_index())

# ══════════════════════════════════════════════════════════════════
#  HELPERS DE UI
# ══════════════════════════════════════════════════════════════════
C_BLUE   = "#4a9eff"
C_YELLOW = "#f6c90e"
C_GREEN  = "#00d4aa"
C_RED    = "#ff6b6b"
C_DARK   = "#0e1117"

PLOT_BASE = dict(
    paper_bgcolor=C_DARK, plot_bgcolor=C_DARK, font_color="#c0c8e0",
    margin=dict(l=28, r=18, t=36, b=28),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#c0c8e0", size=11)),
    xaxis=dict(gridcolor="#14243a", zerolinecolor="#1e2d4a", tickfont=dict(size=11)),
    yaxis=dict(gridcolor="#14243a", zerolinecolor="#1e2d4a", tickfont=dict(size=11)),
)

COLOR_MAD = {
    "PRE-PHV":"#f6c90e", "CIRCUM-PHV":"#4a9eff", "POST-PHV":"#00d4aa",
    "Temprano":"#f6c90e","Promedio":"#4a9eff","Tardío":"#00d4aa",
    "Acelerado":"#00d4aa","Normal":"#4a9eff","Desacelerado":"#f6c90e",
}


def sec(txt):
    st.markdown(f'<div class="sec-title">{txt}</div>', unsafe_allow_html=True)


def tabla(df_t, cols, rename=None):
    avail = [c for c in cols if c in df_t.columns]
    tmp = df_t[avail].copy()
    if rename:
        tmp = tmp.rename(columns={k:v for k,v in rename.items() if k in tmp.columns})
    for c in tmp.select_dtypes(include="number").columns:
        tmp[c] = tmp[c].round(2)
    st.dataframe(tmp, use_container_width=True, hide_index=True)


def qlins(fig, xref=0, yref=5):
    fig.add_vline(x=xref, line_dash="dash", line_color=C_BLUE,   line_width=1, opacity=0.5)
    fig.add_hline(y=yref, line_dash="dash", line_color=C_YELLOW, line_width=1, opacity=0.5)


# ══════════════════════════════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════════════════════════════
c1, c2, c3 = st.columns([1, 6, 4])
with c1: st.markdown("## 🏅")
with c2: st.markdown("### CEPARD – Crecimiento y Maduración")
with c3:
    badge = "sync-ok" if fuente_ok else "sync-warn"
    st.markdown(
        f'<div style="text-align:right;padding-top:12px">'
        f'<span class="{badge}">⚡ {df["Nombre y Apellido"].nunique()} deportistas | {ts_carga}</span></div>',
        unsafe_allow_html=True)
st.divider()


# ══════════════════════════════════════════════════════════════════
#  VISTA: DEPORTISTAS
# ══════════════════════════════════════════════════════════════════
if pagina == "🏃 DEPORTISTAS":

    col_izq, col_der = st.columns([3, 2], gap="medium")

    with col_izq:
        # Scatter principal
        sec("📍 Donde están los deportistas de acuerdo a su desarrollo")
        fig_dev = go.Figure()
        for cat in sorted(df_last["Categoria_Maduracion_Unificada"].dropna().unique()):
            sub = df_last[df_last["Categoria_Maduracion_Unificada"] == cat]
            fig_dev.add_trace(go.Scatter(
                x=sub["Maturity_Offset_Actual_Scatter"],
                y=sub["Growth_Tempo_Ponderado_cm_año"],
                mode="markers+text",
                name=cat,
                text=sub["Iniciales"],
                textposition="top center",
                textfont=dict(size=10, color="#ddeeff"),
                marker=dict(size=13, color=COLOR_MAD.get(cat, C_BLUE),
                            line=dict(width=1.2, color="#fff")),
                customdata=sub[["Nombre y Apellido","Alerta_Cuadrante","Decision_Entrenamiento"]].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Maturity Offset: %{x:.2f} años<br>"
                    "Growth Tempo: %{y:.2f} cm/año<br>"
                    "Alerta: %{customdata[1]}<br>"
                    "Decisión: %{customdata[2]}<extra></extra>"
                ),
            ))
        qlins(fig_dev)
        for xt,yt,txt in [(-2.5,9,"PRE-PHV\nAlta vel."),(1.5,9,"POST-PHV\nAlta vel."),
                           (-2.5,1.5,"PRE-PHV\nBaja vel."),(1.5,1.5,"POST-PHV\nBaja vel.")]:
            fig_dev.add_annotation(x=xt,y=yt,text=txt,showarrow=False,
                font=dict(size=9,color="#4a6070"),bgcolor="rgba(0,0,0,0.3)")
        fig_dev.update_layout(**PLOT_BASE,
            xaxis_title="Maturity Offset (años)",
            yaxis_title="Growth Tempo Ponderado (cm/año)", height=320)
        st.plotly_chart(fig_dev, use_container_width=True)
        st.divider()

        # Barras: % Altura Adulta Predicha
        sec("📊 Porcentaje de Altura Adulta Predicha")
        df_bar = df_last.sort_values("PHV_Porcentaje_Actual", ascending=False)
        fig_bar = go.Figure(go.Bar(
            x=df_bar["Nombre y Apellido"],
            y=df_bar["PHV_Porcentaje_Actual"],
            marker_color=[C_GREEN if v>=97 else (C_BLUE if v>=90 else C_YELLOW)
                          for v in df_bar["PHV_Porcentaje_Actual"]],
            text=df_bar["PHV_Porcentaje_Actual"].round(1).astype(str)+"%",
            textposition="outside", textfont=dict(color="#fff", size=10),
            customdata=df_bar[["Nombre y Apellido","Altura_Adulta_Predicha_Actual_cm"]].values,
            hovertemplate="<b>%{customdata[0]}</b><br>%{y:.1f}% de %{customdata[1]:.0f} cm<extra></extra>",
        ))
        fig_bar.add_hline(y=100, line_dash="dot", line_color=C_GREEN, line_width=1)
        fig_bar.update_layout(**PLOT_BASE,
            xaxis_tickangle=-40, yaxis_title="% Altura Adulta Predicha",
            yaxis_range=[70, max(108, df_bar["PHV_Porcentaje_Actual"].max()+4)],
            height=270, showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_der:
        sec("🚀 Más altas de crecimiento")
        tabla(df_last.nlargest(8,"Growth_Tempo_Ponderado_cm_año"),
              ["Nombre y Apellido","Edad_Actual","Maturity_Offset_Actual","Growth_Tempo_Ponderado_cm_año"],
              {"Edad_Actual":"Edad","Maturity_Offset_Actual":"Offset","Growth_Tempo_Ponderado_cm_año":"GT cm/año"})
        st.divider()

        sec("📈 Todavía siguen creciendo  (Offset < 1)")
        siguen = df_last[df_last["Maturity_Offset_Actual"] < 1].sort_values("Maturity_Offset_Actual")
        tabla(siguen,
              ["Nombre y Apellido","Edad_Actual","Age_at_PHV_Final","PHV_Porcentaje_Actual","Maturity_Offset_Actual"],
              {"Edad_Actual":"Edad","Age_at_PHV_Final":"PHV","PHV_Porcentaje_Actual":"PHV %","Maturity_Offset_Actual":"Offset"})
        st.divider()

        sec("🎯 Cercanos al PHV  (|Offset| ≤ 0.5)")
        cercanos = df_last[df_last["Maturity_Offset_Actual"].abs() <= 0.5]
        tabla(cercanos,
              ["Nombre y Apellido","Edad_Actual","Age_at_PHV_Final","Maturity_Offset_Actual"],
              {"Edad_Actual":"Edad","Age_at_PHV_Final":"Edad PHV","Maturity_Offset_Actual":"Offset"})

    st.divider()
    c1b, c2b = st.columns(2, gap="medium")
    with c1b:
        sec("📋 Resumen – Offset y % Altura Adulta")
        tabla(df_last,
              ["Nombre y Apellido","Maturity_Offset_años","PHV_Porcentaje"],
              {"Maturity_Offset_años":"Offset (años)","PHV_Porcentaje":"PHV %"})
    with c2b:
        sec("🏷️ Grupo de Maduración")
        tabla(df_last, ["Nombre y Apellido","Maturation_Group"],
              {"Maturation_Group":"Grupo"})


# ══════════════════════════════════════════════════════════════════
#  VISTA: PERFIL
# ══════════════════════════════════════════════════════════════════
elif pagina == "👤 PERFIL":

    dep_unico = st.selectbox("👤 Seleccionar deportista:", options=dep_sel)
    df_dep    = df[df["Nombre y Apellido"] == dep_unico].sort_values("Fecha de Evaluacion")
    if len(df_dep) == 0:
        st.error("Sin datos con los filtros actuales.")
        st.stop()
    last = df_dep.iloc[-1]

    # KPIs
    st.markdown("#### Indicadores Actuales")
    k1,k2,k3,k4,k5,k6 = st.columns(6)
    k1.metric("⚖️ Peso (kg)",        f"{last.get('Peso_Actual_kg',0):.1f}")
    k2.metric("📏 Altura (cm)",       f"{last.get('Altura_Pie_Actual_cm',0):.1f}")
    k3.metric("🧬 Edad Biológica",    f"{last.get('Edad_Biologica_Actual',0):.1f}")
    k4.metric("📅 Edad Decimal",      f"{last.get('Edad_Actual',0):.1f}")
    k5.metric("🎯 Etapa",             str(last.get("Categoria_Maduracion_Unificada","—")))
    k6.metric("🏃 Ritmo",             str(last.get("Categoria_Growth_Tempo","—")))
    st.divider()

    c_g, c_c = st.columns([2,3], gap="medium")

    with c_g:
        # Gauge % Altura Adulta
        phv_pct = float(last.get("PHV_Porcentaje_Actual", 90))
        fig_g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=phv_pct,
            number={"suffix":"%","font":{"color":"#fff","size":30}},
            gauge={"axis":{"range":[70,105],"tickcolor":C_BLUE},
                   "bar":{"color":C_BLUE,"thickness":0.25},
                   "bgcolor":"#0a1628","bordercolor":"#2e4a7a",
                   "steps":[{"range":[70,88],"color":"#0a1628"},
                             {"range":[88,95],"color":"#122040"},
                             {"range":[95,100],"color":"#0e3020"},
                             {"range":[100,105],"color":"rgba(0,212,170,0.13)"}],
                   "threshold":{"line":{"color":C_YELLOW,"width":3},"thickness":0.8,"value":100}},
            title={"text":"Altura Adulta Predicha %","font":{"color":C_BLUE,"size":12}},
        ))
        fig_g.update_layout(paper_bgcolor=C_DARK, font_color="#c0c8e0",
                            height=210, margin=dict(l=20,r=20,t=50,b=10))
        st.plotly_chart(fig_g, use_container_width=True)

        ca, cb = st.columns(2)
        ca.metric("🎯 Alt. Adulta",   f"{last.get('Altura_Adulta_Predicha_Actual_cm',0):.0f} cm")
        cb.metric("📌 Deporte",       str(last.get("Deporte","—")))
        st.divider()

        # Tachómetro Growth Tempo
        gt_val = float(last.get("Growth_Tempo_Ponderado_cm_año", 0))
        fig_t = go.Figure(go.Indicator(
            mode="gauge+number",
            value=gt_val,
            number={"suffix":" cm/año","font":{"color":"#fff","size":22}},
            gauge={"axis":{"range":[0,15],"tickcolor":C_BLUE},
                   "bar":{"color":C_YELLOW,"thickness":0.25},
                   "bgcolor":"#0a1628","bordercolor":"#2e4a7a",
                   "steps":[{"range":[0,4],"color":"#0a1628"},
                             {"range":[4,8],"color":"#0e1e2a"},
                             {"range":[8,12],"color":"#0a2010"},
                             {"range":[12,15],"color":"rgba(0,212,170,0.13)"}],
                   "threshold":{"line":{"color":C_RED,"width":3},"thickness":0.8,"value":12}},
            title={"text":"Tasa de Crecimiento (cm/año)","font":{"color":C_BLUE,"size":12}},
        ))
        fig_t.update_layout(paper_bgcolor=C_DARK, font_color="#c0c8e0",
                            height=205, margin=dict(l=20,r=20,t=50,b=10))
        st.plotly_chart(fig_t, use_container_width=True)

        alerta = str(last.get("Alerta_PHV",""))
        if alerta and alerta not in ["—","Sin alerta"]:
            st.info(f"**{alerta}**")

    with c_c:
        sec("📉 Evolución Tasa de Crecimiento")
        fig_lc = go.Figure()
        fig_lc.add_trace(go.Scatter(
            x=df_dep["Fecha de Evaluacion"], y=df_dep["Tasa_Crecimiento_cm_año"],
            mode="lines+markers", name="Tasa",
            line=dict(color=C_BLUE, width=2.5),
            marker=dict(size=8, color=C_BLUE, line=dict(width=1.5,color="#fff")),
            fill="tozeroy", fillcolor="rgba(74,158,255,0.12)",
            hovertemplate="%{x|%d/%m/%Y}: <b>%{y:.2f} cm/año</b><extra></extra>",
        ))
        fig_lc.add_trace(go.Scatter(
            x=df_dep["Fecha de Evaluacion"], y=df_dep["Growth_Tempo_Ponderado_cm_año"],
            mode="lines+markers", name="GT Ponderado",
            line=dict(color=C_YELLOW, width=2, dash="dot"),
            marker=dict(size=6, color=C_YELLOW),
            hovertemplate="%{x|%d/%m/%Y}: <b>%{y:.2f} cm/año</b><extra></extra>",
        ))
        fig_lc.update_layout(**PLOT_BASE, xaxis_title="Fecha", yaxis_title="cm/año", height=215)
        st.plotly_chart(fig_lc, use_container_width=True)
        st.divider()

        sec("📋 Indicadores Claves de Rendimiento (historial completo)")
        tabla(df_dep,
              ["Fecha de Evaluacion","Edad_Actual","Altura_Pie_Actual_cm","Peso_Actual_kg",
               "Maturity_Offset_Actual","Age_at_PHV_Final","PHV_Porcentaje_Actual",
               "Growth_Tempo_Ponderado_cm_año","Altura_Adulta_Predicha_Actual_cm"],
              {"Fecha de Evaluacion":"Fecha","Edad_Actual":"Edad",
               "Altura_Pie_Actual_cm":"Altura","Peso_Actual_kg":"Peso",
               "Maturity_Offset_Actual":"Offset","Age_at_PHV_Final":"PHV",
               "PHV_Porcentaje_Actual":"PHV %","Growth_Tempo_Ponderado_cm_año":"GT",
               "Altura_Adulta_Predicha_Actual_cm":"Alt.Adulta"})

    st.divider()
    sec("🎯 Perfil de Crecimiento y Maduración vs Grupo")
    fig_pf = go.Figure()
    for cat in sorted(df_last["Categoria_Maduracion_Unificada"].dropna().unique()):
        otros = df_last[(df_last["Categoria_Maduracion_Unificada"]==cat) &
                        (df_last["Nombre y Apellido"]!=dep_unico)]
        if len(otros):
            fig_pf.add_trace(go.Scatter(
                x=otros["Maturity_Offset_Actual"], y=otros["Growth_Tempo_Ponderado_cm_año"],
                mode="markers+text", name=cat, text=otros["Iniciales"],
                textposition="top center", textfont=dict(size=9,color="#506070"),
                marker=dict(size=9,color=COLOR_MAD.get(cat,C_BLUE),opacity=0.5,
                            line=dict(width=0.5,color="#fff")),
                hovertemplate="<b>%{text}</b><br>Offset:%{x:.2f}<br>GT:%{y:.2f}<extra></extra>",
            ))
    dep_last_row = df_last[df_last["Nombre y Apellido"]==dep_unico]
    if len(dep_last_row):
        r = dep_last_row.iloc[0]
        fig_pf.add_trace(go.Scatter(
            x=[r["Maturity_Offset_Actual"]], y=[r["Growth_Tempo_Ponderado_cm_año"]],
            mode="markers+text", name=dep_unico, text=[r["Iniciales"]],
            textposition="top right", textfont=dict(size=13,color=C_YELLOW,family="Arial Black"),
            marker=dict(size=20,color=C_YELLOW,symbol="star",line=dict(width=2,color="#fff")),
            hovertemplate=f"<b>{dep_unico}</b><br>Offset:%{{x:.2f}}<br>GT:%{{y:.2f}}<extra></extra>",
        ))
    qlins(fig_pf)
    fig_pf.update_layout(**PLOT_BASE, xaxis_title="Maturity Offset (años)",
                         yaxis_title="Growth Tempo (cm/año)", height=300)
    st.plotly_chart(fig_pf, use_container_width=True)

    decision = str(last.get("Decision_Entrenamiento","—"))
    if decision != "—":
        st.info(f"💡 **Decisión de entrenamiento sugerida:** {decision}")


# ══════════════════════════════════════════════════════════════════
#  VISTA: INSIGHT
# ══════════════════════════════════════════════════════════════════
elif pagina == "💡 INSIGHT":

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        sec("📐 Crecimiento según Edad Decimal")
        fig_i1 = go.Figure()
        for cat in sorted(df["Categoria_Maduracion_Unificada"].dropna().unique()):
            sub = df[df["Categoria_Maduracion_Unificada"]==cat]
            fig_i1.add_trace(go.Scatter(
                x=sub["Edad_Decimal"], y=sub["Altura de Pie"],
                mode="markers", name=cat,
                marker=dict(size=8,color=COLOR_MAD.get(cat,C_BLUE),opacity=0.85,
                            line=dict(width=0.5,color="#fff")),
                customdata=sub["Nombre y Apellido"],
                hovertemplate="<b>%{customdata}</b><br>Edad:%{x:.2f}<br>Altura:%{y:.1f} cm<extra></extra>",
            ))
        fig_i1.update_layout(**PLOT_BASE,
            xaxis_title="Edad Decimal (años)", yaxis_title="Altura de Pie (cm)", height=340)
        st.plotly_chart(fig_i1, use_container_width=True)

    with c2:
        sec("📈 Curvas de Growth Tempo individuales")
        fig_i2 = go.Figure()
        colores = px.colors.qualitative.Set2
        for i, dep in enumerate(sorted(df["Nombre y Apellido"].unique())):
            sub = df[df["Nombre y Apellido"]==dep].sort_values("Edad_Decimal")
            clr = colores[i % len(colores)]
            fig_i2.add_trace(go.Scatter(
                x=sub["Edad_Decimal"], y=sub["Growth_Tempo"],
                mode="lines+markers", name=dep,
                line=dict(color=clr, width=1.8), marker=dict(size=5, color=clr),
                hovertemplate=f"<b>{dep}</b><br>Edad:%{{x:.2f}}<br>GT:%{{y:.2f}} cm/año<extra></extra>",
            ))
        fig_i2.update_layout(**PLOT_BASE,
            xaxis_title="Edad Decimal (años)", yaxis_title="Growth Tempo (cm/año)", height=340)
        st.plotly_chart(fig_i2, use_container_width=True)

    st.divider()
    sec("📊 Estadísticas del Grupo")
    num_cols = ["Edad_Actual","Altura_Pie_Actual_cm","Peso_Actual_kg",
                "Maturity_Offset_Actual","PHV_Porcentaje_Actual",
                "Growth_Tempo_Ponderado_cm_año","Tasa_Crecimiento_cm_año",
                "Age_at_PHV_Final","Edad_Biologica_Actual"]
    exist = [c for c in num_cols if c in df_last.columns]
    stats = df_last[exist].describe().T[["count","mean","std","min","50%","max"]]
    stats.columns = ["N","Media","Desvío","Min","Mediana","Max"]
    stats.index   = [c.replace("_"," ") for c in stats.index]
    st.dataframe(stats.round(2), use_container_width=True)

    st.divider()
    c3, c4, c5 = st.columns(3, gap="medium")
    for col_c, campo, titulo in [
        (c3, "Categoria_Maduracion_Unificada", "🥧 Distribución Maduración"),
        (c4, "Categoria_Growth_Tempo",         "🥧 Distribución Growth Tempo"),
        (c5, "Deporte",                        "🥧 Distribución por Deporte"),
    ]:
        with col_c:
            sec(titulo)
            if campo in df_last.columns:
                dist = df_last[campo].value_counts().reset_index()
                dist.columns = ["Cat","N"]
                fig_pie = px.pie(dist, names="Cat", values="N",
                                 color="Cat", color_discrete_map=COLOR_MAD, hole=0.45)
                fig_pie.update_layout(paper_bgcolor=C_DARK, font_color="#c0c8e0",
                                      legend_bgcolor="rgba(0,0,0,0)", height=260,
                                      margin=dict(l=10,r=10,t=30,b=10))
                st.plotly_chart(fig_pie, use_container_width=True)
