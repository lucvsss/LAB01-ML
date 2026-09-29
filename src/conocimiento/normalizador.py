from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR, DIR_JSON
from src.conocimiento.vocabulario import (
    NOMBRE_REGION,
    PATRON_ALIAS,
    PATRON_INICIALES,
    clave,
    comuna_canonica,
    delito_canonico,
    es_iniciales,
    es_region,
    rol_canonico,
)

RUTA_EQUIVALENCIAS = DATA_DIR / "equivalencias.csv"
CAMPOS_LISTA = ("delitos", "personas", "organizaciones", "lugares", "objetos", "relaciones")


def cargar_noticias(dir_json: Path = DIR_JSON) -> tuple[list[dict], list[str]]:
    rutas = sorted(dir_json.glob("*.json"))
    reales = [r for r in rutas if not r.name.startswith("ejemplo")]
    if not reales and rutas:
        print("  Aviso: solo existe el JSON de ejemplo; se usa para probar el vault.")
        reales = rutas

    noticias, problemas = [], []
    for ruta in reales:
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problemas.append(f"{ruta.name}: JSON inválido ({exc})")
            continue
        if not isinstance(data, dict) or not data.get("id_noticia"):
            problemas.append(f"{ruta.name}: no es un objeto con id_noticia")
            continue
        for campo in CAMPOS_LISTA:
            if not isinstance(data.get(campo), list):
                if campo in data:
                    problemas.append(f"{ruta.name}: '{campo}' no es lista; se trata como vacía")
                data[campo] = []
        noticias.append(data)
    return noticias, problemas


class NormalizadorEntidades:

    def __init__(self, ruta_equivalencias: Path = RUTA_EQUIVALENCIAS) -> None:
        self.equivalencias: dict[tuple[str, str], str] = {}
        if ruta_equivalencias and Path(ruta_equivalencias).exists():
            with Path(ruta_equivalencias).open(encoding="utf-8", newline="") as fh:
                for fila in csv.DictReader(fh):
                    variante = clave(fila.get("variante") or "")
                    canonico = (fila.get("canonico") or "").strip()
                    if variante and canonico:
                        tipo = (fila.get("tipo") or "*").strip().lower()
                        self.equivalencias[(tipo, variante)] = canonico

    def _eq(self, tipo: str, nombre: str) -> str | None:
        k = clave(nombre)
        return self.equivalencias.get((tipo, k)) or self.equivalencias.get(("*", k))

    def normalizar_corpus(self, noticias: list[dict]) -> list[dict]:
        return self._unificar([self.normalizar(d) for d in noticias])

    def normalizar(self, data: dict) -> dict:
        d = json.loads(json.dumps(data))
        nid = d["id_noticia"]
        d["fuente"] = self._fuente(d.get("fuente"))
        d["fecha_publicacion"] = self._fecha(d.get("fecha_publicacion"))
        mapa: dict[str, str | None] = {}

        d["delitos"] = self._unicos([
            self._reg(mapa, x, self._eq("delito", x) or delito_canonico(x))
            for x in d["delitos"] if isinstance(x, str) and x.strip()
        ])
        d["lugares"] = self._unicos([
            self._reg(mapa, x, self._lugar(x))
            for x in d["lugares"] if isinstance(x, str) and x.strip()
        ])
        d["organizaciones"] = self._unicos([
            self._reg(mapa, x, self._eq("organizacion", x) or self._limpio(x))
            for x in d["organizaciones"] if isinstance(x, str) and x.strip()
        ])
        d["personas"] = self._personas(d["personas"], nid, mapa)
        d["objetos"] = self._objetos(d["objetos"], mapa)
        d["relaciones"] = self._relaciones(d["relaciones"], mapa)
        d["comunas"] = [x for x in d["lugares"] if comuna_canonica(x)]
        d["sectores"] = [x for x in d["lugares"] if not comuna_canonica(x) and x != NOMBRE_REGION]
        return d

    def _fuente(self, fuente) -> str:
        limpia = re.sub(r"\s+", " ", str(fuente or "")).strip(" |-–").replace("|", "/") or "desconocida"
        return self._eq("fuente", limpia) or limpia

    @staticmethod
    def _fecha(fecha) -> str | None:
        if not fecha:
            return None
        s = str(fecha).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        m = re.match(r"^(\d{2})[-/](\d{2})[-/](\d{4})$", s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return None

    @staticmethod
    def _limpio(texto: str) -> str:
        return re.sub(r"\s+", " ", str(texto)).strip()

    @staticmethod
    def _reg(mapa: dict, original: str, normal: str | None) -> str | None:
        mapa[clave(original)] = normal
        return normal

    @staticmethod
    def _unicos(valores: list) -> list:
        vistos, salida = set(), []
        for v in valores:
            if v and clave(v) not in vistos:
                vistos.add(clave(v))
                salida.append(v)
        return salida

    def _lugar(self, texto: str) -> str:
        texto = self._limpio(texto)
        normal = self._eq("lugar", texto)
        if not normal:
            normal = NOMBRE_REGION if es_region(texto) else (comuna_canonica(texto) or texto)
        if normal.islower():
            normal = " ".join(
                w if w in ("de", "del", "la", "las", "los", "el", "y") else w.capitalize()
                for w in normal.split()
            )
        return normal

    def _personas(self, personas: list, nid: str, mapa: dict) -> list[dict]:
        salida, vistos = [], set()
        for p in personas:
            if not isinstance(p, dict) or not p.get("nombre"):
                continue
            original = self._limpio(p["nombre"])
            nombre = self._eq("persona", original) or original
            if nombre.isupper() and not es_iniciales(nombre):
                nombre = nombre.title()
            if es_iniciales(nombre) or PATRON_ALIAS.search(nombre):
                nombre = f"{nombre} ({nid})"
            mapa[clave(original)] = nombre
            if clave(nombre) not in vistos:
                vistos.add(clave(nombre))
                salida.append({"nombre": nombre, "rol": rol_canonico(p.get("rol"))})
        return salida

    def _objetos(self, objetos: list, mapa: dict) -> list[dict]:
        salida = []
        for o in objetos:
            if not isinstance(o, dict) or not o.get("nombre"):
                continue
            original = self._limpio(o["nombre"])
            nombre = self._eq("objeto", original) or original.lower()
            mapa[clave(original)] = nombre
            salida.append({
                "tipo": o.get("tipo") or "otro",
                "nombre": nombre,
                "cantidad": o.get("cantidad"),
                "unidad": o.get("unidad"),
            })
        return salida

    @staticmethod
    def _relaciones(relaciones: list, mapa: dict) -> list[dict]:
        salida, vistas = [], set()
        for r in relaciones:
            if not isinstance(r, dict):
                continue
            origen = mapa.get(clave(str(r.get("origen", ""))), r.get("origen"))
            destino = mapa.get(clave(str(r.get("destino", ""))), r.get("destino"))
            tipo = str(r.get("tipo") or "").strip().upper().replace(" ", "_")
            if not origen or not destino or not tipo:
                continue
            firma = (clave(origen), tipo, clave(destino))
            if firma not in vistas:
                vistas.add(firma)
                salida.append({"origen": origen, "tipo": tipo, "destino": destino})
        return salida

    def _unificar(self, noticias: list[dict]) -> list[dict]:
        formas: dict[str, Counter] = {}
        for d in noticias:
            nombres = d["delitos"] + d["organizaciones"] + d["lugares"]
            nombres += [p["nombre"] for p in d["personas"]] + [o["nombre"] for o in d["objetos"]]
            for n in nombres:
                formas.setdefault(clave(n), Counter())[n] += 1
        canon = {
            k: max(c.items(), key=lambda kv: (kv[1], sum(ch.isupper() for ch in kv[0]), kv[0]))[0]
            for k, c in formas.items()
        }

        def f(n: str) -> str:
            return canon.get(clave(n), n)

        for d in noticias:
            for campo in ("delitos", "organizaciones", "lugares", "comunas", "sectores"):
                d[campo] = self._unicos([f(x) for x in d[campo]])
            for p in d["personas"]:
                p["nombre"] = f(p["nombre"])
            for o in d["objetos"]:
                o["nombre"] = f(o["nombre"])
            for r in d["relaciones"]:
                r["origen"], r["destino"] = f(r["origen"]), f(r["destino"])
        return noticias
