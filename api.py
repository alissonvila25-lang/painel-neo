"""
Prime Performance API — FastAPI sobre o portal Ayty/NEO.

Autenticacao: header  X-API-Key: <PRIME_API_KEY>

Endpoints:
  GET  /health                          → status
  GET  /api/campanhas?di=&dfim=         → performance + sugestoes de peso
  GET  /api/historico                   → historico diario acumulado (Sheets)
  GET  /api/operadores?di=&dfim=        → ranking de operadores
  GET  /api/base                        → saude do mailing (discador)
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from functools import wraps
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

# adiciona o diretorio raiz ao path para importar os modulos do painel
sys.path.insert(0, os.path.dirname(__file__))

import engine as E
import historico as H
import treino
from config import THRESHOLDS, now_br, today_br
from portal import PROJETOS_PORTAL, RELATORIOS, PortalAyty

# ---------------------------------------------------------------------------
# App e autenticacao
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Prime Performance API",
    version="1.0.0",
    description="API de dados operacionais da operação NEO Energia.",
    docs_url="/docs",
    redoc_url=None,
)

_API_KEY     = os.environ.get("PRIME_API_KEY", "")
_api_key_hdr = APIKeyHeader(name="X-API-Key", auto_error=True)


async def _auth(key: str = Security(_api_key_hdr)):
    if not _API_KEY:
        raise HTTPException(status_code=503, detail="API key nao configurada no servidor.")
    if key != _API_KEY:
        raise HTTPException(status_code=403, detail="API key invalida.")
    return key


# ---------------------------------------------------------------------------
# Cache simples em memoria (evita chamar o portal em todas as requests)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = int(os.environ.get("API_CACHE_TTL_S", "900"))  # 15 min default


def _cached(key: str, fn, ttl: int = _CACHE_TTL):
    now = time.time()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < ttl:
            return val
    val = fn()
    _cache[key] = (now, val)
    return val


def _portal() -> PortalAyty:
    return PortalAyty(
        usuario=os.environ.get("AYTY_PORTAL_USER", ""),
        senha=os.environ.get("AYTY_PORTAL_SENHA", ""),
    ).login()


def _to_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return df.where(pd.notnull(df), None).to_dict(orient="records")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["status"])
def health():
    return {"status": "ok", "timestamp": str(now_br())}


@app.get("/api/campanhas", tags=["dados"], dependencies=[Depends(_auth)])
def campanhas(di: str | None = None, dfim: str | None = None):
    """Performance de campanhas + sugestao de pesos para o periodo.

    - `di` / `dfim`: datas no formato YYYY-MM-DD (default: hoje).
    """
    hoje = today_br()
    try:
        dt_ini = date.fromisoformat(di)   if di   else hoje
        dt_fim = date.fromisoformat(dfim) if dfim else hoje
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de data invalido. Use YYYY-MM-DD.")

    cache_key = f"campanhas:{dt_ini}:{dt_fim}"

    def _fetch():
        pa   = _portal()
        pid  = PROJETOS_PORTAL["NEO"]
        r    = RELATORIOS[pid]
        perf = pa.fetch_relatorio(pid, r["performance_operacao"], dt_ini, dt_fim)
        disc = pa.estatisticas_discador("NEO", detalhado=True)
        cfg  = pa.config_campanha_grupo("NEO")
        df, acoes = E.analisar(perf, disc, cfg, THRESHOLDS)
        return {
            "periodo": {"ini": str(dt_ini), "fim": str(dt_fim)},
            "campanhas": _to_records(df),
            "acoes": acoes,
            "kpis": E.resumo_kpis(df),
        }

    try:
        return _cached(cache_key, _fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar portal: {e}")


@app.get("/api/operadores", tags=["dados"], dependencies=[Depends(_auth)])
def operadores(di: str | None = None, dfim: str | None = None):
    """Ranking de operadores por producao no periodo."""
    hoje = today_br()
    try:
        dt_ini = date.fromisoformat(di)   if di   else hoje - timedelta(days=6)
        dt_fim = date.fromisoformat(dfim) if dfim else hoje
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de data invalido.")

    cache_key = f"operadores:{dt_ini}:{dt_fim}"

    def _fetch():
        pa  = _portal()
        pid = PROJETOS_PORTAL["NEO"]
        r   = RELATORIOS[pid]
        abc = pa.fetch_relatorio(pid, r["curva_abc_usuario"], dt_ini, dt_fim)
        tmo = pa.fetch_relatorio(pid, r["tmo_operador"],     dt_ini, dt_fim)
        ops = E.operadores(abc, tmo)
        return {
            "periodo": {"ini": str(dt_ini), "fim": str(dt_fim)},
            "operadores": _to_records(ops),
        }

    try:
        return _cached(cache_key, _fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar portal: {e}")


@app.get("/api/historico", tags=["dados"], dependencies=[Depends(_auth)])
def historico_diario():
    """Historico diario acumulado (snapshot D-1, fonte: Google Sheets)."""
    def _fetch():
        hist = H.preparar(treino.carregar_historico())
        if hist.empty:
            return {"historico": []}
        hist["data"] = hist["data"].dt.strftime("%Y-%m-%d")
        return {"historico": _to_records(hist)}

    try:
        return _cached("historico", _fetch, ttl=3600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao acessar historico: {e}")


@app.get("/api/base", tags=["dados"], dependencies=[Depends(_auth)])
def saude_base():
    """Saude do mailing por campanha (fonte: discador)."""
    def _fetch():
        pa   = _portal()
        disc = pa.estatisticas_discador("NEO", detalhado=True)
        dd   = E.normalizar_discador(disc)
        if dd.empty:
            return {"base": []}
        tot  = dd.get("Total da Base", pd.Series(0, index=dd.index)).fillna(0)
        disp = dd.get("Disponiveis",   pd.Series(0, index=dd.index)).fillna(0)
        fin  = dd.get("Finalizados",   pd.Series(0, index=dd.index)).fillna(0)
        dd["Disponivel %"] = (100 * disp / tot.replace(0, float("nan"))).round(1)
        dd["Finalizado %"] = (100 * fin  / tot.replace(0, float("nan"))).round(1)
        return {"base": _to_records(dd), "total_nomes": int(tot.sum()),
                "total_disponiveis": int(disp.sum())}

    try:
        return _cached("base", _fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar discador: {e}")
