"""
Accès base partagé par les modules v3.

- `executer()` : le client supabase-py est SYNCHRONE ; l'appeler directement
  dans une route `async` bloque l'event loop pour tous les utilisateurs (y
  compris les flux audio WebSocket en cours). Tout appel passe donc par un
  thread.
- `est_erreur_schema()` : reconnaît une table/colonne absente (migration pas
  encore appliquée) pour répondre 503 explicite au lieu d'une erreur opaque.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from fastapi import HTTPException

from supabase_client import get_supabase_client

T = TypeVar("T")

_MARQUEURS_SCHEMA = (
    "42P01",  # undefined_table
    "42703",  # undefined_column
    "PGRST205",  # table absente du cache de schéma PostgREST
    "PGRST204",  # colonne absente du cache de schéma PostgREST
    "Could not find the table",
    "Could not find the '",
    "does not exist",
)


def client():
    return get_supabase_client()


async def executer(fonction: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await asyncio.to_thread(fonction, *args, **kwargs)


def est_erreur_schema(exc: BaseException) -> bool:
    texte = f"{exc!r} {getattr(exc, 'message', '')} {getattr(exc, 'code', '')}"
    return any(marqueur in texte for marqueur in _MARQUEURS_SCHEMA)


def migration_manquante(migration: str, fonctionnalite: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "message": f"{fonctionnalite} indisponible : la migration {migration} n'est pas appliquée sur la base.",
            "code": "migration_manquante",
            "migration": migration,
        },
    )
