"""Painel NEO ENERGIA — operacao (fonte: Portal Ayty CRM, sem API)."""
from __future__ import annotations

import hmac
import os
import re
from datetime import timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Prime Performance", page_icon="⚡", layout="wide")

# --- ponte secrets -> env (para o portal.py ler AYTY_PORTAL_* no cloud) ---
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
        elif hasattr(_v, "items"):
            for _kk, _vv in _v.items():
                if isinstance(_vv, str) and re.match(r"^[A-Z][A-Z0-9_]*$", _kk):
                    os.environ.setdefault(_kk, _vv)
except Exception:
    pass

import portal as P          # noqa: E402
import engine as E          # noqa: E402
import treino               # noqa: E402
import calibracao as calib  # noqa: E402
from config import PROJETO, THRESHOLDS, now_br, today_br  # noqa: E402


# --------------------------------------------------------------------------- #
# Login opcional do painel (senha unica via secret/env NEO_PANEL_SENHA)
# --------------------------------------------------------------------------- #
def _require_login():
    senha = os.environ.get("NEO_PANEL_SENHA", "")
    if not senha:
        return  # sem senha configurada -> painel aberto
    if st.session_state.get("neo_auth"):
        return
    st.title("⚡ Prime Performance")
    with st.form("login"):
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar") and hmac.compare_digest(p, senha):
            st.session_state["neo_auth"] = True
            st.rerun()
    if not st.session_state.get("neo_auth"):
        st.stop()


_require_login()


# --------------------------------------------------------------------------- #
# Carga de dados (cache 15 min)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=900, show_spinner="Consultando o portal…")
def carregar(di, dfim):
    pa = P.PortalAyty().login()
    g = pa.menu(P.PROJETOS_PORTAL[PROJETO])
    pid = P.PROJETOS_PORTAL[PROJETO]

    def rel(menu):
        try:
            return pa.fetch_relatorio(pid, menu, di, dfim, guids=g)
        except Exception:
            return pd.DataFrame()

    perf = rel(P.RELATORIOS[pid]["performance_operacao"])
    abc = rel(P.RELATORIOS[pid]["curva_abc_usuario"])
    tmo = rel(P.RELATORIOS[pid]["tmo_operador"])
    try:
        disc = pa.estatisticas_discador(PROJETO, detalhado=True)
    except Exception:
        disc = pd.DataFrame()
    try:
        cfg = pa.config_campanha_grupo(PROJETO)
    except Exception:
        cfg = pd.DataFrame()
    return perf, disc, cfg, abc, tmo


@st.cache_data(ttl=120, show_spinner=False)
def _carregar_treino():
    return treino.carregar()


@st.cache_data(ttl=60, show_spinner=False)
def _status_treino():
    try:
        return treino.status()
    except Exception as e:
        return (False, f"nao consegui checar o treino ({e}).")


@st.cache_data(ttl=300, show_spinner=False)
def _cal_persist():
    try:
        return treino.carregar_calibracao()
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Helpers de estilo (sem matplotlib)
# --------------------------------------------------------------------------- #
def _rg(t: float) -> str:
    t = max(0.0, min(1.0, t))
    r = int(220 * (1 - t) + 40 * t)
    g = int(60 * (1 - t) + 200 * t)
    return f"rgba({r},{g},80,.28)"


def grad_col(s: pd.Series):
    v = pd.to_numeric(s, errors="coerce")
    lo, hi = v.min(), v.max()
    if pd.isna(lo) or hi == lo:
        return ["" for _ in s]
    return [f"background-color:{_rg((x - lo) / (hi - lo))}" if pd.notna(x) else ""
            for x in v]


STATUS_COLOR = {"Critico": "#ff4b5c", "Atencao": "#ffb020",
                "Saudavel": "#22c55e", "Oportunidade": "#38bdf8"}
COER_LABEL = {"SUBIR": "⬆️ Subir", "BAIXAR": "⬇️ Baixar", "OK": "✓ Coerente",
              "OCIOSO": "😴 Ocioso", "SEM_DADO": "—"}


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("⚡ NEO — Controles")
periodo = st.sidebar.radio("Periodo", ["Hoje", "Ontem", "Ultimos 7 dias", "Personalizado"])
if periodo == "Hoje":
    dt_ini = dt_fim = today_br()
elif periodo == "Ontem":
    dt_ini = dt_fim = today_br() - timedelta(days=1)
elif periodo == "Ultimos 7 dias":
    dt_fim = today_br(); dt_ini = dt_fim - timedelta(days=6)
else:
    dt_ini = st.sidebar.date_input("Inicio", today_br() - timedelta(days=6))
    dt_fim = st.sidebar.date_input("Fim", today_br())

st.sidebar.markdown("---")
with st.sidebar.expander("🎚️ Limiares", expanded=False):
    thr = dict(THRESHOLDS)
    thr["min_ligacoes"] = st.number_input("Min. ligacoes", 0, 5000, THRESHOLDS["min_ligacoes"], 10)
    thr["conv_baixa"] = st.number_input("Conversao baixa (%)", 0.0, 100.0, THRESHOLDS["conv_baixa"], 0.5)
    thr["conv_alta"] = st.number_input("Conversao alta (%)", 0.0, 100.0, THRESHOLDS["conv_alta"], 0.5)

# expoente calibrado (auto) sobrescreve o default, se houver
_calp = _cal_persist()
thr["peso_expoente"] = float(_calp.get("peso_expoente", THRESHOLDS["peso_expoente"]))

if st.sidebar.button("🔄 Atualizar agora", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
if os.environ.get("NEO_PANEL_SENHA") and st.session_state.get("neo_auth"):
    if st.sidebar.button("🚪 Sair", use_container_width=True):
        st.session_state.pop("neo_auth", None)
        st.rerun()
st.sidebar.caption("Fonte: Portal Ayty CRM (NEO ENERGIA)")


# --------------------------------------------------------------------------- #
# Corpo
# --------------------------------------------------------------------------- #
st.title("Prime Performance ⚡")
st.caption(f"Atualizado {now_br():%d/%m/%Y %H:%M} · periodo {dt_ini:%d/%m} a {dt_fim:%d/%m}")

if not os.environ.get("AYTY_PORTAL_SENHA"):
    st.warning("Configure AYTY_PORTAL_USER e AYTY_PORTAL_SENHA (secrets) para "
               "conectar ao portal.")
    st.stop()

try:
    perf, disc, cfg, abc, tmo = carregar(dt_ini, dt_fim)
except Exception as e:
    st.error(f"Falha ao consultar o portal: {e}")
    st.stop()

df_camp, acoes = E.analisar(perf, disc, cfg, thr)
if df_camp.empty:
    st.info("Sem campanhas com dados no periodo.")
    st.stop()
kpi = E.resumo_kpis(df_camp)

_view = st.radio("Visao", ["📊 Campanhas", "🧑‍💼 Operadores"], horizontal=True,
                 label_visibility="collapsed")

# =========================== OPERADORES ==================================== #
if _view == "🧑‍💼 Operadores":
    st.subheader("Operadores — producao e curva 🧑‍💼")
    op = E.operadores(abc, tmo)
    if op.empty:
        st.info("Sem dados de operadores no periodo.")
        st.stop()
    _min = st.slider("Min. ligacoes p/ ranquear", 0, 2000, 100, 50)
    v = op[op["Ligacoes"].fillna(0) >= _min].copy()
    v["Conv/Lig %"] = (100.0 * v["Cadastradas"] / v["Ligacoes"].where(v["Ligacoes"] > 0)).round(1)
    v = v.sort_values(["Cadastradas", "Conv/Lig %"], ascending=False).reset_index(drop=True)
    n = len(v)
    v["Curva sugerida"] = ["A" if i < n / 3 else "B" if i < 2 * n / 3 else "C"
                           for i in range(n)]
    v.insert(0, "#", range(1, n + 1))
    c1, c2, c3 = st.columns(3)
    c1.metric("Operadores", n)
    c2.metric("Cadastradas (total)", int(v["Cadastradas"].sum()))
    c3.metric("Media cadastr./op", f"{v['Cadastradas'].mean():.1f}")
    cols = ["#", "Nome", "Supervisor", "Curva", "Curva sugerida", "Ligacoes",
            "Cadastradas", "Conv/Lig %", "Dias"]
    show = v[[c for c in cols if c in v.columns]]
    sty = show.style
    for gc in ["Cadastradas", "Conv/Lig %"]:
        if gc in show.columns:
            sty = sty.apply(grad_col, subset=[gc], axis=0)
    st.dataframe(sty, use_container_width=True, hide_index=True, height=520)
    st.download_button("⬇️ Exportar (CSV)",
                       show.to_csv(index=False).encode("utf-8-sig"),
                       f"operadores_neo_{dt_ini:%Y%m%d}.csv", "text/csv")
    st.caption("Curva atual = Curva ABC do portal (produção). Curva sugerida = "
               "tercos por cadastradas/conversão no periodo.")
    st.stop()

# =========================== CAMPANHAS ===================================== #
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📞 Ligacoes", f"{kpi['ligacoes']:,}".replace(",", "."))
c2.metric("📝 Cadastradas", f"{kpi['cadastradas']:,}".replace(",", "."))
c3.metric("🎯 Conversao", f"{kpi['conv']:.1f}%")
c4.metric("⚙️ Campanhas ativas", kpi["rodando"])
c5.metric("🚀 Oportunidades", kpi["oportunidades"])

if acoes:
    st.subheader("Acoes recomendadas 🧠")
    for a in acoes[:8]:
        cor = {"CRITICO": "#ff4b5c", "ATENCAO": "#ffb020",
               "OPORTUNIDADE": "#22c55e"}.get(a["Severidade"], "#8b95a7")
        st.markdown(
            f"<div style='border-left:4px solid {cor};padding:.3rem .7rem;"
            f"margin:.2rem 0;background:rgba(255,255,255,.03)'>"
            f"<b style='color:{cor}'>{a['Severidade']}</b> · {a['Titulo']} — "
            f"<span style='opacity:.8'>{a['Campanha']}</span><br>"
            f"<small style='opacity:.7'>{a['Detalhe']}</small></div>",
            unsafe_allow_html=True)

st.subheader("Diagnostico por campanha 📋")
diag = df_camp.copy()
diag["Coerencia"] = diag["Coerencia"].map(lambda c: COER_LABEL.get(c, c))
cols = ["Codigo", "Campanha", "Curva", "Peso Config", "Peso Disc", "Peso Sugerido",
        "Coerencia", "Ligacoes", "% Abordagem", "Cadastradas", "% Conversao",
        "Disponivel %", "Hit Rate %", "Status"]
diag = diag[[c for c in cols if c in diag.columns]]
sty = diag.style
for gc in ["% Conversao", "Cadastradas", "Disponivel %", "Hit Rate %"]:
    if gc in diag.columns:
        sty = sty.apply(grad_col, subset=[gc], axis=0)
sty = sty.map(lambda v: f"color:{STATUS_COLOR.get(v, '')};font-weight:700"
              if v in STATUS_COLOR else "", subset=["Status"])
st.dataframe(sty, use_container_width=True, hide_index=True, height=430)
st.download_button("⬇️ Exportar diagnostico (CSV)",
                   diag.to_csv(index=False).encode("utf-8-sig"),
                   f"campanhas_neo_{dt_ini:%Y%m%d}.csv", "text/csv")

if disc is not None and not disc.empty:
    with st.expander("🎧 Visao do discador (base e contactabilidade)"):
        dd = E.normalizar_discador(disc)
        st.dataframe(dd, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# Treinamento do analista + auto-calibracao (Google Sheets)
# --------------------------------------------------------------------------- #
st.markdown("---")
st.subheader("Treinamento do analista (pesos ideais) 🎓")
_ok_tr, _msg_tr = _status_treino()
if not _ok_tr:
    st.info(f"⚙️ Treino indisponivel — {_msg_tr}\n\nConfigure `TREINO_SHEET_ID` e "
            "`GCP_SERVICE_ACCOUNT_JSON` nos secrets (planilha PROPRIA do NEO).")
else:
    base_tr = df_camp[df_camp["Peso Sugerido"].notna()].copy()
    if base_tr.empty:
        st.caption("Sem campanhas com Peso Sugerido para avaliar.")
    else:
        hist = _carregar_treino()
        prev = {}
        if not hist.empty and {"codigo", "peso_ideal"} <= set(hist.columns):
            h = hist.copy()
            if "data" in h.columns:
                h = h.sort_values("data")
            h = h.groupby("codigo").tail(1)
            prev = dict(zip(h["codigo"].astype(str),
                            pd.to_numeric(h["peso_ideal"], errors="coerce")))
        ed = base_tr[["Codigo", "Campanha", "Curva", "Peso Config", "Peso Disc",
                      "Peso Sugerido"]].copy()
        ed["Peso Ideal"] = ed.apply(
            lambda r: prev.get(str(int(r["Codigo"])), r["Peso Sugerido"]), axis=1)
        edited = st.data_editor(
            ed, use_container_width=True, hide_index=True, height=320,
            key="editor_treino_neo",
            column_config={
                "Codigo": st.column_config.NumberColumn(disabled=True),
                "Campanha": st.column_config.TextColumn(disabled=True),
                "Curva": st.column_config.TextColumn(disabled=True),
                "Peso Config": st.column_config.NumberColumn(disabled=True),
                "Peso Disc": st.column_config.NumberColumn(disabled=True),
                "Peso Sugerido": st.column_config.NumberColumn(disabled=True),
                "Peso Ideal": st.column_config.NumberColumn(
                    "Peso Ideal (você)", min_value=0, max_value=200, step=1),
            })
        if st.button("💾 Salvar avaliacao", use_container_width=True):
            agora = now_br()
            rows = []
            for _, r in edited.iterrows():
                cod = int(r["Codigo"])
                src = base_tr[base_tr["Codigo"] == cod].iloc[0]
                rows.append({
                    "data": agora.strftime("%Y-%m-%d"),
                    "timestamp": agora.strftime("%H:%M:%S"),
                    "avaliador": st.session_state.get("neo_auth") and "painel" or "local",
                    "codigo": cod, "campanha": src.get("Campanha"),
                    "curva": src.get("Curva") or "",
                    "peso_config": src.get("Peso Config"),
                    "peso_disc": src.get("Peso Disc"),
                    "peso_sugerido": src.get("Peso Sugerido"),
                    "peso_ideal": r["Peso Ideal"],
                    "conv": src.get("% Conversao"),
                    "disp_abs": src.get("Disponiveis"),
                    "disp_pct": src.get("Disponivel %"),
                    "rodando": bool(src.get("Rodando")),
                    "obs": "",
                })
            n = treino.salvar(rows)
            if n:
                _carregar_treino.clear()
                st.success(f"✅ {n} avaliacoes salvas.")
            else:
                st.error("Nao consegui salvar — verifique credenciais/planilha.")

        # ---- Auto-calibracao ----
        with st.expander("🤖 Auto-calibracao (aprende com as avaliacoes)"):
            _minav = st.number_input("Minimo de avaliacoes", 10, 500, 30, 10)
            if st.button("🤖 Analisar e sugerir", use_container_width=True):
                st.session_state["_cal_res_neo"] = calib.calibrar(
                    _carregar_treino(), int(_minav),
                    float(thr.get("peso_expoente", 0.6)))
            _res = st.session_state.get("_cal_res_neo")
            if _res:
                if not _res.get("ok"):
                    st.info(_res.get("msg"))
                else:
                    q1, q2, q3 = st.columns(3)
                    q1.metric("Erro atual (MAE)", f"{_res['mae_antes']:.1f}")
                    q2.metric("Erro calibrado", f"{_res['mae_depois']:.1f}",
                              f"-{_res['melhora_pct']:.0f}%")
                    q3.metric("Avaliacoes", f"{_res['n']} ({_res['pares']} pares)")
                    st.markdown(f"**Expoente:** {_res['expoente_atual']:.2f} → "
                                f"**{_res['peso_expoente']:.2f}**")
                    if not _res.get("mudou"):
                        st.success("A calibracao atual ja e a melhor. Nada a mudar.")
                    elif st.button("✅ Aplicar e salvar", use_container_width=True):
                        okc = treino.salvar_calibracao({
                            "timestamp": now_br().strftime("%Y-%m-%d %H:%M:%S"),
                            "avaliador": "painel",
                            "peso_expoente": _res["peso_expoente"],
                            "mae_antes": _res["mae_antes"],
                            "mae_depois": _res["mae_depois"],
                            "n_aval": _res["n"],
                        })
                        if okc:
                            _cal_persist.clear()
                            st.session_state.pop("_cal_res_neo", None)
                            st.success("✅ Calibracao aplicada.")
                            st.rerun()
                        else:
                            st.error("Nao consegui salvar a calibracao.")
