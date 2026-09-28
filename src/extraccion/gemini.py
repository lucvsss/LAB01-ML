"""Extractor Gemini: texto limpio → JSON del contrato del laboratorio.

Implementación mínima y ejecutable. El laboratorio NO inventa datos:
solo se extrae información explícita en la noticia, en JSON válido.

TODO(alumno) — mejoras opcionales, el código ya corre sin ellas:
- reintentos ante 429 / timeouts
- recorte de textos muy largos antes del prompt
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from src.config import DIR_JSON, GEMINI_API_KEY, GEMINI_MODEL, PAUSA_ENTRE_REQUESTS
from src.modelos import NoticiaFuente


class ExtractorLLM(ABC):
    """Interfaz de cualquier extractor basado en modelo generativo."""

    @abstractmethod
    def construir_prompt(self, noticia: NoticiaFuente) -> str:
        """Arma el prompt con el esquema JSON y el texto de la noticia."""

    @abstractmethod
    def extraer(self, noticia: NoticiaFuente) -> dict:
        """Devuelve un diccionario que cumple el contrato JSON del laboratorio."""


class ExtractorGemini(ExtractorLLM):
    """Extractor oficial del laboratorio (Gemini).

    1. Carga GEMINI_API_KEY desde .env (nunca hardcodear la clave).
    2. Usa el texto ya limpio en noticia.texto_limpio.
    3. Llama al modelo (p. ej. gemini-2.0-flash) con construir_prompt().
    4. Parsea JSON (quita fences markdown si el modelo los agrega).
    5. Guarda data/json/{id_noticia}.json.
    """

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
    ]

    def __init__(self, dir_json: Path = DIR_JSON) -> None:
        self.dir_json = dir_json
        self.dir_json.mkdir(parents=True, exist_ok=True)
        self._cliente = None

    MAX_CARACTERES = 12000
    @staticmethod
    def _recortar(texto: str, maximo: int = MAX_CARACTERES) -> str:
        if len(texto) <= maximo:
            return texto
        else:
            corte = texto[:maximo]
            ultimo_parrafo = corte.rfind("\n")
            if ultimo_parrafo > maximo * 0.7: 
                corte = corte[:ultimo_parrafo]
            return corte.strip()

    def construir_prompt(self, noticia: NoticiaFuente) -> str:
        campos = ", ".join(self.CAMPOS_OBLIGATORIOS)
        texto = self._recortar((noticia.texto_limpio or ""))
        return (
    "Eres un asistente que estructura noticias policiales de la Region de Coquimbo, Chile.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Extrae SOLO informacion explicita en el texto. No inventes datos, cantidades, "
    "nombres, roles ni relaciones. Si falta un dato, usa null o lista vacia.\n"
    "2. Presuncion de inocencia: los roles de personas son procesales "
    "(imputado, investigado, detenido, formalizado, victima, testigo). "
    "Nunca uses 'culpable', 'delincuente' ni 'criminal' como rol.\n"
    "3. Personas: registra el nombre tal como aparece. Si solo hay iniciales, alias "
    "o nombre parcial, pon identidad_confirmada=false; nunca completes el apellido. "
    "Con nombre y apellido completos, identidad_confirmada=true.\n"
    "4. lugares: incluye SIEMPRE la comuna si el texto la menciona.\n"
    "5. relaciones: solo las que la noticia establece expresamente. "
    "Tipos permitidos: OPERA_EN, INVESTIGADO_POR, DETENIDO_EN, PERTENECE_A, "
    "VICTIMA_DE, INCAUTADO_EN.\n"
    "6. vinculo_narcotrafico: true solo si la noticia vincula explicitamente el hecho "
    "con trafico o microtrafico de drogas; en otro caso false.\n"
    "7. Devuelve exclusivamente JSON valido, sin markdown.\n\n"
    f"Campos obligatorios: {campos}, vinculo_narcotrafico.\n"
    "personas: lista de {nombre, rol, identidad_confirmada}.\n"
    "objetos: lista de {tipo, nombre, cantidad, unidad}.\n"
    "relaciones: lista de {origen, tipo, destino}.\n\n"
    f"id_noticia: {noticia.id_noticia}\n"
    f"fuente: {noticia.fuente}\n"
    f"url: {noticia.url}\n\n"
    f"NOTICIA:\n{texto}\n"
)

    def _llamar_gemini(self, cliente, types, prompt: str, intentos: int = 4):
        espera = 5
        for intento in range(1, intentos + 1):
            try:
                return cliente.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        response_mime_type="application/json",
                        temperature=0,
                    ),
                )
            except Exception as exc: 
                codigo = getattr(exc, "code", None)
                temporal = codigo in (429, 500, 503, 504) or "timeout" in str(exc).lower()
                if not temporal or intento == intentos:
                    raise
                print(f"   Error en GEMINI {codigo}; reintento {intento}/{intentos - 1} en {espera}s")
                time.sleep(espera)
                espera *= 2

    def extraer(self, noticia: NoticiaFuente) -> dict:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "Falta GEMINI_API_KEY. Copie .env.example a .env y complete la clave. "
                "Nunca suba .env a GitHub."
            )
        cliente = self._obtener_cliente()
        from google.genai import types

        
        respuesta = self._llamar_gemini(cliente, types, self.construir_prompt(noticia))

        bruto = (getattr(respuesta, "text", None) or "").strip()
        if not bruto:
            raise ValueError(
                f"Gemini devolvió una respuesta vacía para {noticia.id_noticia}."
            )
        data = self._parsear_json(bruto)
        data["id_noticia"] = noticia.id_noticia
        if not data.get("fuente"):
            data["fuente"] = noticia.fuente
        if not data.get("url"):
            data["url"] = noticia.url
        ruta = self.dir_json / f"{noticia.id_noticia}.json"
        ruta.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        time.sleep(PAUSA_ENTRE_REQUESTS)
        return data

    def _obtener_cliente(self):
        if self._cliente is None:
            from google import genai

            self._cliente = genai.Client(api_key=GEMINI_API_KEY)
        return self._cliente

    @staticmethod
    def _parsear_json(bruto: str) -> dict:
        texto = bruto.strip()
        cerca = re.search(r"```(?:json)?\s*(.*?)\s*```", texto, re.DOTALL)
        if cerca:
            texto = cerca.group(1)
        try:
            data = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Gemini no devolvió JSON válido: {exc}. "
                f"Respuesta: {texto[:300]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError("La respuesta de Gemini no es un objeto JSON.")
        return data
