from __future__ import annotations

import re
import unicodedata

COMUNAS_REGION = (
    "La Serena", "Coquimbo", "Andacollo", "Vicuña", "Paihuano",
    "Ovalle", "Monte Patria", "Combarbalá", "Punitaqui", "Río Hurtado",
    "Illapel", "Salamanca", "Los Vilos", "Canela",
)
NOMBRE_REGION = "Región de Coquimbo"

MAPA_DELITOS = (
    (r"microtr[aá]fico|peque[nñ]as cantidades", "Microtráfico"),
    (r"asociaci[oó]n (criminal|il[ií]cita)|organizaci[oó]n criminal|crimen organizado",
     "Asociación criminal para el tráfico"),
    (r"lavado", "Lavado de activos"),
    (r"cultivo|plantaci[oó]n|siembra", "Cultivo ilegal"),
    (r"tr[aá]fico|narcotr[aá]fico|ley 20\.?000|ley de drogas|droga", "Tráfico de drogas"),
    (r"sicariato", "Sicariato"),
    (r"homicidio|asesinato", "Homicidio"),
    (r"arma|munici[oó]n", "Porte ilegal de armas"),
    (r"receptaci[oó]n", "Receptación"),
    (r"contrabando", "Contrabando"),
    (r"cohecho|soborno|corrupci[oó]n", "Cohecho"),
    (r"secuestro", "Secuestro"),
    (r"robo|hurto", "Robo"),
)

ROLES_INSTITUCIONALES = ("fiscal", "vocero policial", "autoridad", "defensor", "juez")

_SINONIMOS_ROL = (
    (r"detenid", "detenido"),
    (r"formalizad", "formalizado"),
    (r"imputad|investigad|sospechos", "imputado"),
    (r"acusad", "acusado"),
    (r"condenad|sentenciad", "condenado"),
    (r"v[ií]ctima|fallecid|herid", "víctima"),
    (r"testigo", "testigo"),
    (r"fiscal", "fiscal"),
    (r"juez|jueza|magistrad", "juez"),
    (r"defens", "defensor"),
    (r"carabiner|polic|comisari|capit[aá]n|teniente|coronel|mayor|prefect|inspector|"
     r"jefe|jefa|comandante|vocer|alcaide|gendarm|detective|oficial", "vocero policial"),
    (r"alcalde|alcaldesa|delegad|ministr|gobernador|seremi|subsecretari|autoridad|director",
     "autoridad"),
)

PATRON_INSTITUCION = re.compile(
    r"carabineros|\bpdi\b|polic[ií]a|fiscal[ií]a|ministerio p[uú]blico|gendarmer[ií]a|"
    r"juzgado|tribunal|corte|municipalidad|municipio|delegaci[oó]n|gobierno|"
    r"\bos-?7\b|\bgope\b|brianco|brico|bicrim|brigada|labocar|aduana|armada|"
    r"servicio|senda|defensor[ií]a|comisar[ií]a|subcomisar[ií]a|tenencia|prefectura",
    re.IGNORECASE,
)

PATRON_INICIALES = re.compile(r"^(?:[A-ZÁÉÍÓÚÑ]\.\s?){2,6}$|^[A-ZÁÉÍÓÚÑ]{3,5}$")
PATRON_ALIAS = re.compile(r"\balias\b|apodad[oa]|conocid[oa] como", re.IGNORECASE)


def clave(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


_CLAVES_COMUNA = {clave(c): c for c in COMUNAS_REGION}


def comuna_canonica(lugar: str) -> str | None:
    k = re.sub(r"^(comuna|ciudad) de ", "", clave(lugar))
    return _CLAVES_COMUNA.get(k)


def es_region(lugar: str) -> bool:
    return clave(lugar) in {"region de coquimbo", "iv region", "cuarta region", "coquimbo region"}


def es_institucion(organizacion: str) -> bool:
    return bool(PATRON_INSTITUCION.search(organizacion or ""))


def es_iniciales(nombre: str) -> bool:
    return bool(PATRON_INICIALES.match((nombre or "").strip()))


def delito_canonico(texto: str) -> str:
    for patron, canonico in MAPA_DELITOS:
        if re.search(patron, texto or "", re.IGNORECASE):
            return canonico
    return (texto or "Otro").strip().capitalize()


def rol_canonico(rol) -> str | None:
    if not rol:
        return None
    rol = str(rol).strip().lower()
    for patron, canonico in _SINONIMOS_ROL:
        if re.search(patron, rol):
            return canonico
    return rol


def tipo_lugar(nombre: str) -> str:
    if comuna_canonica(nombre):
        return "comuna"
    if nombre == NOMBRE_REGION:
        return "región"
    return "sector"
