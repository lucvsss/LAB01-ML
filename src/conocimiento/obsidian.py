"""Persistencia final: red de notas Markdown para Obsidian.
Jerarquía generada:
    obsidian_vault/
    ├── 00_Indice.md
    ├── Noticias/       
    ├── Delitos/         
    ├── Personas/
    ├── Organizaciones/
    ├── Lugares/
    ├── Objetos/
    └── Relaciones/     
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path

from src.config import DIR_JSON, DIR_VAULT
from src.conocimiento.normalizador import NormalizadorEntidades, cargar_noticias
from src.conocimiento.relaciones import AnalizadorRelaciones, RelacionNoticias
from src.conocimiento.utilidades import slugify
from src.conocimiento.vocabulario import (
    COMUNAS_REGION,
    ROLES_INSTITUCIONALES,
    comuna_canonica,
    es_institucion,
    tipo_lugar,
)

CARPETAS = ("Noticias", "Delitos", "Personas", "Organizaciones", "Lugares", "Objetos", "Relaciones")

AVISO_ETICO = (
    "> [Advertencia] Uso netamente académico\n"
)

GRAPH_JSON = """{
  "showTags": false,
  "showAttachments": false,
  "showOrphans": true,
  "colorGroups": [
    {"query": "path:Noticias", "color": {"a": 1, "rgb": 3900150}},
    {"query": "path:Delitos", "color": {"a": 1, "rgb": 14427686}},
    {"query": "path:Personas", "color": {"a": 1, "rgb": 16096779}},
    {"query": "path:Organizaciones", "color": {"a": 1, "rgb": 1483594}},
    {"query": "path:Lugares", "color": {"a": 1, "rgb": 9133302}},
    {"query": "path:Objetos", "color": {"a": 1, "rgb": 7041664}},
    {"query": "path:Relaciones", "color": {"a": 1, "rgb": 10265519}}
  ]
}
"""


def enlace(carpeta: str, nombre: str) -> str:
    """[[Carpeta/Slug|Nombre visible]]"""
    return f"[[{carpeta}/{slugify(nombre)}|{nombre}]]"


def enlace_noticia(nid: str) -> str:
    return f"[[Noticias/{nid}|{nid}]]"


def _yaml(valor) -> str:
    """Serializa un valor simple a YAML (strings entre comillas dobles)."""
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    if isinstance(valor, (list, tuple)):
        return "[" + ", ".join(_yaml(v) for v in valor) + "]"
    texto = str(valor).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{texto}"'


def frontmatter(campos: dict) -> str:
    return "---\n" + "".join(f"{k}: {_yaml(v)}\n" for k, v in campos.items()) + "---\n"


def _cantidad(objeto: dict) -> str:
    cantidad, unidad = objeto.get("cantidad"), objeto.get("unidad")
    if cantidad is None:
        return "cantidad no informada"
    # Gemini a veces devuelve cantidad como string
    try:
        cantidad = float(str(cantidad).replace(",", "."))
    except (ValueError, TypeError):
        return f"{cantidad}" + (f" {unidad}" if unidad else "")
    if cantidad == int(cantidad):
        cantidad = int(cantidad)
    texto = f"{cantidad:,}".replace(",", "§").replace(".", ",").replace("§", ".")
    return texto + (f" {unidad}" if unidad else "")


class EscritorObsidian(ABC):
    """Contrato para generar la bóveda a partir de JSON validado."""

    @abstractmethod
    def escribir_noticia(self, data: dict) -> Path:
        """Crea obsidian_vault/Noticias/{id_noticia}.md con frontmatter y enlaces."""

    @abstractmethod
    def escribir_entidades(self, noticias: list[dict]) -> None:
        """Agrega notas de delitos, personas, organizaciones, lugares y objetos."""

    @abstractmethod
    def escribir_indice(self, noticias: list[dict]) -> Path:
        """Crea obsidian_vault/00_Indice.md."""

    @abstractmethod
    def escribir_vault(self, noticias: list[dict]) -> None:
        """Orquesta noticia + entidades + índice."""


class EscritorVaultObsidian(EscritorObsidian):
    """Genera la bóveda completa a partir de los JSON de data/json/."""

    def __init__(
        self,
        vault: Path = DIR_VAULT,
        dir_json: Path = DIR_JSON,
        normalizador: NormalizadorEntidades | None = None,
    ) -> None:
        self.vault = vault
        self.dir_json = dir_json
        self.normalizador = normalizador or NormalizadorEntidades()
        self.relaciones: list[RelacionNoticias] = []
        self.grupos_mismo_hecho: list[list[str]] = []
        self.problemas_carga: list[str] = []
        self._por_id: dict[str, dict] = {}

    def _ruta(self, carpeta: str, nombre: str) -> Path:
        return self.vault / carpeta / f"{slugify(nombre)}.md"

    def _escribir(self, ruta: Path, contenido: str) -> Path:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido.rstrip() + "\n", encoding="utf-8")
        return ruta

    def _limpiar_vault(self) -> None:
        """Borra solo las notas generadas (*.md); conserva .gitkeep y .obsidian/."""
        for carpeta in CARPETAS:
            for nota in (self.vault / carpeta).glob("*.md"):
                nota.unlink()
        indice = self.vault / "00_Indice.md"
        if indice.exists():
            indice.unlink()

    def _linea_noticia(self, nid: str, extra: str = "") -> str:
        d = self._por_id.get(nid, {})
        fecha = d.get("fecha_publicacion") or "s/f"
        titulo = d.get("titulo") or ""
        return f"- {enlace_noticia(nid)} · {fecha} · {titulo}{extra}"

    def _relacionadas_de(self, nid: str) -> list[tuple[str, RelacionNoticias]]:
        salida = []
        for rel in self.relaciones:
            if rel.origen == nid:
                salida.append((rel.destino, rel))
            elif rel.destino == nid:
                salida.append((rel.origen, rel))
        return sorted(salida, key=lambda x: x[0])

    def escribir_noticia(self, data: dict) -> Path:
        nid = data["id_noticia"]
        personas = data.get("personas", [])
        objetos = data.get("objetos", [])
        lineas = [
            frontmatter(
                {
                    "id": nid,
                    "tipo": "noticia",
                    "titulo": data.get("titulo"),
                    "fecha_publicacion": data.get("fecha_publicacion"),
                    "fecha_hecho": data.get("fecha_hecho"),
                    "fuente": data.get("fuente"),
                    "url": data.get("url"),
                    "comunas": data.get("comunas", []),
                    "delitos": data.get("delitos", []),
                    "n_personas": len(personas),
                    "n_organizaciones": len(data.get("organizaciones", [])),
                    "tags": ["noticia"] + [f"delito/{slugify(d)}" for d in data.get("delitos", [])],
                }
            ),
            f"# {data.get('titulo') or nid}",
            "",
            f"**Fuente:** [{data.get('fuente') or 'medio'}]({data.get('url')}) · "
            f"**Publicada:** {data.get('fecha_publicacion') or 'sin fecha'}"
            + (f" · **Fecha del hecho:** {data['fecha_hecho']}" if data.get("fecha_hecho") else ""),
            "",
            "## Resumen",
            data.get("resumen") or "_Sin resumen._",
            "",
            "## Delitos",
            *([f"- {enlace('Delitos', d)}" for d in data.get("delitos", [])] or ["_Ninguno._"]),
            "",
            "## Personas",
            *(
                [f"- {enlace('Personas', p['nombre'])} — {p.get('rol') or 'rol no informado'}" for p in personas]
                or ["_Ninguna con nombre._"]
            ),
            "",
            "## Organizaciones",
            *(
                [
                    f"- {enlace('Organizaciones', o)}"
                    + (" _(institución)_" if es_institucion(o) else "")
                    for o in data.get("organizaciones", [])
                ]
                or ["_Ninguna._"]
            ),
            "",
            "## Lugares",
            *(
                [f"- {enlace('Lugares', x)} _({tipo_lugar(x)})_" for x in data.get("lugares", [])]
                or ["_Ninguno._"]
            ),
            "",
            "## Objetos incautados",
            *(
                [f"- {enlace('Objetos', o['nombre'])} — {_cantidad(o)}" for o in objetos]
                or ["_Ninguno._"]
            ),
            "",
            "## Relaciones",
            *(
                [
                    f"- {self._enlace_entidad(r['origen'], data)} — `{r['tipo']}` → "
                    f"{self._enlace_entidad(r['destino'], data)}"
                    for r in data.get("relaciones", [])
                ]
                or ["_Sin relaciones explícitas._"]
            ),
            "",
            "## Noticias relacionadas",
        ]
        relacionadas = self._relacionadas_de(nid)
        if relacionadas:
            for otra, rel in relacionadas:
                lineas.append(self._linea_noticia(otra, f" — **{rel.nivel}**: {'; '.join(rel.motivos)}"))
        else:
            lineas.append("_Sin noticias relacionadas._")
        lineas += ["", AVISO_ETICO]
        return self._escribir(self.vault / "Noticias" / f"{nid}.md", "\n".join(lineas))

    @staticmethod
    def _enlace_entidad(nombre: str, data: dict) -> str:
        """Enlaza el extremo de una relación a la carpeta de la entidad que corresponde."""
        if nombre in data.get("delitos", []):
            return enlace("Delitos", nombre)
        if any(p["nombre"] == nombre for p in data.get("personas", [])):
            return enlace("Personas", nombre)
        if nombre in data.get("organizaciones", []):
            return enlace("Organizaciones", nombre)
        if nombre in data.get("lugares", []):
            return enlace("Lugares", nombre)
        if any(o["nombre"] == nombre for o in data.get("objetos", [])):
            return enlace("Objetos", nombre)
        return f"{nombre} _(no es entidad de la noticia)_"

    # ENTIDADES
    def escribir_entidades(self, noticias: list[dict]) -> None:
        # Indices entidad 
        idx = {c: defaultdict(set) for c in ("Delitos", "Personas", "Organizaciones", "Lugares", "Objetos")}
        roles = defaultdict(list)          # persona 
        cantidades = defaultdict(list)     # objeto 
        tipo_objeto = {}
        coocurrencias = defaultdict(lambda: defaultdict(set))  # (carpeta, nombre)
        triples = defaultdict(list)        # tipo relacion

        for d in noticias:
            nid = d["id_noticia"]
            entidades = {
                "Delitos": d.get("delitos", []),
                "Personas": [p["nombre"] for p in d.get("personas", [])],
                "Organizaciones": d.get("organizaciones", []),
                "Lugares": d.get("lugares", []),
                "Objetos": [o["nombre"] for o in d.get("objetos", [])],
            }
            for carpeta, nombres in entidades.items():
                for nombre in nombres:
                    idx[carpeta][nombre].add(nid)
                    for otra_carpeta, otros in entidades.items():
                        for otro in otros:
                            if (otra_carpeta, otro) != (carpeta, nombre):
                                coocurrencias[(carpeta, nombre)][otra_carpeta].add(otro)
            for p in d.get("personas", []):
                roles[p["nombre"]].append((nid, p.get("rol") or "rol no informado"))
            for o in d.get("objetos", []):
                cantidades[o["nombre"]].append((nid, _cantidad(o)))
                tipo_objeto[o["nombre"]] = o.get("tipo")
            for r in d.get("relaciones", []):
                triples[r["tipo"]].append((r["origen"], r["destino"], nid, d))

        def lista(carpeta: str, nombres: set[str]) -> list[str]:
            return [f"- {enlace(carpeta, n)}" for n in sorted(nombres)] or ["_Ninguno._"]

        def noticias_de(nids: set[str]) -> list[str]:
            return [self._linea_noticia(n) for n in sorted(nids, key=lambda n: (self._por_id[n].get("fecha_publicacion") or "", n))]

        for nombre, nids in idx["Delitos"].items():
            co = coocurrencias[("Delitos", nombre)]
            self._escribir(
                self._ruta("Delitos", nombre),
                "\n".join(
                    [
                        frontmatter({"tipo": "delito", "nombre": nombre, "n_noticias": len(nids), "tags": ["delito"]}),
                        f"# {nombre}", "", "Tipo: Delito", "",
                        f"## Noticias relacionadas ({len(nids)})", *noticias_de(nids), "",
                        "## Personas relacionadas", *lista("Personas", co["Personas"]), "",
                        "## Organizaciones relacionadas", *lista("Organizaciones", co["Organizaciones"]), "",
                        "## Lugares", *lista("Lugares", co["Lugares"]), "",
                        "## Objetos incautados", *lista("Objetos", co["Objetos"]),
                    ]
                ),
            )

        for nombre, nids in idx["Personas"].items():
            co = coocurrencias[("Personas", nombre)]
            roles_observados = sorted({r for _, r in roles[nombre]})
            institucional = all(r in ROLES_INSTITUCIONALES for r in roles_observados)
            self._escribir(
                self._ruta("Personas", nombre),
                "\n".join(
                    [
                        frontmatter(
                            {
                                "tipo": "persona",
                                "nombre": nombre,
                                "roles": roles_observados,
                                "funcionario": institucional,
                                "n_noticias": len(nids),
                                "tags": ["persona"] + (["funcionario"] if institucional else []),
                            }
                        ),
                        f"# {nombre}", "",
                        f"## Noticias donde aparece ({len(nids)})",
                        *[self._linea_noticia(n, f" — rol: **{r}**") for n, r in sorted(roles[nombre])], "",
                        "## Roles observados", *[f"- {r}" for r in roles_observados], "",
                        "## Delitos asociados", *lista("Delitos", co["Delitos"]), "",
                        "## Organizaciones relacionadas", *lista("Organizaciones", co["Organizaciones"]), "",
                        "## Lugares", *lista("Lugares", co["Lugares"]), "",
                        AVISO_ETICO,
                    ]
                ),
            )

        # Organizaciones
        for nombre, nids in idx["Organizaciones"].items():
            co = coocurrencias[("Organizaciones", nombre)]
            clase = "institución" if es_institucion(nombre) else "organización criminal u otra"
            self._escribir(
                self._ruta("Organizaciones", nombre),
                "\n".join(
                    [
                        frontmatter(
                            {
                                "tipo": "organizacion",
                                "nombre": nombre,
                                "clase": clase,
                                "n_noticias": len(nids),
                                "tags": ["organizacion", "institucion" if es_institucion(nombre) else "banda"],
                            }
                        ),
                        f"# {nombre}", "", f"Clase: {clase}", "",
                        f"## Noticias relacionadas ({len(nids)})", *noticias_de(nids), "",
                        "## Personas relacionadas", *lista("Personas", co["Personas"]), "",
                        "## Delitos", *lista("Delitos", co["Delitos"]), "",
                        "## Lugares donde aparece", *lista("Lugares", co["Lugares"]),
                    ]
                ),
            )

        # Lugares
        for nombre, nids in idx["Lugares"].items():
            co = coocurrencias[("Lugares", nombre)]
            tipo = tipo_lugar(nombre)
            extra = []
            if tipo == "sector":
                comunas = {x for x in co["Lugares"] if comuna_canonica(x)}
                extra = ["## Comunas mencionadas junto a este sector", *lista("Lugares", comunas), ""]
            self._escribir(
                self._ruta("Lugares", nombre),
                "\n".join(
                    [
                        frontmatter({"tipo": "lugar", "nombre": nombre, "clase": tipo, "n_noticias": len(nids), "tags": ["lugar", tipo]}),
                        f"# {nombre}", "", f"Tipo de lugar: {tipo}", "",
                        f"## Noticias ({len(nids)})", *noticias_de(nids), "",
                        *extra,
                        "## Delitos", *lista("Delitos", co["Delitos"]), "",
                        "## Organizaciones", *lista("Organizaciones", co["Organizaciones"]), "",
                        "## Objetos incautados", *lista("Objetos", co["Objetos"]),
                    ]
                ),
            )

        # Objetos
        for nombre, nids in idx["Objetos"].items():
            co = coocurrencias[("Objetos", nombre)]
            self._escribir(
                self._ruta("Objetos", nombre),
                "\n".join(
                    [
                        frontmatter({"tipo": "objeto", "nombre": nombre, "clase": tipo_objeto.get(nombre), "n_noticias": len(nids), "tags": ["objeto"]}),
                        f"# {nombre}", "", f"Tipo: {tipo_objeto.get(nombre) or 'otro'}", "",
                        f"## Incautaciones ({len(cantidades[nombre])})",
                        *[self._linea_noticia(n, f" — {c}") for n, c in sorted(cantidades[nombre])], "",
                        "## Lugares", *lista("Lugares", co["Lugares"]), "",
                        "## Delitos", *lista("Delitos", co["Delitos"]),
                    ]
                ),
            )

        # Relaciones, una nota por tipo + relaciones entre noticias
        for tipo, filas in triples.items():
            self._escribir(
                self.vault / "Relaciones" / f"{slugify(tipo)}.md",
                "\n".join(
                    [
                        frontmatter({"tipo": "relacion", "nombre": tipo, "n": len(filas), "tags": ["relacion"]}),
                        f"# {tipo}", "",
                        *[
                            f"- {self._enlace_entidad(o, d)} — `{tipo}` → {self._enlace_entidad(de, d)} ({enlace_noticia(n)})"
                            for o, de, n, d in sorted(filas, key=lambda x: x[2])
                        ],
                    ]
                ),
            )
        self._escribir_relaciones_noticias()

    def _escribir_relaciones_noticias(self) -> None:
        relacionadas = self.relaciones

        def fila(r: RelacionNoticias) -> str:
            return f"- {enlace_noticia(r.origen)} ↔ {enlace_noticia(r.destino)}: {'; '.join(r.motivos)}"

        self._escribir(
            self.vault / "Relaciones" / "Noticias_relacionadas.md",
            "\n".join(
                [
                    frontmatter({"tipo": "relacion", "nombre": "Noticias relacionadas", "total": len(relacionadas)}),
                    "# Relaciones entre noticias", "",
                    "Criterios de la sección 10 de la ficha: mismo sujeto, misma organización, "
                    "o misma comuna y delito. Las noticias que solo comparten una institución "
                    "(Carabineros, PDI, Fiscalía) o solo un funcionario (vocero policial) **no** se relacionan.",
                    "",
                    f"## Noticias relacionadas ({len(relacionadas)})",
                    *([fila(r) for r in relacionadas] or ["_Ninguna._"]),
                ]
            ),
        )
        self._escribir(
            self.vault / "Relaciones" / "Mismo_hecho.md",
            "\n".join(
                [
                    frontmatter({"tipo": "relacion", "nombre": "Mismo hecho", "grupos": len(self.grupos_mismo_hecho)}),
                    "# Mismo hecho cubierto por varios medios", "",
                    "Cada grupo reúne noticias de distintos medios sobre un mismo procedimiento. "
                    "Para contar hechos distintos, cada grupo vale uno.", "",
                    *(
                        [
                            f"- Grupo {i}: " + ", ".join(
                                f"{enlace_noticia(n)} ({self._por_id[n].get('fuente')})" for n in grupo
                            )
                            for i, grupo in enumerate(self.grupos_mismo_hecho, 1)
                        ]
                        or ["_No se detectaron hechos repetidos._"]
                    ),
                ]
            ),
        )

    # INDICE
    def escribir_indice(self, noticias: list[dict]) -> Path:
        conteo = defaultdict(lambda: defaultdict(int))
        for d in noticias:
            for delito in d.get("delitos", []):
                conteo["Delitos"][delito] += 1
            for comuna in d.get("comunas", []):
                conteo["Comunas"][comuna] += 1
            for org in d.get("organizaciones", []):
                if not es_institucion(org):
                    conteo["Bandas"][org] += 1
            for p in d.get("personas", []):
                if p.get("rol") not in ROLES_INSTITUCIONALES:
                    conteo["Personas"][p["nombre"]] += 1

        def top(tipo: str, carpeta: str, n: int = 15) -> list[str]:
            items = sorted(conteo[tipo].items(), key=lambda x: (-x[1], x[0]))[:n]
            return [f"| {enlace(carpeta, k).replace('|', chr(92) + '|')} | {v} |" for k, v in items] or ["| _sin datos_ | 0 |"]

        hechos_distintos = len(noticias) - sum(len(g) - 1 for g in self.grupos_mismo_hecho)
        comunas_sin = [c for c in COMUNAS_REGION if c not in conteo["Comunas"]]
        ordenadas = sorted(noticias, key=lambda d: (d.get("fecha_publicacion") or "", d["id_noticia"]), reverse=True)
        lineas = [
            frontmatter({"tipo": "indice", "noticias": len(noticias), "hechos_distintos": hechos_distintos}),
            "# Narcotráfico en la Región de Coquimbo — Índice",
            "",
            "Base de conocimiento generada automáticamente por el pipeline del laboratorio "
            "(noticias → texto limpio → Gemini → JSON validado → notas Markdown).",
            "",
            "## Resumen",
            f"- Noticias en alcance: **{len(noticias)}**",
            f"- Hechos distintos (agrupando cobertura repetida): **{hechos_distintos}**",
            f"- Medios: **{len({d.get('fuente') for d in noticias})}**",
            f"- Comunas con hechos: **{len(conteo['Comunas'])}** de {len(COMUNAS_REGION)}"
            + (f" (sin noticias: {', '.join(comunas_sin)})" if comunas_sin else ""),
            f"- Relaciones entre noticias: [[Relaciones/Noticias_relacionadas|ver detalle]] · "
            f"[[Relaciones/Mismo_hecho|hechos cubiertos por varios medios]]",
            "",
            "## Delitos más frecuentes", "| Delito | Noticias |", "|---|---|", *top("Delitos", "Delitos"), "",
            "## Comunas con más hechos", "| Comuna | Noticias |", "|---|---|", *top("Comunas", "Lugares"), "",
            "## Organizaciones criminales mencionadas", "| Organización | Noticias |", "|---|---|", *top("Bandas", "Organizaciones"), "",
            "## Personas (no funcionarios) con más menciones", "| Persona | Noticias |", "|---|---|", *top("Personas", "Personas"), "",
            "## Todas las noticias (más recientes primero)",
            *[self._linea_noticia(d["id_noticia"], f" ({d.get('fuente')})") for d in ordenadas],
            "",
            "## Cómo leer el grafo",
            "- Colores por carpeta (configurados en `.obsidian/graph.json`): noticias, delitos, personas, organizaciones, lugares, objetos.",
            "- Carabineros, PDI, Fiscalía y el delito *Tráfico de drogas* son nodos centrales que conectan casi todo. "
            "Para ver agrupamientos reales, filtre el grafo con `-tag:#institucion -path:Relaciones`.",
            "- Las relaciones útiles entre noticias están en [[Relaciones/Noticias_relacionadas]].",
        ]
        fuera = [d["id_noticia"] for d in noticias if not d.get("comunas")]
        if fuera or self.problemas_carga:
            lineas += ["", "## Avisos de calidad"]
            if fuera:
                lineas.append(
                    "- Noticias sin ninguna comuna de la región en `lugares` (revisar alcance o extracción): "
                    + ", ".join(enlace_noticia(n) for n in fuera)
                )
            lineas += [f"- Archivo omitido: {p}" for p in self.problemas_carga]
        return self._escribir(self.vault / "00_Indice.md", "\n".join(lineas))

    # VAULT/BOVEDA
    def escribir_vault(self, noticias: list[dict] | None = None) -> None:
        """Orquesta noticia + entidades + índice.

        pipeline.ejecutar_obsidian() llama escribir_vault([]): en ese caso se
        cargan todos los JSON de data/json/. Si se entregan noticias, se usan esas.
        """
        if not noticias:
            noticias, self.problemas_carga = cargar_noticias(self.dir_json)
            for problema in self.problemas_carga:
                print(f"  Se omite {problema}")
        if not noticias:
            print(f"No hay JSON en {self.dir_json}. Ejecute primero: python main.py extraer")
            return
        noticias = self.normalizador.normalizar_corpus(noticias)

        self.vault.mkdir(parents=True, exist_ok=True)
        self._limpiar_vault()
        self._por_id = {d["id_noticia"]: d for d in noticias}
        analizador = AnalizadorRelaciones()
        self.relaciones = analizador.calcular(noticias)
        self.grupos_mismo_hecho = analizador.grupos_mismo_hecho(self.relaciones)

        for d in noticias:
            self.escribir_noticia(d)
        self.escribir_entidades(noticias)
        self.escribir_indice(noticias)

        config = self.vault / ".obsidian" / "graph.json"
        if not config.exists():
            self._escribir(config, GRAPH_JSON)
        print(
            f"Vault generado en {self.vault}: {len(noticias)} noticias, "
            f"{len(self.relaciones)} relaciones entre noticias, "
            f"{len(self.grupos_mismo_hecho)} grupos de mismo hecho."
        )
