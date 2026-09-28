"""Validación del JSON producido por el LLM.

El LLM no es la fuente de verdad: el código debe verificar el esquema.

- ERRORES: el JSON se rechaza.
- ADVERTENCIAS: el JSON se acepta, pero se registra lo faltante.
- REGISTRO: guardar_registro() deja un JSON para Data Understanding.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path


def _norm(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", str(texto))
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


class ValidadorJSON:
    """Comprueba que cada archivo JSON cumpla el contrato de datos."""

    CAMPOS_OBLIGATORIOS = [
        "id_noticia",
        "titulo",
        "fecha_publicacion",
        "fuente",
        "url",
        "resumen",
        "delitos",
        "personas",
        "organizaciones",
        "lugares",
        "objetos",
        "relaciones",
        "vinculo_narcotrafico",
    ]

    CAMPOS_LISTA = [
        "delitos",
        "personas",
        "organizaciones",
        "lugares",
        "objetos",
        "relaciones",
    ]

    TIPOS_RELACION = {
        "OPERA_EN",
        "INVESTIGADO_POR",
        "DETENIDO_EN",
        "PERTENECE_A",
        "VICTIMA_DE",
        "INCAUTADO_EN",
    }

    ROLES_PROHIBIDOS = {
        "culpable", "delincuente", "criminal", "asesino", "homicida",
        "narcotraficante", "narco", "sicario", "autor",
    }

    COMUNAS = {
        "la serena", "coquimbo", "ovalle", "vicuna", "andacollo", "paihuano",
        "illapel", "salamanca", "los vilos", "canela", "monte patria",
        "combarbala", "punitaqui", "rio hurtado"
    }

    def __init__(self) -> None:
        self.registro: list[dict] = []

    def validar(self, ruta: str | Path, texto_fuente: str | None = None) -> dict:
        """Lee, parsea y valida un JSON. Lanza ValueError si el contrato no se cumple.
        """

        archivo = Path(ruta)
        errores = []
        advertencias = []
        data = None

        try:
            data = json.loads(archivo.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errores.append("no contiene un objeto JSON")
            else:
                self._validar_estructura(data, errores)
                if not errores:
                    self._validar_reglas(data, texto_fuente, advertencias)
        except json.JSONDecodeError as exc:
            errores.append(f"JSON inválido: {exc}")

        self._registrar(archivo, data, errores, advertencias)
        if errores:
            raise ValueError(f"{archivo.name}: " + " | ".join(errores))
        return data

    def validar_todos(self, dir_json: str | Path) -> list[dict]:
        """Valida todos los .json de un directorio; devuelve solo los válidos."""
        validos = []
        for ruta in sorted(Path(dir_json).glob("*.json")):
            if ruta.name.startswith("_"):  # ignora archivos de registro
                continue
            try:
                validos.append(self.validar(ruta))
            except ValueError as exc:
                print(f"  RECHAZADO {exc}")
        return validos

    def guardar_registro(self, ruta: str | Path) -> None:
        """Guarda el registro de validación (insumo de ExploradorDatos)."""
        Path(ruta).write_text(
            json.dumps(self.registro, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------ estructura
    def _validar_estructura(self, data: dict, errores: list[str]) -> None:
        faltantes = [c for c in self.CAMPOS_OBLIGATORIOS if c not in data]
        if faltantes:
            errores.append(f"faltan campos {faltantes}")
            return

        for campo in self.CAMPOS_LISTA:
            if not isinstance(data[campo], list):
                errores.append(f"'{campo}' debe ser una lista")
        if errores:
            return

        if not isinstance(data["vinculo_narcotrafico"], bool):
            errores.append("'vinculo_narcotrafico' debe ser true o false")

        fecha = data["fecha_publicacion"]
        if fecha is not None:
            try:
                datetime.strptime(str(fecha), "%Y-%m-%d")
            except ValueError:
                errores.append(f"fecha_publicacion '{fecha}' no es AAAA-MM-DD")

        for i, d in enumerate(data["delitos"]):
            if not isinstance(d, str) or not d.strip():
                errores.append(f"delitos[{i}] debe ser un texto no vacío")
        for i, o in enumerate(data["organizaciones"]):
            if not isinstance(o, str) or not o.strip():
                errores.append(f"organizaciones[{i}] debe ser un texto no vacío")
        for i, lg in enumerate(data["lugares"]):
            if not isinstance(lg, str) or not lg.strip():
                errores.append(f"lugares[{i}] debe ser un texto no vacío")

        for i, p in enumerate(data["personas"]):
            if not isinstance(p, dict):
                errores.append(f"personas[{i}] debe ser un objeto")
                continue
            if not isinstance(p.get("nombre"), str) or not p["nombre"].strip():
                errores.append(f"personas[{i}] sin 'nombre'")
            if not isinstance(p.get("identidad_confirmada"), bool):
                errores.append(f"personas[{i}] sin 'identidad_confirmada' booleano")
            rol = p.get("rol")
            if rol is not None and not isinstance(rol, str):
                errores.append(f"personas[{i}] 'rol' debe ser texto o null")
            elif isinstance(rol, str) and any(
                w in self.ROLES_PROHIBIDOS for w in _norm(rol).split()
            ):
                errores.append(
                    f"personas[{i}] rol '{rol}' afirma culpabilidad "
                    "(usar roles procesales)"
                )

        for i, o in enumerate(data["objetos"]):
            if not isinstance(o, dict) or not o.get("nombre"):
                errores.append(f"objetos[{i}] debe ser objeto con 'nombre'")

        for i, r in enumerate(data["relaciones"]):
            if not isinstance(r, dict):
                errores.append(f"relaciones[{i}] debe ser un objeto")
                continue
            if not all(r.get(k) for k in ("origen", "tipo", "destino")):
                errores.append(f"relaciones[{i}] requiere origen, tipo y destino")
            elif r["tipo"] not in self.TIPOS_RELACION:
                errores.append(f"relaciones[{i}] tipo '{r['tipo']}' no permitido")

    # -------------------------------------------------------------- reglas
    def _validar_reglas(
        self, data: dict, texto_fuente: str | None, adv: list[str]
    ) -> None:
        if not data["vinculo_narcotrafico"]:
            adv.append("sin vínculo con narcotráfico (fuera de alcance)")
        if data["fecha_publicacion"] is None:
            adv.append("fecha_publicacion nula")

        lugares_norm = {_norm(x) for x in data["lugares"]}
        if not lugares_norm & self.COMUNAS:
            adv.append("no se identificó ninguna comuna de la Región de Coquimbo")

        for p in data["personas"]:
            partes = _norm(p["nombre"]).replace(".", " ").split()
            if p["identidad_confirmada"] and len(partes) < 2:
                adv.append(
                    f"'{p['nombre']}' marcado confirmado con nombre incompleto"
                )
            if not p["identidad_confirmada"] and len(partes) >= 3:
                adv.append(
                    f"'{p['nombre']}' parece nombre completo pero no confirmado"
                )

        # Relaciones entre entidades que no fueron listadas
        entidades = (
            {_norm(d) for d in data["delitos"]}
            | {_norm(o) for o in data["organizaciones"]}
            | lugares_norm
            | {_norm(p["nombre"]) for p in data["personas"]}
            | {_norm(o["nombre"]) for o in data["objetos"]}
        )
        for r in data["relaciones"]:
            for extremo in ("origen", "destino"):
                if _norm(r[extremo]) not in entidades:
                    adv.append(
                        f"relación {r['tipo']}: '{r[extremo]}' no está entre "
                        "las entidades extraídas"
                    )

        # Posibles entidades inventadas (no aparecen en el texto fuente)
        if texto_fuente:
            texto = _norm(texto_fuente)
            candidatas = [p["nombre"] for p in data["personas"]] + list(
                data["organizaciones"]
            )
            for nombre in candidatas:
                if _norm(nombre) not in texto:
                    adv.append(f"'{nombre}' no aparece literal en el texto fuente")

    # ------------------------------------------------------------ registro
    def _registrar(self, archivo, data, errores, advertencias) -> None:
        nulos = []
        if isinstance(data, dict):
            nulos = [
                k for k, v in data.items() if v is None or v == [] or v == ""
            ]
        self.registro.append(
            {
                "archivo": archivo.name,
                "id_noticia": data.get("id_noticia") if isinstance(data, dict) else None,
                "valido": not errores,
                "errores": errores,
                "advertencias": advertencias,
                "campos_vacios": nulos,
            }
        )