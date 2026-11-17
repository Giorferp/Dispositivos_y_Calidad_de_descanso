# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pandas>=2.2",
#   "numpy>=1.26",
#   "matplotlib>=3.8",
#   "seaborn>=0.13",
#   "scipy>=1.12",
#   "statsmodels>=0.14",
#   "openpyxl>=3.1",
# ]
# ///
"""
Gráficos descriptivos, cuadros estadísticos y verificación inferencial del
informe final (EECA-UCV, 2026-01S).

Ejecución:  uv run generar_graficos.py

Salidas:
  - grafico_*.png               (directorio de trabajo, 300 dpi)
  - cuadros_resultados.tex      (cuadros con booktabs, \\input desde el informe)
  - cuadros_resultados.md       (los mismos cuadros en Markdown para el .ipynb)
  - resultados_inferencia.json  (estadísticos usados en el texto del informe)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
from matplotlib.ticker import MaxNLocator
from scipy import stats

RAIZ = Path(__file__).resolve().parent
ARCHIVO = RAIZ / "Encuesta sobre uso de dispositivos y calidad del sueño (Respuestas).xlsx"
N_VALIDO = 28

# ---------------------------------------------------------------------------
# 1. Carga y depuración (n = 28, excluye la fila 29 posterior al corte)
# ---------------------------------------------------------------------------
crudo = pd.read_excel(ARCHIVO)
crudo = crudo.iloc[:N_VALIDO].copy()
assert len(crudo) == N_VALIDO

df = crudo.drop(columns=["Marca temporal"])
df.columns = [f"Pregunta {i}" for i in range(1, 13)]
for c in df.select_dtypes(include=["object", "string"]).columns:
    df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)

df["Edad"] = pd.to_numeric(
    df["Pregunta 2"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"
).astype("int64")


def a_horas(v) -> float:
    if hasattr(v, "hour"):
        return v.hour + v.minute / 60.0
    h, m = str(v).split(":")[:2]
    return int(h) + int(m) / 60.0


def corregir_acostarse(h: pd.Series) -> np.ndarray:
    """Corrige ambigüedad 12 a. m./12 p. m. documentada en el Diagnóstico."""
    a = h.to_numpy(dtype=float)
    return np.where((a >= 8) & (a < 12), a + 12, np.where((a >= 12) & (a < 13), a - 12, a))


lev_sem = df["Pregunta 7"].apply(a_horas).to_numpy(float)
aco_sem = corregir_acostarse(df["Pregunta 8"].apply(a_horas))
lev_fin = df["Pregunta 9"].apply(a_horas).to_numpy(float)
aco_fin = corregir_acostarse(df["Pregunta 10"].apply(a_horas))

sem = np.where(aco_sem >= 14, 24 - aco_sem + lev_sem, lev_sem - aco_sem)
fin = np.where(aco_fin >= 14, 24 - aco_fin + lev_fin, lev_fin - aco_fin)
inconsistente = (df["Pregunta 8"].apply(a_horas).to_numpy(float) == lev_sem) | (sem <= 0)
sem[inconsistente] = np.sort(sem[~inconsistente])[0]  # cota mínima válida = 4,00 h

df["Sueno_Semana"] = sem
df["Sueno_Finde"] = fin
df["Sueno_Ponderado"] = (5 * sem + 2 * fin) / 7
df["Compensacion_Finde"] = fin - sem

ORDEN_TIEMPO = [
    "Menos de 30 minutos",
    "De 30 a 59 minutos",
    "De 60 a 119 minutos",
    "120 a 179 minutos",
    "180 minutos o más",
]
ETQ_TIEMPO = ["< 30 min", "30–59 min", "60–119 min", "120–179 min", "≥ 180 min"]
ETQ_TIEMPO_TEX = [r"$<$ 30 min", "30--59 min", "60--119 min", "120--179 min", r"$\ge$ 180 min"]
MINUTOS = dict(zip(ORDEN_TIEMPO, [15.0, 44.5, 89.5, 149.5, 195.0]))
TRAMOS = ["< 60 min", "60 a 119 min", "120 min o más"]
A_TRAMO = dict(zip(ORDEN_TIEMPO, [TRAMOS[0], TRAMOS[0], TRAMOS[1], TRAMOS[2], TRAMOS[2]]))

df["Minutos_Pantalla"] = df["Pregunta 5"].map(MINUTOS)
df["Tiempo_Cat"] = pd.Categorical(df["Pregunta 5"], ORDEN_TIEMPO, ordered=True)
df["Tramo_Pantalla"] = pd.Categorical(df["Pregunta 5"].map(A_TRAMO), TRAMOS, ordered=True)

SENSACION = {
    "Energía suficiente para toda la jornada académica.": "Energía suficiente",
    "Cansancio leve que desaparece tras la primera hora.": "Cansancio leve",
    "Somnolencia persistente que afecta su concentración en clases.": "Somnolencia persistente",
}
ORDEN_SENSACION = [
    "Energía suficiente",
    "Cansancio leve",
    "Somnolencia persistente",
    "Agotamiento severo",
]
df["Sensacion"] = pd.Categorical(df["Pregunta 12"].map(SENSACION), ORDEN_SENSACION, ordered=True)
df["Calidad_Sueño"] = df["Sensacion"].map(
    {"Somnolencia persistente": 1, "Cansancio leve": 2, "Energía suficiente": 3}
).astype(int)

ORDEN_DESP = ["Ninguna", "Una vez", "Dos veces", "3 o más veces"]
df["Despertares"] = pd.Categorical(df["Pregunta 11"], ORDEN_DESP, ordered=True)
df["Despertares_Num"] = df["Despertares"].cat.codes

CICLOS_TEX = [
    r"Básico (1.\textsuperscript{o}--3.\textsuperscript{o})",
    r"Intermedio (4.\textsuperscript{o}--6.\textsuperscript{o})",
    r"Finales (7.\textsuperscript{o}--10.\textsuperscript{o})",
]
CICLOS = ["Básico (1.º–3.º)", "Intermedio (4.º–6.º)", "Finales (7.º–10.º)"]
df["Ciclo"] = pd.cut(df["Pregunta 3"], bins=[0, 3, 6, 10], labels=CICLOS)

ORDEN_DISP = [
    "Teléfono Inteligente",
    "Televisor / Smart TV",
    "Computadora de escritorio",
    "Computadora portátil",
]
ETQ_DISP = {
    "Teléfono Inteligente": "Teléfono inteligente",
    "Televisor / Smart TV": "Televisor / Smart TV",
    "Computadora de escritorio": "Computadora de escritorio",
    "Computadora portátil": "Computadora portátil",
}
ACT = {
    "Redes sociales / Mensajería": "Redes sociales / mensajería",
    "Estudio / Realización de Asignaciones universitarias": "Estudio / asignaciones UCV",
    "Videojuegos": "Videojuegos",
    "Trabajo": "Trabajo",
    "Otro": "Otra actividad",
}
df["Actividad"] = df["Pregunta 6"].map(ACT)
assert df["Actividad"].notna().all() and df["Sensacion"].notna().all()

# ---------------------------------------------------------------------------
# 2. Estética académica sobria
# ---------------------------------------------------------------------------
sns.set_theme(style="ticks", context="paper")
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 10.5,
    "axes.titlesize": 11,
    "axes.labelsize": 10.5,
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "legend.fontsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": "#d9d9d9",
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})
TINTA = "#3b4a5a"
AZUL_ACERO = "#556f87"
AZUL_CLARO = "#b9c7d5"
GRISES = ["#dce3ea", "#b4c2d0", "#8297ac", "#4d6277", "#2c3947"]


def coma(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def etiqueta(n: int, total: int = N_VALIDO) -> str:
    return f"{n}\n({coma(100 * n / total)} %)"


def barras_univariadas(
    conteos: pd.Series,
    xlabel: str,
    archivo: str,
    horizontal: bool = False,
    ancho: float = 6.4,
    alto: float = 3.4,
) -> None:
    fig, ax = plt.subplots(figsize=(ancho, alto))
    pos = np.arange(len(conteos))
    if horizontal:
        ax.barh(pos, conteos.values, color=TINTA, height=0.6)
        ax.set_yticks(pos, conteos.index)
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        for p, v in zip(pos, conteos.values):
            ax.text(v + 0.25, p, f"{v} ({coma(100 * v / N_VALIDO)} %)", va="center", fontsize=9)
        ax.set_xlabel("Frecuencia absoluta ($n_i$)")
        ax.set_xlim(0, conteos.max() * 1.32)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    else:
        ax.bar(pos, conteos.values, color=TINTA, width=0.6)
        ax.set_xticks(pos, conteos.index)
        for p, v in zip(pos, conteos.values):
            ax.text(
                p,
                v + 0.25,
                etiqueta(v),
                ha="center",
                va="bottom",
                fontsize=8.8,
                linespacing=1.1,
            )
        ax.set_ylabel("Frecuencia absoluta ($n_i$)")
        ax.set_xlabel(xlabel)
        ax.set_ylim(0, conteos.max() * 1.30)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.savefig(RAIZ / archivo)
    plt.close(fig)


def barras_apiladas(
    tabla: pd.DataFrame,
    xlabel: str,
    leyenda: str,
    archivo: str,
    porcentaje: bool = False,
    alto: float = 3.5,
) -> None:
    datos = tabla.div(tabla.sum(axis=1), axis=0) * 100 if porcentaje else tabla
    k = tabla.shape[1]
    paleta = GRISES[-k:] if k <= len(GRISES) else sns.color_palette("Greys", k)
    fig, ax = plt.subplots(figsize=(6.6, alto))
    izq = np.zeros(len(tabla))
    pos = np.arange(len(tabla))
    for j, col in enumerate(tabla.columns):
        vals = datos[col].to_numpy(float)
        ax.barh(
            pos,
            vals,
            left=izq,
            color=paleta[j],
            edgecolor="white",
            linewidth=0.8,
            height=0.6,
            label=col,
        )
        for p, base, v, n in zip(pos, izq, vals, tabla[col].to_numpy()):
            if n > 0:
                claro = j >= k - 2 if k > 2 else j == k - 1
                txt = f"{n}" if not porcentaje else f"{n}\n({coma(v, 1)} %)"
                umbral = 7 if porcentaje else 0.6
                if v >= umbral:
                    ax.text(
                        base + v / 2,
                        p,
                        txt,
                        ha="center",
                        va="center",
                        fontsize=8.2,
                        color="white" if claro else "black",
                        linespacing=1.0,
                    )
        izq += vals
    etiquetas = [f"{g}  (n = {int(t)})" for g, t in zip(tabla.index, tabla.sum(axis=1))]
    ax.set_yticks(pos, etiquetas)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    if porcentaje:
        ax.set_xlim(0, 100)
        ax.set_xlabel("Porcentaje condicional por fila (%)")
    else:
        ax.set_xlim(0, tabla.sum(axis=1).max() * 1.05)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("Frecuencia absoluta ($n_{ij}$)")
    ax.set_ylabel(xlabel)
    ax.legend(
        title=leyenda,
        ncol=min(k, 5),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        frameon=False,
        columnspacing=1.0,
        handlelength=1.2,
        title_fontsize=9,
    )
    fig.savefig(RAIZ / archivo)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 3. Gráficos univariados (excluyendo Preguntas 7-10 afectadas por 12 a.m./12 p.m.)
# ---------------------------------------------------------------------------
sexo = df["Pregunta 1"].value_counts().reindex(["Femenino", "Masculino"])
barras_univariadas(sexo, "Sexo", "grafico_sexo.png", ancho=4.6)

edad_cls = pd.cut(
    df["Edad"],
    bins=[17, 19, 21, 23, 25, 30, 60],
    labels=["18–19", "20–21", "22–23", "24–25", "26–30", "31 o más"],
)
barras_univariadas(
    edad_cls.value_counts(sort=False),
    "Edad (años cumplidos)",
    "grafico_edad.png",
)

sem_cnt = df["Pregunta 3"].value_counts().reindex(range(1, 11), fill_value=0)
sem_cnt.index = [f"{i}.º" for i in sem_cnt.index]
barras_univariadas(
    sem_cnt,
    "Semestre (materia del semestre más bajo)",
    "grafico_semestre.png",
    ancho=6.8,
)

disp = df["Pregunta 4"].value_counts().reindex(ORDEN_DISP)
disp.index = [ETQ_DISP[i] for i in disp.index]
barras_univariadas(
    disp,
    "",
    "grafico_dispositivo.png",
    horizontal=True,
    alto=2.6,
)

tiempo = df["Tiempo_Cat"].value_counts(sort=False)
tiempo.index = ETQ_TIEMPO
barras_univariadas(
    tiempo,
    "Minutos promedio previos a conciliar el sueño",
    "grafico_tiempo_pantalla.png",
)

act = df["Actividad"].value_counts()
barras_univariadas(
    act,
    "",
    "grafico_actividad.png",
    horizontal=True,
    alto=2.8,
)

desp = df["Despertares"].value_counts(sort=False)
barras_univariadas(
    desp,
    "Frecuencia habitual de despertares",
    "grafico_despertares.png",
    ancho=5.6,
)

sens = df["Sensacion"].value_counts(sort=False)
barras_univariadas(
    sens,
    "Categoría de recuperación matutina (Pregunta 12)",
    "grafico_sensacion.png",
    ancho=6.4,
)

# ---------------------------------------------------------------------------
# 4. Gráficos bivariados del Plan de Tabulaciones Básicas
# ---------------------------------------------------------------------------
ct_disp_t = pd.crosstab(df["Pregunta 4"], df["Tiempo_Cat"], dropna=False).reindex(ORDEN_DISP)
ct_disp_t.index = [ETQ_DISP[i] for i in ct_disp_t.index]
ct_disp_t.columns = ETQ_TIEMPO
barras_apiladas(
    ct_disp_t,
    "Dispositivo principal",
    "Tiempo de uso",
    "grafico_dispositivo_tiempo.png",
)

ct_tramo_cal = pd.crosstab(df["Tramo_Pantalla"], df["Sensacion"], dropna=False)
ct_tramo_cal = ct_tramo_cal[ORDEN_SENSACION[:3]]
barras_apiladas(
    ct_tramo_cal,
    "Tiempo de uso nocturno",
    "Sensación al despertar",
    "grafico_tiempo_calidad.png",
    porcentaje=True,
    alto=3.2,
)

ct_ciclo_desp = pd.crosstab(df["Ciclo"], df["Despertares"], dropna=False)
barras_apiladas(
    ct_ciclo_desp,
    "Ciclo académico",
    "Despertares por noche",
    "grafico_ciclo_despertares.png",
    alto=3.0,
)

# ---------------------------------------------------------------------------
# 4b. Gráficos analíticos e inferenciales unificados (misma estética sobria)
# ---------------------------------------------------------------------------
# Gráfico 12: Dispersión y recta MCO
fig, ax = plt.subplots(figsize=(6.4, 3.8))
sns.regplot(
    data=df,
    x="Minutos_Pantalla",
    y="Sueno_Semana",
    ax=ax,
    scatter_kws={"color": TINTA, "s": 42, "alpha": 0.85, "edgecolor": "white", "linewidths": 0.5},
    line_kws={"color": "#1f2933", "linestyle": "--", "linewidth": 1.6, "label": "Tendencia MCO"},
    ci=95,
)
for poly in ax.collections:
    if poly not in ax.collections[:1]:
        poly.set_facecolor(AZUL_CLARO)
        poly.set_alpha(0.32)
ax.set_xlabel("Tiempo de uso nocturno (minutos)")
ax.set_ylabel("Horas de sueño en días lectivos")
ax.set_xticks([15, 44.5, 89.5, 149.5, 195])
ax.set_xticklabels(["15", "44,5", "89,5", "149,5", "195"])
ax.yaxis.set_major_locator(MaxNLocator(integer=True))
ax.legend(frameon=False, loc="upper right")
fig.savefig(RAIZ / "grafico1_dispersion.png")
plt.close(fig)

# Gráfico 13: Calidad promedio al despertar según tramo de pantalla
medias_cal = df.groupby("Tramo_Pantalla", observed=False)["Calidad_Sueño"].mean()
fig, ax = plt.subplots(figsize=(6.0, 3.6))
pos_c = np.arange(len(medias_cal))
ax.bar(pos_c, medias_cal.values, color=[AZUL_CLARO, AZUL_ACERO, TINTA], edgecolor="#2c3947", linewidth=0.8, width=0.52)
ax.set_xticks(pos_c, medias_cal.index)
ax.set_xlabel("Tiempo de uso nocturno")
ax.set_ylabel("Puntaje promedio (1: Somnolencia a 3: Energía)")
ax.set_ylim(1.2, 2.18)
for p, v in zip(pos_c, medias_cal.values):
    ax.text(p, v + 0.025, coma(v, 2), ha="center", va="bottom", fontsize=9.5, fontweight="bold", color="#1f2933")
fig.savefig(RAIZ / "grafico2_calidad_pantallas.png")
plt.close(fig)

# Gráfico 14: Comparación semanal vs fin de semana (diagrama de cajas)
datos_cajas = pd.melt(
    df[["Sueno_Semana", "Sueno_Finde"]].rename(
        columns={"Sueno_Semana": "Lunes a Viernes", "Sueno_Finde": "Fin de Semana"}
    ),
    var_name="Periodo",
    value_name="Horas",
)
fig, ax = plt.subplots(figsize=(5.6, 3.8))
sns.boxplot(
    data=datos_cajas,
    x="Periodo",
    y="Horas",
    hue="Periodo",
    width=0.42,
    palette={"Lunes a Viernes": AZUL_CLARO, "Fin de Semana": AZUL_ACERO},
    linewidth=1.1,
    fliersize=0,
    legend=False,
    ax=ax,
)
sns.stripplot(
    data=datos_cajas,
    x="Periodo",
    y="Horas",
    color="#1f2933",
    alpha=0.6,
    size=4.2,
    jitter=0.09,
    ax=ax,
)
ax.axhline(7, color="#4d6277", linestyle=":", linewidth=1.4, label="Mínimo recomendado (7 h)")
ax.set_xlabel("")
ax.set_ylabel("Horas calculadas de sueño")
ax.yaxis.set_major_locator(MaxNLocator(integer=True))
ax.legend(frameon=False, loc="upper left")
fig.savefig(RAIZ / "grafico3_semana_vs_finde.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 5. Inferencia estadística completa (n = 28)
# ---------------------------------------------------------------------------
n = N_VALIDO
gl = n - 1
tcrit = stats.t.ppf(0.975, gl)


def ic(x):
    x = np.asarray(x, float)
    m, se = x.mean(), stats.sem(x)
    return m, x.std(ddof=1), se, m - tcrit * se, m + tcrit * se


R: dict = {"n": n, "gl_t": gl, "t_critico_0975": tcrit}
for nombre, col in [
    ("semana", "Sueno_Semana"),
    ("finde", "Sueno_Finde"),
    ("delta", "Compensacion_Finde"),
]:
    m, s, se, li, ls = ic(df[col])
    R[f"ic_{nombre}"] = dict(media=m, s=s, se=se, li=li, ls=ls)

sw = {c: stats.shapiro(df[c]) for c in ["Sueno_Semana", "Sueno_Finde", "Compensacion_Finde"]}
R["shapiro"] = {c: dict(W=float(v.statistic), p=float(v.pvalue)) for c, v in sw.items()}

t1 = stats.ttest_1samp(df["Sueno_Semana"], 7.0, alternative="less")
R["prueba1"] = dict(t=float(t1.statistic), p=float(t1.pvalue), gl=gl)

t2u = stats.ttest_rel(df["Sueno_Finde"], df["Sueno_Semana"], alternative="greater")
t2b = stats.ttest_rel(df["Sueno_Finde"], df["Sueno_Semana"])
w2u = stats.wilcoxon(df["Sueno_Finde"], df["Sueno_Semana"], alternative="greater")
w2b = stats.wilcoxon(df["Sueno_Finde"], df["Sueno_Semana"])
R["prueba2"] = dict(
    t=float(t2u.statistic),
    p_unilateral=float(t2u.pvalue),
    p_bilateral=float(t2b.pvalue),
    gl=gl,
    W=float(w2b.statistic),
    p_wilcoxon_bilateral=float(w2b.pvalue),
    p_wilcoxon_unilateral=float(w2u.pvalue),
)

X = sm.add_constant(df["Minutos_Pantalla"])
ols = sm.OLS(df["Sueno_Semana"], X).fit()
jb = sm.stats.stattools.jarque_bera(ols.resid)
R["ols"] = dict(
    b0=ols.params.iloc[0],
    b1=ols.params.iloc[1],
    se0=ols.bse.iloc[0],
    se1=ols.bse.iloc[1],
    t0=ols.tvalues.iloc[0],
    t1=ols.tvalues.iloc[1],
    p0=ols.pvalues.iloc[0],
    p1=ols.pvalues.iloc[1],
    ci0=list(ols.conf_int().iloc[0]),
    ci1=list(ols.conf_int().iloc[1]),
    r2=ols.rsquared,
    r2a=ols.rsquared_adj,
    F=ols.fvalue,
    pF=ols.f_pvalue,
    gl1=int(ols.df_model),
    gl2=int(ols.df_resid),
    dw=float(sm.stats.stattools.durbin_watson(ols.resid)),
    jb=float(jb[0]),
    pjb=float(jb[1]),
    sw_resid=dict(zip(["W", "p"], map(float, stats.shapiro(ols.resid)))),
)

pr = stats.pearsonr(df["Minutos_Pantalla"], df["Sueno_Semana"])
sp_cal = stats.spearmanr(df["Minutos_Pantalla"], df["Calidad_Sueño"])
sp_desp = stats.spearmanr(df["Minutos_Pantalla"], df["Despertares_Num"])
R["correlaciones"] = dict(
    pearson_sueno=dict(r=float(pr.statistic), p=float(pr.pvalue)),
    spearman_calidad=dict(r=float(sp_cal.statistic), p=float(sp_cal.pvalue)),
    spearman_despertares=dict(r=float(sp_desp.statistic), p=float(sp_desp.pvalue)),
    gl=n - 2,
)

chi = stats.chi2_contingency(ct_tramo_cal.to_numpy())
ct_5x3 = pd.crosstab(df["Tiempo_Cat"], df["Sensacion"], dropna=False)[ORDEN_SENSACION[:3]]
chi_5x3 = stats.chi2_contingency(ct_5x3.to_numpy())
R["chi2_tramo_calidad"] = dict(
    chi2=float(chi.statistic),
    gl=int(chi.dof),
    p=float(chi.pvalue),
    prop_esperadas_menor5=float((chi.expected_freq < 5).mean()),
)
R["chi2_5x3_calidad"] = dict(
    chi2=float(chi_5x3.statistic),
    gl=int(chi_5x3.dof),
    p=float(chi_5x3.pvalue),
    prop_esperadas_menor5=float((chi_5x3.expected_freq < 5).mean()),
)
R["medias_calidad_tramo"] = df.groupby("Tramo_Pantalla", observed=False)["Calidad_Sueño"].mean().to_dict()

(RAIZ / "resultados_inferencia.json").write_text(
    json.dumps(R, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
)

# ---------------------------------------------------------------------------
# 6. Cuadros estadísticos (LaTeX con booktabs + Markdown sin corrupción)
# ---------------------------------------------------------------------------
FUENTE = r"\fuente"
tex: list[str] = []
md: list[str] = []


def pct(v, total, d=2):
    return coma(100 * v / total, d)


def tex_a_md(s: str) -> str:
    s = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", s)
    s = re.sub(r"\\textsuperscript\{([^}]*)\}", r"\1", s)
    s = s.replace(r"\%", "%")
    s = s.replace(r"\guillemotleft ", "«").replace(r"\guillemotright", "»")
    s = s.replace(r"\guillemotleft", "«")
    s = s.replace(r"$<$", "<").replace(r"$\ge$", "≥").replace(r"$>$", ">")
    s = s.replace(r"\,", " ").replace("--", "–").replace(r"\textendash", "–")
    s = s.replace(r"\Delta", "Δ").replace(r"\times", "×").replace(r"\neq", "≠")
    s = s.replace(r"\chi^2", "χ²").replace(r"\rho_s", "ρ_s")
    s = s.replace(r"0{,}0001", "0,0001").replace(r"0{,}05", "0,05").replace(r"0{,}975", "0,975")
    s = s.replace(r"\hat\beta_0", "β̂₀").replace(r"\hat\beta_1", "β̂₁")
    s = s.replace(r"\beta_1", "β₁").replace(r"\bar{x}", "x̄").replace(r"\tilde{x}", "x̃")
    s = s.replace(r"s/\sqrt{n}", "s/√n")
    s = s.replace(r"\mu_{\text{sem}}", "μ_sem").replace(r"\mu_{\text{fin}}", "μ_fin")
    s = s.replace(r"\mu_{\Delta t}", "μ_Δt").replace(r"\mu_{Δ t}", "μ_Δt")
    s = s.replace(r"\text{sueño, fin}", "sueño, fin").replace(r"\text{sueño, sem}", "sueño, sem")
    s = s.replace(r"_{\text{unilateral}}", "_unilateral").replace(r"\text{unilateral}", "unilateral")
    s = s.replace(r"_{\text{aj}}", "_aj").replace(r"\text{aj}", "aj")
    s = s.replace(r"$n_i$", "nᵢ").replace(r"$F_i$", "Fᵢ")
    s = s.replace(r"$h_i$", "hᵢ").replace(r"$H_i$", "Hᵢ")
    s = s.replace(r"10^{-6}", "10⁻⁶").replace(r"10^{-5}", "10⁻⁵")
    s = s.replace("$", "")
    return s


def cuadro(
    label: str,
    titulo: str,
    cols: str,
    cabecera: list[str],
    filas: list[list[str]],
    totales: list[str] | None = None,
    nota: str | None = None,
    md_titulo: str = "",
    tam: str = r"\small",
    tabcolsep: str | None = None,
) -> None:
    t = [
        r"\begin{table}[H]",
        r"\centering",
        rf"\caption{{{titulo}}}",
        rf"\label{{{label}}}",
        tam,
    ]
    if tabcolsep:
        t.append(rf"\setlength{{\tabcolsep}}{{{tabcolsep}}}")
    t += [
        rf"\begin{{tabular}}{{{cols}}}",
        r"\toprule",
        " & ".join(rf"\textbf{{{c}}}" if c else "" for c in cabecera) + r" \\",
        r"\midrule",
    ]
    t += [" & ".join(f) + r" \\" for f in filas]
    if totales:
        t += [r"\midrule", " & ".join(totales) + r" \\"]
    t += [r"\bottomrule", r"\end{tabular}"]
    if nota:
        t.append(rf"\par\smallskip\parbox{{0.92\linewidth}}{{\footnotesize\textit{{Nota:}} {nota}}}")
    t += [FUENTE, r"\end{table}", ""]
    tex.extend(t)

    md.append(f"**{md_titulo}**\n")
    cab_md = [tex_a_md(c) for c in cabecera]
    md.append("| " + " | ".join(cab_md) + " |")
    md.append("| :--- | " + " | ".join([":---:"] * (len(cabecera) - 1)) + " |")
    for f in filas + ([totales] if totales else []):
        md.append("| " + " | ".join(tex_a_md(c) for c in f) + " |")
    if nota:
        md.append(f"\n*Nota:* {tex_a_md(nota)}")
    md.append("\n*Fuente: Elaboración propia a partir de datos de la encuesta (n = 28).*\n")


# Cuadro 1: dispositivo × tiempo de uso (Cuadro Proyectado 1)
ct = pd.crosstab(df["Pregunta 4"], df["Tiempo_Cat"], dropna=False).reindex(ORDEN_DISP)
filas = []
for d_, r in ct.iterrows():
    filas.append([ETQ_DISP[d_]] + [str(v) for v in r.values] + [str(r.sum()), pct(r.sum(), n)])
tot = ct.sum()
cuadro(
    "tab:c1",
    "Distribución de estudiantes según dispositivo principal y tiempo de uso nocturno antes de dormir",
    "lccccccc",
    [
        "Dispositivo principal",
        r"$<$30 min",
        "30--59 min",
        "60--119 min",
        "120--179 min",
        r"$\ge$180 min",
        "Total ($n_i$)",
        r"\%",
    ],
    filas,
    [r"\textbf{Total}"]
    + [rf"\textbf{{{v}}}" for v in tot.values]
    + [rf"\textbf{{{n}}}", r"\textbf{100,00}"],
    nota=r"ningún informante seleccionó tableta ni la opción \guillemotleft Otro\guillemotright; ambas filas se omiten.",
    md_titulo="Cuadro 1. Distribución de estudiantes según dispositivo principal y tiempo de uso nocturno antes de dormir",
    tam=r"\scriptsize",
    tabcolsep="4pt",
)

# Cuadro 2: tiempo de uso (frecuencias absolutas, relativas y acumuladas)
fa = df["Tiempo_Cat"].value_counts(sort=False)
Fa = fa.cumsum()
filas = [[e, str(v), pct(v, n), str(F), pct(F, n)] for e, v, F in zip(ETQ_TIEMPO_TEX, fa.values, Fa.values)]
cuadro(
    "tab:c2",
    "Distribución de estudiantes según tiempo de uso de pantallas antes de dormir",
    "lcccc",
    ["Tiempo de uso", "$n_i$", r"$h_i$ (\%)", "$F_i$", r"$H_i$ (\%)"],
    filas,
    [r"\textbf{Total}", rf"\textbf{{{n}}}", r"\textbf{100,00}", "", ""],
    nota=(
        f"por tramos, {fa.iloc[:2].sum()} estudiantes ({pct(fa.iloc[:2].sum(), n)} \\%) usan pantallas menos de 60 min, "
        f"{fa.iloc[2]} ({pct(fa.iloc[2], n)} \\%) entre 60 y 119 min y {fa.iloc[3:].sum()} "
        f"({pct(fa.iloc[3:].sum(), n)} \\%) 120 min o más; {fa.iloc[2:].sum()} estudiantes "
        f"({pct(fa.iloc[2:].sum(), n)} \\%) superan los 60 min."
    ),
    md_titulo="Cuadro 2. Distribución de estudiantes según tiempo de uso de pantallas antes de dormir",
)

# Cuadro 3: duración del sueño en días lectivos × sexo (Cuadro Proyectado 4)
cat_sueno = pd.cut(
    df["Sueno_Semana"],
    bins=[-np.inf, 5 - 1e-9, 7 - 1e-9, 9 + 1e-9, np.inf],
    labels=[
        "Menos de 5 h (muy corta)",
        "De 5 a 6,9 h (corta)",
        "De 7 a 9 h (óptima)",
        "Más de 9 h (prolongada)",
    ],
)
ct3 = pd.crosstab(cat_sueno, df["Pregunta 1"], dropna=False)[["Femenino", "Masculino"]]
filas = [
    [str(k), str(r["Femenino"]), str(r["Masculino"]), str(r.sum()), pct(r.sum(), n)]
    for k, r in ct3.iterrows()
]
cuadro(
    "tab:c3",
    "Distribución de estudiantes según duración calculada del sueño en días lectivos y sexo",
    "lcccc",
    ["Duración del sueño (lun.--vie.)", "Femenino", "Masculino", "Total ($n_i$)", r"\%"],
    filas,
    [
        r"\textbf{Total}",
        rf"\textbf{{{ct3['Femenino'].sum()}}}",
        rf"\textbf{{{ct3['Masculino'].sum()}}}",
        rf"\textbf{{{n}}}",
        r"\textbf{100,00}",
    ],
    nota=(
        f"{int((df['Sueno_Semana'] < 7).sum())} estudiantes "
        f"({pct((df['Sueno_Semana'] < 7).sum(), n)} \\%) duermen menos de 7 h en días lectivos."
    ),
    md_titulo="Cuadro 3. Distribución de estudiantes según duración calculada del sueño en días lectivos y sexo",
)

# Cuadro 4: descriptivos de las horas de sueño (Cuadro Proyectado 2)
filas = []
for etq, col in [
    ("Días lectivos (lun.--vie.)", "Sueno_Semana"),
    ("Fines de semana (sáb.--dom.)", "Sueno_Finde"),
    ("Promedio ponderado (5:2)", "Sueno_Ponderado"),
    (r"Compensación ($\Delta t$)", "Compensacion_Finde"),
]:
    x = df[col]
    q1, q3 = x.quantile([0.25, 0.75])
    filas.append(
        [
            etq,
            coma(x.mean()),
            coma(x.median()),
            coma(x.std(ddof=1)),
            coma(q3 - q1),
            coma(x.min()),
            coma(x.max()),
            coma(100 * x.std(ddof=1) / x.mean(), 1),
        ]
    )
cuadro(
    "tab:c4",
    "Estadísticos descriptivos de las horas calculadas de sueño según régimen semanal",
    "lccccccc",
    ["Régimen", r"$\bar{x}$", r"$\tilde{x}$", "$s$", "RIC", "Mín.", "Máx.", r"CV (\%)"],
    filas,
    nota=(
        r"horas decimales; $\Delta t = t_{\text{sueño, fin}} - t_{\text{sueño, sem}}$. "
        "Un registro inconsistente de días lectivos se imputó con la cota mínima válida (4,00 h)."
    ),
    md_titulo="Cuadro 4. Estadísticos descriptivos de las horas calculadas de sueño según régimen semanal",
    tam=r"\footnotesize",
)

# Cuadro 5: tramo de pantalla × sensación al despertar (Cuadro Proyectado 3)
ct5 = pd.crosstab(df["Tramo_Pantalla"], df["Sensacion"], dropna=False)[ORDEN_SENSACION]
medias = df.groupby("Tramo_Pantalla", observed=False)["Calidad_Sueño"].mean()
TRAMO_TEX = {
    "< 60 min": r"$<$ 60 min",
    "60 a 119 min": "60 a 119 min",
    "120 min o más": "120 min o más",
}
filas = [
    [TRAMO_TEX[k]] + [str(v) for v in r.values] + [str(r.sum()), coma(medias[k])]
    for k, r in ct5.iterrows()
]
cuadro(
    "tab:c5",
    "Sensación habitual al despertar según tramo de tiempo de pantalla nocturno",
    "lcccccc",
    [
        "Tiempo de pantalla",
        "Energía",
        "Cansancio leve",
        "Somnolencia",
        "Agotamiento",
        "Total",
        "Puntaje medio",
    ],
    filas,
    [r"\textbf{Total}"]
    + [rf"\textbf{{{v}}}" for v in ct5.sum().values]
    + [rf"\textbf{{{n}}}", rf"\textbf{{{coma(df['Calidad_Sueño'].mean())}}}"],
    nota=(
        r"puntaje medio con la codificación del procesamiento (1 = somnolencia persistente, "
        r"2 = cansancio leve, 3 = energía suficiente); valores altos indican mejor estado matutino. "
        r"Ningún informante eligió \guillemotleft agotamiento severo\guillemotright. Independencia sobre la matriz $3\times 3$: "
        rf"$\chi^2 = {coma(R['chi2_tramo_calidad']['chi2'], 4)}$, $gl = {R['chi2_tramo_calidad']['gl']}$, "
        rf"$p = {coma(R['chi2_tramo_calidad']['p'], 4)}$, con "
        rf"{coma(100 * R['chi2_tramo_calidad']['prop_esperadas_menor5'], 1)} \% de frecuencias esperadas menores que 5."
    ),
    md_titulo="Cuadro 5. Sensación habitual al despertar según tramo de tiempo de pantalla nocturno",
    tam=r"\footnotesize",
)

# Cuadro 6: ciclo académico × despertares (Cuadro Proyectado 5)
ct6 = pd.crosstab(df["Ciclo"], df["Despertares"], dropna=False)
filas = [
    [ciclo_tex] + [str(v) for v in r.values] + [str(r.sum()), pct(r.sum(), n)]
    for ciclo_tex, (_, r) in zip(CICLOS_TEX, ct6.iterrows())
]
cuadro(
    "tab:c6",
    "Distribución de despertares nocturnos involuntarios según ciclo académico",
    "lcccccc",
    ["Ciclo académico", "Ninguna", "1 vez", "2 veces", r"$\ge$3 veces", "Total", r"\%"],
    filas,
    [r"\textbf{Total}"]
    + [rf"\textbf{{{v}}}" for v in ct6.sum().values]
    + [rf"\textbf{{{n}}}", r"\textbf{100,00}"],
    nota="semestre determinado por la materia del semestre más bajo, inscrita o no (Pregunta 3).",
    md_titulo="Cuadro 6. Distribución de despertares nocturnos involuntarios según ciclo académico",
    tam=r"\footnotesize",
)

# Cuadro 7: regresión lineal simple OLS
o = R["ols"]
filas = [
    [
        "Intercepto ($\\hat\\beta_0$)",
        coma(o["b0"], 4),
        coma(o["se0"], 4),
        coma(o["t0"], 4),
        "$<0{,}0001$",
        f"[{coma(o['ci0'][0], 4)};\\,{coma(o['ci0'][1], 4)}]",
    ],
    [
        "Minutos de pantalla ($\\hat\\beta_1$)",
        coma(o["b1"], 4),
        coma(o["se1"], 4),
        coma(o["t1"], 4),
        coma(o["p1"], 4),
        f"[{coma(o['ci1'][0], 4)};\\,{coma(o['ci1'][1], 4)}]",
    ],
]
cuadro(
    "tab:c7",
    "Regresión lineal simple (MCO) de las horas de sueño en días lectivos sobre los minutos de pantalla",
    "lccccc",
    ["Parámetro", "Coeficiente", "Error est.", "$t$", "$p$", r"IC 95\,\%"],
    filas,
    nota=(
        rf"$n = {n}$; $R^2 = {coma(o['r2'], 4)}$; $R^2_{{\text{{aj}}}} = {coma(o['r2a'], 4)}$; "
        rf"$F({o['gl1']},\,{o['gl2']}) = {coma(o['F'], 4)}$, $p = {coma(o['pF'], 4)}$; "
        rf"Durbin--Watson $= {coma(o['dw'], 3)}$; Jarque--Bera $= {coma(o['jb'], 3)}$ "
        rf"($p = {coma(o['pjb'], 3)}$); Shapiro--Wilk de residuos: $W = {coma(o['sw_resid']['W'], 4)}$, "
        rf"$p = {coma(o['sw_resid']['p'], 4)}$. Minutos imputados por marca de clase."
    ),
    md_titulo="Cuadro 7. Regresión lineal simple (MCO) de las horas de sueño en días lectivos sobre los minutos de pantalla",
    tam=r"\footnotesize",
)

# Cuadro 8: correlaciones
c = R["correlaciones"]
filas = [
    [
        "Pearson ($r$)",
        "Horas de sueño (lun.--vie.)",
        coma(c["pearson_sueno"]["r"], 4),
        coma(c["pearson_sueno"]["p"], 4),
    ],
    [
        "Spearman ($r_s$)",
        "Calidad percibida (1--3)",
        "+" + coma(c["spearman_calidad"]["r"], 4),
        coma(c["spearman_calidad"]["p"], 4),
    ],
    [
        "Spearman ($r_s$)",
        "Despertares nocturnos (0--3)",
        coma(c["spearman_despertares"]["r"], 4),
        coma(c["spearman_despertares"]["p"], 4),
    ],
]
cuadro(
    "tab:c8",
    "Coeficientes de correlación entre los minutos de pantalla y los indicadores de sueño",
    "llcc",
    ["Coeficiente", "Variable asociada", "Valor", "$p$ (bilateral)"],
    filas,
    nota=(
        rf"$n = {n}$, $gl = n - 2 = {c['gl']}$. La calidad percibida usa la escala del procesamiento "
        "(1 = somnolencia persistente, 3 = energía suficiente): un coeficiente positivo indica mejor "
        "estado matutino al aumentar los minutos de pantalla."
    ),
    md_titulo="Cuadro 8. Coeficientes de correlación entre los minutos de pantalla y los indicadores de sueño",
)

# Cuadro 9: intervalos de confianza
filas = []
for etq, k in [
    (r"Sueño en días lectivos ($\mu_{\text{sem}}$)", "ic_semana"),
    (r"Sueño en fines de semana ($\mu_{\text{fin}}$)", "ic_finde"),
    (r"Compensación ($\mu_{\Delta t}$)", "ic_delta"),
]:
    v = R[k]
    filas.append(
        [
            etq,
            coma(v["media"], 4),
            coma(v["s"], 4),
            coma(v["se"], 4),
            f"[{coma(v['li'], 2)};\\,{coma(v['ls'], 2)}]",
        ]
    )
cuadro(
    "tab:c9",
    r"Intervalos de confianza del 95\,\% para las medias de sueño",
    "lcccc",
    ["Parámetro", r"$\bar{x}$", "$s$", r"$s/\sqrt{n}$", r"IC 95\,\%"],
    filas,
    nota=rf"$n = {n}$; $t_{{0{{,}}975;\,{gl}}} = {coma(tcrit, 5)}$. Horas decimales.",
    md_titulo="Cuadro 9. Intervalos de confianza del 95 % para las medias de sueño",
    tam=r"\footnotesize",
)

# Cuadro 10: contrastes de hipótesis
p1, p2 = R["prueba1"], R["prueba2"]
filas = [
    [
        "1. Umbral de 7 h",
        r"$H_1: \mu_{\text{sem}} < 7$",
        rf"$t = {coma(p1['t'], 4)}$",
        str(gl),
        coma(p1["p"], 4),
        "No se rechaza",
    ],
    [
        "2. Jetlag social",
        r"$H_1: \mu_{\Delta t} > 0$",
        rf"$t = {coma(p2['t'], 4)}$",
        str(gl),
        rf"${coma(p2['p_unilateral'] * 1e6, 2)}\times 10^{{-6}}$",
        "Se rechaza",
    ],
    [
        "3. Modelo MCO",
        r"$H_1: \beta_1 \neq 0$",
        rf"$F = {coma(o['F'], 3)}$",
        f"(1, {o['gl2']})",
        coma(o["pF"], 4),
        "No se rechaza",
    ],
    [
        "4. Spearman",
        r"$H_1: \rho_s \neq 0$",
        rf"$r_s = +{coma(c['spearman_calidad']['r'], 4)}$",
        str(n - 2),
        coma(c["spearman_calidad"]["p"], 4),
        "Se rechaza",
    ],
]
cuadro(
    "tab:c10",
    r"Resumen de los contrastes de hipótesis ($\alpha = 0{,}05$)",
    "llcccl",
    ["Prueba", "Alternativa", "Estadístico", "$gl$", "$p$", r"Decisión sobre $H_0$"],
    filas,
    nota=(
        rf"prueba 2 complementada con Wilcoxon de rangos con signo: $W = {coma(p2['W'], 1)}$, "
        rf"$p_{{\text{{unilateral}}}} = {coma(p2['p_wilcoxon_unilateral'] * 1e5, 2)}\times 10^{{-5}}$."
    ),
    md_titulo="Cuadro 10. Resumen de los contrastes de hipótesis (α = 0,05)",
    tam=r"\footnotesize",
)

(RAIZ / "cuadros_resultados.tex").write_text(
    "% Generado automáticamente por generar_graficos.py: no editar a mano.\n" + "\n".join(tex),
    encoding="utf-8",
)
(RAIZ / "cuadros_resultados.md").write_text("\n".join(md), encoding="utf-8")

# ---------------------------------------------------------------------------
# 7. Reporte en consola de frecuencias absolutas y relativas
# ---------------------------------------------------------------------------
for nombre, s in [
    ("Sexo", sexo),
    ("Edad (clases)", edad_cls.value_counts(sort=False)),
    ("Semestre", sem_cnt),
    ("Dispositivo", disp),
    ("Tiempo de uso", tiempo),
    ("Actividad", act),
    ("Despertares", desp),
    ("Sensación", sens),
]:
    t = pd.DataFrame({"n_i": s, "h_i (%)": (100 * s / n).round(2)})
    print(f"\n== {nombre} (n = {int(s.sum())})\n{t.to_string()}")

print(
    "\nEdad: media = %.2f, mediana = %.1f, s = %.2f, rango = [%d, %d]"
    % (df["Edad"].mean(), df["Edad"].median(), df["Edad"].std(), df["Edad"].min(), df["Edad"].max())
)
print(
    json.dumps(
        {
            k: R[k]
            for k in [
                "prueba1",
                "prueba2",
                "correlaciones",
                "chi2_tramo_calidad",
                "chi2_5x3_calidad",
                "shapiro",
                "medias_calidad_tramo",
            ]
        },
        indent=2,
        ensure_ascii=False,
        default=float,
    )
)
