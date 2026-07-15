"""Auto-calibracao do painel NEO — ajusta o EXPOENTE de compressao da conversao.

Sem base virgem, o unico parametro relevante do merito e o expoente. A partir
das avaliacoes acumuladas (peso ideal + features), reconstroi a redistribuicao
por lote (data + avaliador + curva; curva costuma ser vazia no NEO -> 1 pool por
lote) e busca o expoente que minimiza o erro vs o peso ideal humano.
"""
from __future__ import annotations

import pandas as pd

_EXPOENTES = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
_COLS_NUM = ["peso_config", "peso_disc", "peso_ideal", "conv", "disp_abs", "disp_pct"]


def _truthy(v) -> bool:
    s = str(v).strip().lower()
    if s == "":
        return True
    return s in ("true", "1", "sim", "verdadeiro", "v")


def _limpar(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    c = df.copy()
    for col in _COLS_NUM:
        if col in c.columns:
            c[col] = pd.to_numeric(c[col], errors="coerce")
    for col in ("data", "avaliador", "curva"):
        if col not in c.columns:
            c[col] = ""
        c[col] = c[col].astype(str)
    ref = c.get("peso_config")
    if ref is None:
        ref = c.get("peso_disc")
    elif "peso_disc" in c.columns:
        ref = ref.fillna(c["peso_disc"])
    c["_ref"] = ref
    return c.dropna(subset=["_ref", "peso_ideal", "conv"])


def _merito(conv: float, disp_abs: float, vol_med: float, expoente: float) -> float:
    cvc = max(conv, 0.1) ** expoente
    vf = (max(disp_abs, 1.0) / vol_med) ** 0.35
    return cvc * min(1.5, max(0.7, vf))


def _mae(df: pd.DataFrame, expoente: float) -> tuple[float | None, int]:
    has_rod = "rodando" in df.columns
    has_disp = "disp_pct" in df.columns
    erros: list[float] = []
    for _, g in df.groupby(["data", "avaliador", "curva"]):
        pool = g[g["_ref"] > 0]
        if has_rod:
            pool = pool[pool["rodando"].map(_truthy)]
        if has_disp:
            dp = pd.to_numeric(pool["disp_pct"], errors="coerce")
            pool = pool[dp.isna() | (dp >= 3)]
        if len(pool) < 2:
            continue
        budget = float(pool["_ref"].sum())
        if budget <= 0:
            continue
        vols = [max(float(x), 0.0) for x in pool["disp_abs"].fillna(0.0)]
        vol_med = float(pd.Series(vols).median()) or 1.0
        merits, ideais = [], []
        for _, r in pool.iterrows():
            da = float(r["disp_abs"]) if pd.notna(r.get("disp_abs")) else 0.0
            merits.append(_merito(float(r["conv"]), da, vol_med, expoente))
            ideais.append(float(r["peso_ideal"]))
        soma = sum(merits) or 1.0
        for m, ideal in zip(merits, ideais):
            erros.append(abs(budget * m / soma - ideal))
    if not erros:
        return None, 0
    return sum(erros) / len(erros), len(erros)


def calibrar(df_treino: pd.DataFrame, min_aval: int = 30,
             expoente_atual: float = 0.6) -> dict:
    c = _limpar(df_treino)
    n = int(len(c))
    if n < min_aval:
        return {"ok": False, "n": n, "min_aval": min_aval,
                "msg": f"Sao necessarias ao menos {min_aval} avaliacoes "
                       f"(atuais: {n})."}
    mae_atual, pares = _mae(c, expoente_atual)
    if mae_atual is None or pares < 6:
        return {"ok": False, "n": n, "pares": pares,
                "msg": "Poucos lotes com 2+ campanhas para reconstruir a "
                       "redistribuicao. Avalie mais campanhas no mesmo dia."}
    melhor = (expoente_atual, mae_atual)
    for e in _EXPOENTES:
        m, _ = _mae(c, e)
        if m is not None and m < melhor[1]:
            melhor = (e, m)
    e, mae_novo = melhor
    melhora = mae_atual - mae_novo
    return {
        "ok": True, "n": n, "pares": pares,
        "peso_expoente": round(e, 2), "expoente_atual": round(expoente_atual, 2),
        "mae_antes": round(mae_atual, 2), "mae_depois": round(mae_novo, 2),
        "melhora_pct": round(melhora / mae_atual * 100 if mae_atual > 0 else 0, 1),
        "mudou": round(e, 2) != round(expoente_atual, 2), "msg": "ok",
    }
