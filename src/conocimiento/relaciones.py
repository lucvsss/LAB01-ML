from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

from src.conocimiento.vocabulario import clave, es_iniciales, es_institucion, ROLES_INSTITUCIONALES


@dataclass
class RelacionNoticias:
    origen: str
    destino: str
    nivel: str
    motivos: list[str] = field(default_factory=list)


class AnalizadorRelaciones:
    """Sección 10 de la ficha: dos noticias se relacionan si comparten
    un mismo sujeto, una misma organización, o la misma comuna y delito.
    """

    def calcular(self, noticias: list[dict]) -> list[RelacionNoticias]:
        relaciones = []
        for a, b in combinations(sorted(noticias, key=lambda d: d["id_noticia"]), 2):
            motivos = self._motivos(a, b)
            if motivos:
                relaciones.append(RelacionNoticias(a["id_noticia"], b["id_noticia"], "relacionadas", motivos))
        return relaciones

    def _motivos(self, a: dict, b: dict) -> list[str]:
        motivos = []

        # Mismo sujeto (identidad confirmada o no, sección 7)
        personas_a = self._personas(a)
        personas_b = self._personas(b)
        comunes = personas_a & personas_b
        # Identidades no confirmadas (iniciales) solo se conectan si además
        # comparten la misma comuna y el mismo hecho (sección 7 de la ficha)
        for p in sorted(comunes):
            if self._es_no_confirmada(p):
                if set(a.get("comunas", [])) & set(b.get("comunas", [])):
                    motivos.append(f"misma persona (no confirmada, misma comuna): {p}")
            else:
                motivos.append(f"misma persona: {p}")

        # Misma organización
        orgs_a = {o for o in a.get("organizaciones", []) if not es_institucion(o)}
        orgs_b = {o for o in b.get("organizaciones", []) if not es_institucion(o)}
        for o in sorted(orgs_a & orgs_b):
            motivos.append(f"misma organización: {o}")

        # Misma comuna y mismo delito
        comunas = set(a.get("comunas", [])) & set(b.get("comunas", []))
        delitos = set(a.get("delitos", [])) & set(b.get("delitos", []))
        if comunas and delitos:
            motivos.append(
                f"misma comuna ({', '.join(sorted(comunas))}) y delito ({', '.join(sorted(delitos))})"
            )

        return motivos

    @staticmethod
    def _personas(d: dict) -> set[str]:
        return {
            p["nombre"]
            for p in d.get("personas", [])
            if p.get("nombre") and p.get("rol") not in ROLES_INSTITUCIONALES
        }

    @staticmethod
    def _es_no_confirmada(nombre: str) -> bool:
        base = nombre.split("(")[0].strip()
        return es_iniciales(base) or "alias" in nombre.lower()

    @staticmethod
    def grupos_mismo_hecho(relaciones: list[RelacionNoticias]) -> list[list[str]]:
        padre: dict[str, str] = {}

        def raiz(x: str) -> str:
            padre.setdefault(x, x)
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        for rel in relaciones:
            padre[raiz(rel.origen)] = raiz(rel.destino)
        grupos: dict[str, list[str]] = {}
        for nodo in list(padre):
            grupos.setdefault(raiz(nodo), []).append(nodo)
        return sorted((sorted(g) for g in grupos.values() if len(g) > 1), key=lambda g: g[0])
