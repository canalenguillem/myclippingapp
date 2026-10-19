"""Textos para YouTube (título, descripción y etiquetas) de un short, con el modelo y con un plan B sin red.

El modelo solo PROPONE: lo que devuelve se limpia (sin `<` ni `>`, longitudes de YouTube, `#Shorts`) y el usuario lo revisa y
edita en el editor antes de subir nada.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

TITLE_MAX = 100
DESCRIPTION_MAX = 4900          # YouTube admite 5000 bytes: margen por los caracteres multibyte
TAG_MAX_CHARS = 30
TAGS_TOTAL_CHARS = 450          # YouTube cuenta ~500 entre todas las etiquetas
TAGS_MAX = 15
SHORTS_TAG = "#Shorts"


@dataclass
class Seo:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    source: str = "model"


def _plain(text: str) -> str:
    return re.sub(r"[<>]", "", str(text or "")).replace("\r", "").strip()


def clean_title(text: str) -> str:
    title = re.sub(r"\s+", " ", _plain(text))
    if len(title) <= TITLE_MAX:
        return title
    cut = title[:TITLE_MAX].rsplit(" ", 1)[0]
    return (cut or title[:TITLE_MAX]).rstrip(" ,;:-")


def clean_description(text: str) -> str:
    body = _plain(text)[:DESCRIPTION_MAX].rstrip()
    if SHORTS_TAG.lower() not in body.lower():
        body = (body + "\n\n" if body else "") + SHORTS_TAG
    return body


def clean_tags(tags) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    total = 0
    for raw in tags if isinstance(tags, list) else []:
        tag = re.sub(r"\s+", " ", re.sub(r"[<>,#]", "", str(raw))).strip()[:TAG_MAX_CHARS].strip()
        if not tag or tag.lower() in seen:
            continue
        if len(out) >= TAGS_MAX or total + len(tag) + 1 > TAGS_TOTAL_CHARS:
            break
        out.append(tag)
        seen.add(tag.lower())
        total += len(tag) + 1
    return out


def clean(seo: Seo) -> Seo:
    return Seo(clean_title(seo.title), clean_description(seo.description), clean_tags(seo.tags), seo.source)


def fallback(*, title: str, hook: str, reason: str, transcript: str, emphasis: list[str]) -> Seo:
    """Sin modelo: título del clip, descripción con el porqué y etiquetas a partir de las palabras de énfasis."""
    base = clean_title(hook or title or "Short")
    description = (reason or transcript or "")[:300].strip()
    return clean(Seo(base, description, ["shorts", *emphasis], source="plan_b"))


PROMPT = (
    "Eres editor de un canal de YouTube Shorts. Escribe los textos de publicación del short a partir de su transcripción. "
    "Responde SOLO un JSON con: \"title\" (máx. 70 caracteres, gancho claro y honesto), \"description\" (2–4 líneas que expliquen "
    "de qué va el short y terminen con 3 hashtags, uno de ellos #Shorts) y \"tags\" (de 6 a 12 etiquetas cortas, sin #). "
    "Reglas: escribe en el idioma indicado; NO inventes datos ni afirmes como hecho lo que es opinión de quien habla (atribúyelo: "
    "«según…», «opina que…»); sin titulares falsos ni insultos; no menciones que lo ha escrito una IA; sin los caracteres < >."
)


def default_llm(system: str, user: str) -> dict | None:
    from app.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, timeout=40)
        response = client.chat.completions.create(
            model=settings.openai_clip_model, temperature=0.6, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - red, cuota o JSON roto: se cae al plan B y el usuario lo ve
        return None


def generate(*, title: str, hook: str, reason: str, transcript: str, emphasis: list[str], channel_name: str, language: str,
             seo_rules: str, llm: Callable[[str, str], dict | None] | None = default_llm) -> Seo:
    plan_b = fallback(title=title, hook=hook, reason=reason, transcript=transcript, emphasis=emphasis)
    if llm is None:
        return plan_b
    user = (
        f"Idioma: {language}\nCanal: {channel_name}\nReglas del canal: {seo_rules.strip() or '(ninguna)'}\n"
        f"Título interno del clip: {title}\nGancho: {hook}\nPor qué es interesante: {reason}\n"
        f"Transcripción:\n{transcript[:1800]}"
    )
    data = llm(PROMPT, user)
    if not data or not str(data.get("title", "")).strip():
        return plan_b
    return clean(Seo(str(data.get("title", "")), str(data.get("description", "")), data.get("tags") or [], source="model"))


HANDLE_RE = re.compile(r"^@?([A-Za-z0-9._\-·]{1,60})$")


def normalize_handle(text: str) -> str:
    """«esRadio», «@esRadio» o «https://www.youtube.com/@esRadio» → «@esRadio»; vacío si no es un handle válido."""
    text = (text or "").strip()
    m = re.search(r"youtube\.com/(@[^/?#\s]+)", text)
    text = m.group(1) if m else text
    m = HANDLE_RE.match(text)
    return f"@{m.group(1)}" if m else ""


def handle_from_info(info: dict) -> str:
    """El @ del canal del vídeo original, de los metadatos de yt-dlp (`uploader_id` o la URL del canal)."""
    for key in ("uploader_id", "channel_url", "uploader_url"):
        value = str(info.get(key) or "")
        if "@" in value:
            return normalize_handle(value)
    return ""


def source_link(url: str, start: float) -> str:
    """Enlace al vídeo original en el segundo donde empieza el clip (YouTube); otras URLs, tal cual."""
    m = re.search(r"(?:youtu\.be/|[?&]v=|/shorts/)([A-Za-z0-9_-]{11})", url or "")
    if not m:
        return url
    return f"https://www.youtube.com/watch?v={m.group(1)}&t={max(0, int(start))}s"


def with_source(description: str, *, handle: str, url: str, start: float) -> str:
    """Cabecera de la descripción: el @ del canal original lo primero (para etiquetarlo) y el enlace al vídeo original.
    No repite lo que ya está."""
    link = source_link(url, start)
    head: list[str] = []
    if handle and handle.lower() not in description.lower():
        head.append(handle)
    if link and link not in description:
        head.append(f"Vídeo original: {link}")
    return "\n".join(head) + ("\n\n" + description if description and head else description)
