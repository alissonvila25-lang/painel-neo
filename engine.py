"""Analise do painel NEO ENERGIA a partir dos relatorios do portal.

Sem API: junta Performance de Operacao (campanha), Config Campanha (peso real +
curva) e Estatisticas do Discador (base disponivel/hit rate) por CODIGO de
campanha. Conversao = Propostas Cadastradas / Abordagens (a coluna nativa do
portal vem zerada). O peso sugerido e uma versao SIMPLIFICADA (conversao +
base disponivel), pois o portal deste tenant nao expoe base virgem.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from config import THRESHOLDS

_COD_RE = re.compile(r"0*(\d+)")
_CURVA_RE = re.compile(r"CURVA\s+([A-Za-z0-9]+)", re.I)
_PESO_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def _num(v) -> float:
    """Converte texto pt-BR ('39,27', '1.234,56', '4.81%') em float."""
    if v is None:
        return np.nan
    s = str(v).strip()
    if s in ("", "-", "nan", "None"):
        return np.nan
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return np.nan
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _codigo(nome) -> int | None:
    m = _COD_RE.search(str(nome or ""))
    return int(m.group(1)) if m else None


def _peso_int(v) -> float:
    """'3 (4.7619%)' -> 3.0 ; '15' -> 15.0."""
    m = _PESO_RE.search(str(v or ""))
    return float(m.group(1).replace(",", ".")) if m else np.nan


# --------------------------------------------------------------------------- #
# Normalizacao de cada relatorio
# --------------------------------------------------------------------------- #
def normalizar_performance(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["Codigo"] = d["Campanha"].map(_codigo)
    for c in ("Ligações", "Abordagens", "Contatos", "Propostas Cadastradas",
              "Propostas Confirmadas", "Propostas Canceladas", "Trabalhados",
              "Quantidade de PAs", "Dias Trabalhados"):
        if c in d.columns:
            d[c] = d[c].map(_num)
    d = d.dropna(subset=["Codigo"])
    d["Codigo"] = d["Codigo"].astype(int)
    return d


def normalizar_discador(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["Codigo"] = d["Campanha"].map(_codigo)
    d["Peso Disc"] = d["Peso"].map(_peso_int)
    for c in ("Hit Rate", "Penetração", "Spin Rate", "Total da Base",
              "Disponíveis", "Livres", "Total Bloqueados", "Buffer"):
        if c in d.columns:
            d[c] = d[c].map(_num)
    d["Curva Disc"] = d["Grupo de Atendimento"].map(
        lambda g: (_CURVA_RE.search(str(g)).group(1).upper()
                   if _CURVA_RE.search(str(g)) else ""))
    d = d.dropna(subset=["Codigo"])
    d["Codigo"] = d["Codigo"].astype(int)
    # agrega por campanha (varios grupos de atendimento)
    ag = d.groupby("Codigo").agg(
        **{"Peso Disc": ("Peso Disc", "max"),
           "Hit Rate %": ("Hit Rate", "max"),
           "Penetracao %": ("Penetração", "max"),
           "Total da Base": ("Total da Base", "sum"),
           "Disponiveis": ("Disponíveis", "sum"),
           "Livres": ("Livres", "sum"),
           "Bloqueados": ("Total Bloqueados", "sum"),
           "Curva Disc": ("Curva Disc", lambda s: next((x for x in s if x), ""))})
    return ag.reset_index()


def normalizar_config(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Codigo" not in df.columns:
        return pd.DataFrame()
    d = df.copy()
    d["Codigo"] = pd.to_numeric(d["Codigo"], errors="coerce")
    d = d.dropna(subset=["Codigo"])
    d["Codigo"] = d["Codigo"].astype(int)
    d["Peso Config"] = d["Peso"].map(_peso_int)
    d["Curva"] = d["Curva"].astype(str).str.upper().str.strip()
    d = d[d["Grupo de Atendimento"].astype(str).str.strip() != ""]
    ag = d.groupby("Codigo").agg(
        **{"Peso Config": ("Peso Config", "max"),
           "Curva": ("Curva", lambda s: next((x for x in s if x), ""))})
    return ag.reset_index()


# --------------------------------------------------------------------------- #
# Analise
# --------------------------------------------------------------------------- #
def analisar(perf: pd.DataFrame, disc: pd.DataFrame, cfg: pd.DataFrame,
             thr: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    thr = thr or THRESHOLDS
    p = normalizar_performance(perf)
    if p.empty:
        return pd.DataFrame(), []
    d = normalizar_discador(disc)
    c = normalizar_config(cfg)

    base = p
    if not d.empty:
        base = base.merge(d, on="Codigo", how="left")
    if not c.empty:
        base = base.merge(c, on="Codigo", how="left")

    reg, acoes = [], []
    for _, r in base.iterrows():
        def _v(x) -> float:
            try:
                f = float(x)
                return 0.0 if np.isnan(f) else f
            except (TypeError, ValueError):
                return 0.0
        lig = _v(r.get("Ligações"))
        abord = _v(r.get("Abordagens"))
        cad = _v(r.get("Propostas Cadastradas"))
        canc = _v(r.get("Propostas Canceladas"))
        conf = _v(r.get("Propostas Confirmadas"))
        conv = (100.0 * cad / abord) if abord > 0 else np.nan
        abord_pct = (100.0 * abord / lig) if lig > 0 else np.nan
        total_base = _v(r.get("Total da Base"))
        disp = _v(r.get("Disponiveis"))
        disp_pct = (100.0 * disp / total_base) if total_base > 0 else np.nan
        peso_cfg = r.get("Peso Config")
        peso_disc = r.get("Peso Disc")
        peso_ref = peso_cfg if pd.notna(peso_cfg) else peso_disc
        tem_peso = pd.notna(peso_ref)
        curva = (r.get("Curva") if isinstance(r.get("Curva"), str) and r.get("Curva")
                 else (r.get("Curva Disc") or ""))
        hit = float(r.get("Hit Rate %") or np.nan)
        rodando = lig > 0

        rec_conv = 0 if np.isnan(conv) else conv
        oportunidade = (lig >= thr["min_ligacoes"] and rec_conv >= thr["conv_alta"]
                        and (np.isnan(disp_pct) or disp_pct > 15))
        # status
        score = 60.0
        motivos = []
        if not np.isnan(conv):
            if conv >= thr["conv_alta"]:
                score += 20
            elif conv < thr["conv_baixa"]:
                score -= 20
                motivos.append(f"conversao baixa ({conv:.1f}%)")
        if not np.isnan(disp_pct) and disp_pct < thr["disp_baixa_pct"]:
            score -= 18
            motivos.append(f"base disponivel baixa ({disp_pct:.0f}%)")
        if not np.isnan(abord_pct) and abord_pct < thr["abordagem_baixa"]:
            score -= 10
            motivos.append(f"abordagem baixa ({abord_pct:.0f}%)")
        score = max(0.0, min(100.0, score))
        status = ("Oportunidade" if oportunidade and score >= 75
                  else "Critico" if score < 50
                  else "Atencao" if score < 75 else "Saudavel")

        # coerencia peso x performance
        coer = "SEM_DADO"
        if tem_peso:
            if peso_ref > 0 and not rodando:
                coer = "OCIOSO"
            elif oportunidade:
                coer = "SUBIR"
            elif (lig >= thr["min_ligacoes"] and not np.isnan(conv)
                  and conv < thr["conv_baixa"]) or (
                    not np.isnan(disp_pct) and disp_pct < 3):
                coer = "BAIXAR"
            else:
                coer = "OK"

        reg.append({
            "Codigo": int(r["Codigo"]),
            "Campanha": r.get("Campanha"),
            "Curva": curva,
            "Peso Config": peso_cfg if pd.notna(peso_cfg) else None,
            "Peso Disc": peso_disc if pd.notna(peso_disc) else None,
            "Coerencia": coer,
            "Rodando": rodando,
            "Ligacoes": int(lig),
            "Abordagens": int(abord),
            "% Abordagem": round(abord_pct, 1) if not np.isnan(abord_pct) else None,
            "Cadastradas": int(cad),
            "Confirmadas": int(conf),
            "Canceladas": int(canc),
            "% Conversao": round(conv, 1) if not np.isnan(conv) else None,
            "Hit Rate %": round(hit, 1) if not np.isnan(hit) else None,
            "Penetracao %": (round(float(r["Penetracao %"]), 1)
                             if pd.notna(r.get("Penetracao %")) else None),
            "Total da Base": int(total_base) if total_base else 0,
            "Disponiveis": int(disp) if disp else 0,
            "Disponivel %": round(disp_pct, 1) if not np.isnan(disp_pct) else None,
            "Score": round(score, 0),
            "Status": status,
        })

        # acoes acionaveis
        def add(sev, tit, det):
            acoes.append({"Severidade": sev, "Campanha": r.get("Campanha"),
                          "Codigo": int(r["Codigo"]), "Curva": curva,
                          "Titulo": tit, "Detalhe": det, "Ligacoes": int(lig)})

        if lig >= thr["min_ligacoes"] and not np.isnan(disp_pct) and disp_pct < 3:
            add("CRITICO", "Base esgotada com discagem ativa",
                f"{int(lig)} ligacoes e apenas {disp_pct:.0f}% de base disponivel. "
                "Reabastecer o mailing ou reduzir o peso.")
        if lig >= thr["min_ligacoes"] and not np.isnan(conv) and conv < thr["conv_baixa"]:
            add("ATENCAO", "Conversao baixa com volume",
                f"Conversao {conv:.1f}% em {int(lig)} ligacoes. Revisar abordagem "
                "ou reduzir peso.")
        if lig >= thr["min_ligacoes"] and not np.isnan(abord_pct) and abord_pct < thr["abordagem_baixa"]:
            add("ATENCAO", "Abordagem baixa",
                f"% Abordagem {abord_pct:.0f}% — possivel problema de "
                "contactabilidade (linha/horario/base).")
        if oportunidade:
            add("OPORTUNIDADE", "Alta conversao + base disponivel",
                f"Conversao {conv:.1f}% e base disponivel — avaliar aumentar o peso.")

    df_camp = pd.DataFrame(reg)
    if not df_camp.empty:
        df_camp["Peso Sugerido"] = _sugerir_pesos(df_camp, thr)
        df_camp = _reconciliar_coerencia(df_camp)
        df_camp = df_camp.sort_values(["Score", "Ligacoes"], ascending=[True, False])
    sev_ord = {"CRITICO": 0, "ATENCAO": 1, "OPORTUNIDADE": 2, "INFO": 3}
    acoes.sort(key=lambda a: (sev_ord.get(a["Severidade"], 9), -a["Ligacoes"]))
    return df_camp, acoes


def _sugerir_pesos(df: pd.DataFrame, thr: dict) -> pd.Series:
    """Redistribui o peso total da curva entre campanhas ativas por merito
    (conversao comprimida x base disponivel). Simplificado: sem base virgem."""
    n = len(df)
    out = pd.Series([None] * n, index=df.index, dtype="object")
    ref = pd.to_numeric(df.get("Peso Config"), errors="coerce")
    ref = ref.fillna(pd.to_numeric(df.get("Peso Disc"), errors="coerce"))
    conv = pd.to_numeric(df.get("% Conversao"), errors="coerce")
    disp = pd.to_numeric(df.get("Disponivel %"), errors="coerce")
    disp_abs = pd.to_numeric(df.get("Disponiveis"), errors="coerce").fillna(0)
    rod = df["Rodando"] if "Rodando" in df.columns else pd.Series(False, index=df.index)
    exp = float(thr.get("peso_expoente", 0.6))
    rf = float(thr.get("peso_ramp_frac", 0.4))
    rmin = int(thr.get("peso_ramp_min", 3))
    cb = float(thr.get("conv_baixa", 1.0))

    for curva, g in df.groupby(df["Curva"].fillna("")):
        idx = [i for i in g.index
               if pd.notna(ref.loc[i]) and ref.loc[i] > 0 and bool(rod.loc[i])
               and (pd.isna(disp.loc[i]) or disp.loc[i] >= 3)]
        if len(idx) < 2:
            continue
        budget = float(ref.loc[idx].sum())
        teto = int(round(ref.loc[idx].max() * 1.2))
        vol_med = float(pd.Series([max(float(disp_abs.loc[i]), 0.0)
                                   for i in idx]).median()) or 1.0
        merit = {}
        for i in idx:
            cv = float(conv.loc[i]) if pd.notna(conv.loc[i]) else 0.0
            cvc = max(cv, 0.1) ** exp
            vf = min(1.5, max(0.7, (max(float(disp_abs.loc[i]), 1.0) / vol_med) ** 0.35))
            merit[i] = cvc * vf
        soma = sum(merit.values()) or 1.0
        for i in idx:
            alvo = int(round(min(max(budget * merit[i] / soma, 1), teto)))
            atual = int(ref.loc[i])
            step = max(rmin, int(round(atual * rf)))
            alvo = min(alvo, atual + step)
            alvo = max(alvo, atual - step)
            cvv = conv.loc[i]
            if pd.notna(cvv) and float(cvv) < cb and alvo > atual:
                alvo = atual
            out.at[i] = alvo
    return out


def _reconciliar_coerencia(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Peso Sugerido" not in df.columns:
        return df
    ref = pd.to_numeric(df.get("Peso Config"), errors="coerce")
    ref = ref.fillna(pd.to_numeric(df.get("Peso Disc"), errors="coerce"))
    sug = pd.to_numeric(df["Peso Sugerido"], errors="coerce")
    for i in df.index:
        c = df.at[i, "Coerencia"]
        if c in (None, "SEM_DADO", "OCIOSO"):
            continue
        r, s = ref.loc[i], sug.loc[i]
        if pd.isna(r) or pd.isna(s):
            continue
        r, s = float(r), float(s)
        tol = max(1.0, r * 0.1)
        if s > r + tol:
            df.at[i, "Coerencia"] = "SUBIR"
        elif s < r - tol:
            df.at[i, "Coerencia"] = "BAIXAR"
        else:
            df.at[i, "Coerencia"] = "OK"
    return df


def resumo_kpis(df_camp: pd.DataFrame) -> dict:
    if df_camp is None or df_camp.empty:
        return {"ligacoes": 0, "cadastradas": 0, "confirmadas": 0, "canceladas": 0,
                "conv": 0.0, "campanhas": 0, "rodando": 0, "criticas": 0,
                "oportunidades": 0}
    lig = int(df_camp["Ligacoes"].sum())
    cad = int(df_camp["Cadastradas"].sum())
    abord = int(df_camp["Abordagens"].sum())
    return {
        "ligacoes": lig, "cadastradas": cad,
        "confirmadas": int(df_camp["Confirmadas"].sum()),
        "canceladas": int(df_camp["Canceladas"].sum()),
        "conv": (100.0 * cad / abord) if abord > 0 else 0.0,
        "campanhas": int(len(df_camp)),
        "rodando": int(df_camp["Rodando"].sum()),
        "criticas": int((df_camp["Status"] == "Critico").sum()),
        "oportunidades": int((df_camp["Status"] == "Oportunidade").sum()),
    }


def operadores(curva_abc: pd.DataFrame, tmo: pd.DataFrame) -> pd.DataFrame:
    """Junta Curva ABC (curva + confirmadas) com TMO (ligacoes/cadastradas)."""
    if tmo is None or tmo.empty:
        return pd.DataFrame()
    t = tmo.copy()
    for c in ("Ligações", "Propostas Cadastradas", "Propostas Confirmadas"):
        if c in t.columns:
            t[c] = t[c].map(_num)
    t = t.rename(columns={"Matrícula do Usuário": "Matricula",
                          "Nome do Usuário": "Nome", "Ligações": "Ligacoes",
                          "Propostas Cadastradas": "Cadastradas",
                          "Propostas Confirmadas": "Confirmadas"})
    cols = ["Matricula", "Nome", "Ligacoes", "Cadastradas", "Confirmadas"]
    t = t[[c for c in cols if c in t.columns]]
    if curva_abc is not None and not curva_abc.empty:
        a = curva_abc.rename(columns={"Matrícula": "Matricula", "Usuário": "Nome",
                                      "Curva": "Curva",
                                      "Qtd. Dias Trabalhados": "Dias",
                                      "Supervisor": "Supervisor"})
        keep = [c for c in ["Matricula", "Curva", "Dias", "Supervisor"] if c in a.columns]
        t = t.merge(a[keep], on="Matricula", how="left")
    if "Dias" in t.columns:
        t["Dias"] = t["Dias"].map(_num)
    return t
