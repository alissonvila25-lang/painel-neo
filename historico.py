"""Analitico historico do NEO — snapshot diario (D-1) acumulado no Google Sheets.

Cada dia vira uma linha com os totais da Performance de Operacao daquele dia.
`atualizar_ate` preenche os dias faltantes ate D-1 (com limite de chamadas por
execucao, para nao pesar no carregamento do painel). O mesmo modulo e usado pelo
script de snapshot diario (GitHub Action).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import engine as E
import portal as P
import treino
from config import PROJETO


def _agg_dia(perf: pd.DataFrame, dia: dt.date) -> dict | None:
    p = E.normalizar_performance(perf)
    if p.empty:
        return None
    lig = float(p.get("Ligações", pd.Series(dtype=float)).sum())
    abord = float(p.get("Abordagens", pd.Series(dtype=float)).sum())
    cad = float(p.get("Propostas Cadastradas", pd.Series(dtype=float)).sum())
    conf = float(p.get("Propostas Confirmadas", pd.Series(dtype=float)).sum())
    canc = float(p.get("Propostas Canceladas", pd.Series(dtype=float)).sum())
    conv = (100.0 * cad / abord) if abord > 0 else 0.0
    abpct = (100.0 * abord / lig) if lig > 0 else 0.0
    camp = int((p.get("Ligações", pd.Series(dtype=float)) > 0).sum())
    if lig <= 0 and cad <= 0:
        return None
    return {
        "data": dia.strftime("%Y-%m-%d"),
        "ligacoes": int(lig), "abordagens": int(abord),
        "cadastradas": int(cad), "confirmadas": int(conf), "canceladas": int(canc),
        "conv_pct": round(conv, 2), "abord_pct": round(abpct, 2),
        "campanhas": camp,
    }


def _portal():
    pa = P.PortalAyty().login()
    pid = P.PROJETOS_PORTAL[PROJETO]
    g = pa.menu(pid)
    return pa, pid, g


def snapshot(dia: dt.date) -> dict | None:
    """Coleta os totais de UM dia (para o cron / bootstrap manual)."""
    pa, pid, g = _portal()
    perf = pa.fetch_relatorio(
        pid, P.RELATORIOS[pid]["performance_operacao"], dia, dia, guids=g)
    return _agg_dia(perf, dia)


def atualizar_ate(dfim: dt.date, dias_janela: int = 60,
                  max_fetch: int = 3) -> int:
    """Preenche os dias faltantes ate `dfim`, do mais recente ao mais antigo,
    limitando a `max_fetch` chamadas por execucao. Retorna quantos gravou."""
    hist = treino.carregar_historico()
    existentes = set()
    if not hist.empty and "data" in hist.columns:
        existentes = set(hist["data"].astype(str).str[:10])
    faltantes = []
    for k in range(dias_janela):
        d = dfim - dt.timedelta(days=k)
        if d.strftime("%Y-%m-%d") not in existentes:
            faltantes.append(d)
    faltantes = sorted(faltantes, reverse=True)[:max_fetch]
    if not faltantes:
        return 0
    pa, pid, g = _portal()
    rows = []
    for d in sorted(faltantes):
        try:
            perf = pa.fetch_relatorio(
                pid, P.RELATORIOS[pid]["performance_operacao"], d, d, guids=g)
            r = _agg_dia(perf, d)
            if r:
                rows.append(r)
        except Exception:
            continue
    return treino.salvar_historico(rows)


def preparar(hist: pd.DataFrame) -> pd.DataFrame:
    """Normaliza o historico para exibicao (tipos + ordenacao)."""
    if hist is None or hist.empty:
        return pd.DataFrame()
    d = hist.copy()
    d["data"] = pd.to_datetime(d["data"], errors="coerce")
    for c in ("ligacoes", "abordagens", "cadastradas", "confirmadas",
              "canceladas", "conv_pct", "abord_pct", "campanhas"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["data"]).sort_values("data")
    d = d.drop_duplicates("data", keep="last")
    return d
