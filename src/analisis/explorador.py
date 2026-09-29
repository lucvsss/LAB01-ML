"""Data Understanding sobre el corpus estructurado.

Salidas:
    reportes/figuras/*.png          gráficos
    reportes/tablas/*.csv           datos detrás de cada gráfico
    reportes/data_understanding.md  tablas, cifras y hallazgos para el informe
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin ventana pq funciona en cualquier computador
import matplotlib.pyplot as plt  
import pandas as pd  
from matplotlib.ticker import MaxNLocator 

from src.config import DIR_JSON, DIR_PROCESSED, RAIZ, RUTA_URLS  
from src.conocimiento.normalizador import NormalizadorEntidades, cargar_noticias
from src.conocimiento.relaciones import AnalizadorRelaciones 
from src.conocimiento.vocabulario import ( 
    COMUNAS_REGION,
    ROLES_INSTITUCIONALES,
    clave,
    es_institucion,
)

DIR_REPORTES = RAIZ / "reportes"

AZUL = "#2a78d6"
GRIS = "#b9b8b3"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
FONDO = "#fcfcfb"
CAMPOS = ["titulo", "fecha_publicacion", "fuente", "url", "resumen",
          "delitos", "personas", "organizaciones", "lugares", "objetos", "relaciones"]


def _estilo() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": FONDO, "axes.facecolor": FONDO, "axes.edgecolor": GRIS,
            "axes.labelcolor": TINTA_2, "axes.titlecolor": TINTA, "axes.titlesize": 12,
            "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
            "xtick.color": TINTA_2, "ytick.color": TINTA_2, "font.size": 9,
            "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "axes.axisbelow": True,
        }
    )


class ExploradorDatos:
    """Estadísticas y gráficos mínimos del laboratorio."""

    def __init__(
        self,
        dir_json: Path = DIR_JSON,
        dir_processed: Path = DIR_PROCESSED,
        ruta_urls: Path = RUTA_URLS,
        dir_reportes: Path = DIR_REPORTES,
        normalizador: NormalizadorEntidades | None = None,
    ) -> None:
        self.dir_json = dir_json
        self.dir_processed = dir_processed
        self.ruta_urls = ruta_urls
        self.dir_reportes = dir_reportes
        self.dir_figuras = dir_reportes / "figuras"
        self.dir_tablas = dir_reportes / "tablas"
        self.normalizador = normalizador or NormalizadorEntidades()
        self.secciones: list[str] = []
        self._cargado = False

    # DATOS
    def cargar(self) -> None:
        self.urls = pd.read_csv(self.ruta_urls) if self.ruta_urls.exists() else pd.DataFrame()
        if "fuente" in self.urls:
            self.urls["fuente"] = self.urls["fuente"].map(self.normalizador._fuente)
        self.crudos, self.problemas = cargar_noticias(self.dir_json)  # tal como los dejó Gemini
        self.noticias = self.normalizador.normalizar_corpus(self.crudos)  # como en el vault
        self.capturadas = sorted(p.stem for p in self.dir_processed.glob("*.txt"))
        self.dir_figuras.mkdir(parents=True, exist_ok=True)
        self.dir_tablas.mkdir(parents=True, exist_ok=True)
        _estilo()
        self._cargado = True

    def _asegurar(self) -> None:
        if not self._cargado:
            self.cargar()

    # UTILIDADES
    def _guardar(self, fig, archivo: str) -> Path:
        fig.tight_layout()
        ruta = self.dir_figuras / archivo
        fig.savefig(ruta, dpi=150)
        plt.close(fig)
        return ruta

    def _barras(self, serie: pd.Series, titulo: str, archivo: str, xlabel: str = "Noticias",
                resaltar_cero: bool = False) -> Path:
        """Barras horizontales ordenadas, con el valor escrito al final de cada barra."""
        serie = serie.sort_values()
        fig, ax = plt.subplots(figsize=(7.5, max(2.5, 0.32 * len(serie) + 1.2)))
        colores = [GRIS if (resaltar_cero and v == 0) else AZUL for v in serie.values]
        ax.barh(serie.index.astype(str), serie.values, color=colores, height=0.6)
        for i, v in enumerate(serie.values):
            ax.text(v + max(serie.max(), 1) * 0.01, i, f"{v:g}", va="center", color=TINTA_2, fontsize=8)
        ax.set_title(titulo, loc="left")
        ax.set_xlabel(xlabel)
        ax.grid(axis="y", visible=False)
        if all(float(v).is_integer() for v in serie.values):
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.margins(x=0.08)
        serie.sort_values(ascending=False).rename("valor").to_csv(self.dir_tablas / archivo.replace(".png", ".csv"))
        return self._guardar(fig, archivo)

    @staticmethod
    def _tabla_md(serie: pd.Series, col1: str, col2: str = "Noticias", n: int = 15) -> str:
        filas = [f"| {col1} | {col2} |", "|---|---|"]
        filas += [f"| {str(k).replace('|', '/')} | {v:g} |" for k, v in serie.sort_values(ascending=False).head(n).items()]
        return "\n".join(filas)

    @staticmethod
    def _df_md(df: pd.DataFrame, indice: str = "") -> str:
        filas = [f"| {indice} | " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * (len(df.columns) + 1)]
        for idx, fila in df.iterrows():
            filas.append(f"| {str(idx).replace('|', '/')} | " + " | ".join(f"{v:g}" if isinstance(v, (int, float)) else str(v) for v in fila) + " |")
        return "\n".join(filas)

    def _seccion(self, titulo: str, figura: Path | None, texto: str) -> None:
        bloque = f"## {titulo}\n\n" + (f"![{titulo}](figuras/{figura.name})\n\n" if figura else "")
        self.secciones.append(bloque + texto.strip() + "\n")

    # EMBUDO
    def embudo_pipeline(self) -> dict:
        """¿Cuántas noticias fueron procesadas y cuántas fallaron? (diapositiva 32)"""
        self._asegurar()
        analizador = AnalizadorRelaciones()
        grupos = analizador.grupos_mismo_hecho(analizador.calcular(self.noticias))
        etapas = {
            "URLs en urls.csv": len(self.urls),
            "Capturadas (texto)": len(self.capturadas),
            "JSON utilizables": len(self.noticias),
            "Hechos distintos": len(self.noticias) - sum(len(g) - 1 for g in grupos),
        }
        serie = pd.Series(etapas)
        fig, ax = plt.subplots(figsize=(7.5, 3.2))
        ax.bar(serie.index, serie.values, color=AZUL, width=0.55)
        for i, v in enumerate(serie.values):
            ax.text(i, v + max(serie.max(), 1) * 0.02, str(v), ha="center", va="bottom", color=TINTA_2)
        ax.set_ylim(0, max(serie.max(), 1) * 1.15)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title("Embudo del pipeline: cuántas noticias sobreviven cada etapa", loc="left")
        ax.grid(axis="x", visible=False)
        ruta = self._guardar(fig, "00_embudo_pipeline.png")
        serie.rename("noticias").to_csv(self.dir_tablas / "00_embudo_pipeline.csv")

        sin_captura = sorted(set(self.urls.get("id_noticia", [])) - set(self.capturadas))
        sin_json = sorted(set(self.capturadas) - {d["id_noticia"] for d in self.noticias})
        texto = [self._df_md(serie.rename("Noticias").to_frame(), "Etapa"), ""]
        texto.append(f"- Fallaron en la captura: **{len(sin_captura)}** ({', '.join(sin_captura) or 'ninguna'}).")
        texto.append(f"- Capturadas sin JSON utilizable: **{len(sin_json)}** ({', '.join(sin_json) or 'ninguna'}).")
        texto += [f"- JSON omitido: {p}" for p in self.problemas]
        texto.append(f"- Grupos de noticias sobre un mismo hecho: **{len(grupos)}** "
                     f"({'; '.join(', '.join(g) for g in grupos) or 'ninguno'}).")
        fuentes_urls = self.urls["fuente"].value_counts() if "fuente" in self.urls else pd.Series(dtype=int)
        if not fuentes_urls.empty:
            texto.append("- Medios en urls.csv: " + ", ".join(f"{k} ({v})" for k, v in fuentes_urls.items()) + ".")
        self._seccion("0. Embudo del pipeline", ruta, "\n".join(texto))
        return etapas

    # FUENTES
    def noticias_por_fuente(self) -> pd.Series:
        """¿Qué fuentes fueron usadas? (diapositivas 32 y 34)"""
        self._asegurar()
        serie = pd.Series(Counter(d.get("fuente") or "desconocida" for d in self.noticias), dtype=int)
        if serie.empty:
            return serie
        ruta = self._barras(serie, "Noticias por medio", "01_noticias_por_fuente.png")
        texto = self._tabla_md(serie, "Medio") + (
            f"\n\n- {len(serie)} medios. El medio con más noticias ({serie.idxmax()}) aporta "
            f"{serie.max() / serie.sum():.0%} del corpus.")
        self._seccion("1. Noticias por medio", ruta, texto)
        return serie

    # DELITOS
    def delitos_frecuentes(self) -> pd.Series:
        """¿Qué delitos aparecen con mayor frecuencia? (diapositiva 32)"""
        self._asegurar()
        serie = pd.Series(Counter(x for d in self.noticias for x in d["delitos"]), dtype=int)
        if serie.empty:
            return serie
        ruta = self._barras(serie, "Noticias por tipo de delito", "02_delitos_frecuentes.png")
        multi = sum(1 for d in self.noticias if len(d["delitos"]) > 1)
        texto = self._tabla_md(serie, "Delito") + (
            f"\n\n- {multi} de {len(self.noticias)} noticias ({multi / len(self.noticias):.0%}) "
            "registran más de un delito (por ejemplo, tráfico + porte de armas).")
        self._seccion("2. Delitos más frecuentes", ruta, texto)
        return serie

    # LUGARES
    def lugares_frecuentes(self) -> pd.Series:
        """¿Qué lugares concentran más menciones? + delitos por comuna (diapositivas 32 y 34)"""
        self._asegurar()
        conteo = Counter(c for d in self.noticias for c in d["comunas"])
        serie = pd.Series({c: conteo.get(c, 0) for c in COMUNAS_REGION}, dtype=int)
        ruta = self._barras(serie, "Noticias por comuna (gris = sin noticias)", "03_noticias_por_comuna.png",
                            resaltar_cero=True)
        sin = [c for c, v in serie.items() if v == 0]
        texto = self._tabla_md(serie[serie > 0], "Comuna") + f"\n\n- Comunas sin noticias: {', '.join(sin) or 'ninguna'}."
        if serie.sum():
            dos = serie.sort_values(ascending=False).head(2)
            texto += (f"\n- Las dos comunas con más menciones ({', '.join(dos.index)}) concentran "
                      f"{dos.sum() / serie.sum():.0%} de las menciones de comuna.")
        sectores = pd.Series(Counter(s for d in self.noticias for s in d["sectores"]), dtype=int)
        if not sectores.empty:
            texto += "\n\n**Sectores y poblaciones más mencionados**\n\n" + self._tabla_md(sectores, "Sector", n=10)
        self._seccion("3. Comunas y sectores", ruta, texto)

        filas = [(c, x) for d in self.noticias for c in d["comunas"] for x in d["delitos"]]
        if filas:
            tabla = pd.crosstab(pd.Series([f[0] for f in filas], name="comuna"),
                                pd.Series([f[1] for f in filas], name="delito"))
            fig, ax = plt.subplots(figsize=(8, max(3, 0.4 * len(tabla) + 1.5)))
            im = ax.imshow(tabla.values, cmap="Blues", aspect="auto")  # un solo tono = magnitud
            ax.set_xticks(range(len(tabla.columns)), tabla.columns, rotation=35, ha="right")
            ax.set_yticks(range(len(tabla.index)), tabla.index)
            ax.grid(False)
            for i in range(tabla.shape[0]):
                for j in range(tabla.shape[1]):
                    v = tabla.values[i, j]
                    if v:
                        ax.text(j, i, str(v), ha="center", va="center", fontsize=8,
                                color="white" if v > tabla.values.max() * 0.55 else TINTA)
            ax.set_title("Delitos por comuna (número de noticias)", loc="left")
            fig.colorbar(im, ax=ax, shrink=0.7)
            ruta2 = self._guardar(fig, "04_delitos_por_comuna.png")
            tabla.to_csv(self.dir_tablas / "04_delitos_por_comuna.csv")
            self._seccion("4. Delitos por comuna", ruta2, "Cada celda cuenta noticias que mencionan esa comuna y ese delito.")
        return serie

    # ENT. POR NOTICIA
    def entidades_por_noticia(self) -> pd.DataFrame:
        """Cantidad de personas u organizaciones por noticia (diapositiva 34)."""
        self._asegurar()
        df = pd.DataFrame([
            {
                "id_noticia": d["id_noticia"],
                "personas": sum(p.get("rol") not in ROLES_INSTITUCIONALES for p in d["personas"]),
                "funcionarios": sum(p.get("rol") in ROLES_INSTITUCIONALES for p in d["personas"]),
                "organizaciones": len(d["organizaciones"]),
                "bandas": sum(not es_institucion(o) for o in d["organizaciones"]),
                "relaciones": len(d["relaciones"]),
            }
            for d in self.noticias
        ])
        if df.empty:
            return df
        df.to_csv(self.dir_tablas / "05_entidades_por_noticia.csv", index=False)
        cols = ["personas", "funcionarios", "organizaciones", "bandas", "relaciones"]
        fig, axes = plt.subplots(1, len(cols), figsize=(10, 2.8), sharey=True)
        for ax, col in zip(axes, cols):
            conteo = df[col].value_counts().sort_index()
            ax.bar(conteo.index.astype(str), conteo.values, color=AZUL, width=0.6)
            ax.set_title(col, loc="left", fontsize=10)
            ax.set_xlabel("por noticia")
            ax.grid(axis="x", visible=False)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes[0].set_ylabel("Noticias")
        fig.suptitle("Cantidad de entidades por noticia", x=0.01, ha="left", fontweight="bold", color=TINTA)
        ruta = self._guardar(fig, "05_entidades_por_noticia.png")
        resumen = df[cols].describe().loc[["mean", "50%", "max"]].round(2)
        sin_personas = int((df["personas"] == 0).sum())
        texto = self._df_md(resumen.rename(index={"mean": "promedio", "50%": "mediana", "max": "máximo"})) + (
            f"\n\n- {sin_personas} de {len(df)} noticias ({sin_personas / len(df):.0%}) no nombran a ninguna "
            "persona que no sea funcionario: la prensa regional suele omitir nombres o usar iniciales.")
        self._seccion("5. Personas y organizaciones por noticia", ruta, texto)
        return df

    # CAMPOS FALTANRTES
    def campos_faltantes(self) -> pd.Series:
        """Porcentaje de campos nulos o vacíos en el JSON de Gemini."""
        self._asegurar()
        if not self.crudos:
            return pd.Series(dtype=float)

        def vacio(v) -> bool:
            return v is None or (isinstance(v, (str, list)) and len(v) == 0)

        pct = pd.Series({c: 100 * sum(vacio(d.get(c)) for d in self.crudos) / len(self.crudos) for c in CAMPOS})
        ruta = self._barras(pct.round(1), "Campos nulos o vacíos en el JSON de Gemini (%)",
                            "06_campos_faltantes.png", xlabel="% de noticias")
        texto = self._tabla_md(pct.round(1), "Campo", "% nulo o vacío") + (
            "\n\nUna lista vacía no siempre es un error (una noticia puede no tener objetos incautados); "
            "un título o una fecha nulos sí lo son.")
        self._seccion("6. Campos faltantes", ruta, texto)
        return pct

    # EVOLUCION TEMPORAL
    def evolucion_temporal(self) -> pd.Series:
        """Evolución temporal simple si la fecha está disponible (diapositiva 34)."""
        self._asegurar()
        fechas = pd.to_datetime(pd.Series([d.get("fecha_publicacion") for d in self.noticias]),
                                errors="coerce").dropna()
        if fechas.empty:
            self._seccion("7. Evolución temporal", None, "Ninguna noticia tiene fecha_publicacion válida.")
            return pd.Series(dtype=int)
        por_mes = pd.Series(1, index=pd.DatetimeIndex(fechas)).resample("MS").sum()
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot(por_mes.index, por_mes.values, color=AZUL, linewidth=2, marker="o", markersize=4)
        ax.set_title("Noticias por mes de publicación", loc="left")
        ax.set_ylabel("Noticias")
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        fig.autofmt_xdate()
        ruta = self._guardar(fig, "07_evolucion_temporal.png")
        por_mes.index = por_mes.index.strftime("%Y-%m")
        por_mes.rename("noticias").to_csv(self.dir_tablas / "07_evolucion_temporal.csv")
        sin_fecha = len(self.noticias) - len(fechas)
        texto = (f"- Rango: {fechas.min():%Y-%m-%d} a {fechas.max():%Y-%m-%d}.\n"
                 f"- Mes con más noticias: {por_mes.idxmax()} ({por_mes.max()}).\n"
                 f"- Noticias sin fecha válida: {sin_fecha}.\n\n"
                 "La serie mide **cobertura de prensa en el corpus**, no incidencia delictual: "
                 "el corpus se armó con búsquedas, y los buscadores privilegian noticias recientes.")
        self._seccion("7. Evolución temporal", ruta, texto)
        return por_mes

    # OBJS
    def objetos_incautados(self) -> pd.Series:
        self._asegurar()
        serie = pd.Series(Counter(o["nombre"] for d in self.noticias for o in d["objetos"]), dtype=int)
        if serie.empty:
            return serie
        ruta = self._barras(serie.sort_values(ascending=False).head(15),
                            "Objetos incautados (noticias que los mencionan)", "08_objetos_incautados.png")
        sin_cantidad = sum(o.get("cantidad") is None for d in self.noticias for o in d["objetos"])
        total = sum(len(d["objetos"]) for d in self.noticias)
        texto = self._tabla_md(serie, "Objeto") + f"\n\n- {sin_cantidad} de {total} objetos no tienen cantidad informada."
        self._seccion("8. Objetos incautados", ruta, texto)
        return serie

    # CALIDAD
    def calidad_extraccion(self) -> list[tuple[str, str, str, float]]:
        """Entidades con nombres inconsistentes y relaciones dudosas (diapositiva 32)."""
        self._asegurar()
        texto = []
        dudosas = []
        for d in self.noticias:
            entidades = {clave(x) for x in d["delitos"] + d["organizaciones"] + d["lugares"]}
            entidades |= {clave(p["nombre"]) for p in d["personas"]} | {clave(o["nombre"]) for o in d["objetos"]}
            for r in d["relaciones"]:
                for extremo in ("origen", "destino"):
                    if clave(r[extremo]) not in entidades:
                        dudosas.append((d["id_noticia"], f"{r['origen']} {r['tipo']} {r['destino']}", r[extremo]))
        total_rel = sum(len(d["relaciones"]) for d in self.noticias)
        texto.append(f"- Relaciones cuyo origen o destino no es una entidad de la misma noticia: "
                     f"**{len(dudosas)}** de {total_rel}.")
        texto += [f"  - {nid}: {rel} (extremo: «{ext}»)" for nid, rel, ext in dudosas[:15]]

        roles = Counter(p.get("rol") or "sin rol" for d in self.noticias for p in d["personas"])
        texto.append("- Roles registrados: " + (", ".join(f"{k} ({v})" for k, v in roles.most_common()) or "ninguno") + ".")

        pares = self.nombres_inconsistentes()
        texto.append(f"\n**Posibles nombres inconsistentes: {len(pares)}** "
                     "(si son la misma entidad, agréguelos a `data/equivalencias.csv` y vuelva a ejecutar obsidian y analizar):\n")
        texto += [f"- {t}: «{a}» ~ «{b}» (similitud {s:.2f})" for t, a, b, s in pares[:25]] or ["- Ninguno."]
        pd.DataFrame(pares, columns=["tipo", "nombre_a", "nombre_b", "similitud"]).to_csv(
            self.dir_tablas / "09_nombres_inconsistentes.csv", index=False)
        self._seccion("9. Calidad de la extracción", None, "\n".join(texto))
        return pares

    def nombres_inconsistentes(self, umbral: float = 0.82) -> list[tuple[str, str, str, float]]:
        """Pares de nombres distintos pero muy parecidos dentro del mismo tipo de entidad."""
        self._asegurar()
        grupos = {
            "organización": {o for d in self.noticias for o in d["organizaciones"]},
            "lugar": {x for d in self.noticias for x in d["lugares"]},
            "persona": {p["nombre"] for d in self.noticias for p in d["personas"] if "(" not in p["nombre"]},
            "objeto": {o["nombre"] for d in self.noticias for o in d["objetos"]},
        }
        pares = []
        for tipo, nombres in grupos.items():
            lista = sorted(nombres)
            for i, a in enumerate(lista):
                for b in lista[i + 1:]:
                    ka, kb = clave(a), clave(b)
                    s = SequenceMatcher(None, ka, kb).ratio()
                    if s >= umbral or (min(len(ka), len(kb)) > 3 and (ka in kb or kb in ka)):
                        pares.append((tipo, a, b, round(s, 2)))
        return sorted(pares, key=lambda x: -x[3])

    # RELACIONES
    def evaluar_relaciones(self) -> dict:
        """Relaciones entre noticias según la sección 9 de la ficha."""
        self._asegurar()
        relaciones = AnalizadorRelaciones().calcular(self.noticias)
        fuertes = [r for r in relaciones if r.nivel == "fuerte"]
        medias = [r for r in relaciones if r.nivel == "media"]
        motivos = Counter(m.split(":")[0].split(" (")[0] for r in relaciones for m in r.motivos)
        conectadas = {r.origen for r in relaciones} | {r.destino for r in relaciones}
        hubs = Counter(o for d in self.noticias for o in d["organizaciones"] if es_institucion(o))
        texto = [
            f"- Relaciones fuertes: **{len(fuertes)}**; medias: **{len(medias)}**.",
            "- Motivos: " + (", ".join(f"{k} ({v})" for k, v in motivos.most_common()) or "ninguno") + ".",
            f"- Noticias sin ninguna relación fuerte o media: **{len(self.noticias) - len(conectadas)}** de {len(self.noticias)}.",
        ]
        if hubs:
            texto.append("- Instituciones (nodos hub que NO crean relación): "
                         + ", ".join(f"{k} ({v})" for k, v in hubs.most_common(6)) + ".")
        texto += ["", "Detalle:"] + [f"- {r.origen} ↔ {r.destino} ({r.nivel}): {'; '.join(r.motivos)}" for r in relaciones[:30]]
        pd.DataFrame([{"origen": r.origen, "destino": r.destino, "nivel": r.nivel, "motivos": "; ".join(r.motivos)}
                      for r in relaciones]).to_csv(self.dir_tablas / "10_relaciones_entre_noticias.csv", index=False)
        self._seccion("10. Relaciones entre noticias", None, "\n".join(texto))
        return {"fuertes": len(fuertes), "medias": len(medias)}

    # EJECUTAR
    def ejecutar(self) -> Path | None:
        """Corre todas las visualizaciones pedidas en la guía y escribe el reporte."""
        self.cargar()
        self.secciones = []
        if not self.noticias:
            print(f"No hay JSON en {self.dir_json}. Ejecute primero: python main.py extraer")
            return None
        self.embudo_pipeline()
        self.noticias_por_fuente()
        self.delitos_frecuentes()
        self.lugares_frecuentes()
        self.entidades_por_noticia()
        self.campos_faltantes()
        self.evolucion_temporal()
        self.objetos_incautados()
        self.calidad_extraccion()
        self.evaluar_relaciones()
        reporte = self.dir_reportes / "data_understanding.md"
        reporte.write_text(
            "# Data Understanding — narcotráfico en la Región de Coquimbo\n\n"
            "Generado por `python main.py analizar`. Cifras sobre los JSON normalizados (los mismos del vault), "
            "salvo la sección 6, que mide el JSON tal como lo entregó Gemini.\n\n" + "\n".join(self.secciones),
            encoding="utf-8",
        )
        print(f"Reporte: {reporte}")
        print(f"Figuras: {self.dir_figuras}")
        return reporte
