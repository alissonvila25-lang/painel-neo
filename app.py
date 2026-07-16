"""Painel NEO ENERGIA — operacao (fonte: Portal Ayty CRM, sem API)."""
from __future__ import annotations

import hmac
import os
import re
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Prime Performance", page_icon="⚡", layout="wide")

# --- tema escuro + componentes (cards de KPI, barras de secao, tabelas) ---
st.markdown(
    """
    <style>
      .stApp { background: #0e1117; }
      .block-container { padding-top: 1.2rem; }
      h1, h2, h3 { color: #f5f7fa; }
      h1 { font-weight:800; letter-spacing:.3px; }
      .kpi {
        position:relative; overflow:hidden;
        background: linear-gradient(160deg,#1b2130,#12161f);
        border: 1px solid #262d3d; border-radius: 16px; padding: 16px 18px 0 18px;
        box-shadow: 0 6px 20px rgba(0,0,0,.38); height:100%;
      }
      .kpi .row { display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }
      .kpi .value { font-size:1.85rem; font-weight:800; line-height:1.05; }
      .kpi .label { color:#8b95a7; font-size:.72rem; text-transform:uppercase;
                    letter-spacing:.6px; margin-top:5px; }
      .kpi .icon { font-size:1.5rem; line-height:1; opacity:.9;
                   filter:drop-shadow(0 2px 6px rgba(0,0,0,.4)); }
      .kpi .foot { margin:14px -18px 0 -18px; padding:8px 18px; font-size:.74rem;
                   font-weight:600; display:flex; justify-content:space-between;
                   align-items:center; }
      .kpi .foot .arrow { opacity:.85; font-size:.9rem; }
      .card { border-radius:14px; padding:14px 16px; margin-bottom:10px;
        border-left:5px solid #444; background:#161b26; }
      .card .t { font-weight:700; font-size:1rem; color:#fff; }
      .card .m { color:#c3cad6; font-size:.86rem; margin-top:4px; }
      .crit  { border-left-color:#ff4b5c; background:#241419; }
      .aten  { border-left-color:#ffb020; background:#241f14; }
      .opor  { border-left-color:#22c55e; background:#122417; }
      .info  { border-left-color:#3b82f6; background:#121a24; }
      .curvapill { display:inline-block; margin-left:6px; padding:1px 9px;
        border-radius:999px; font-size:.68rem; font-weight:700; color:#c7d2fe;
        background:rgba(129,140,248,.15); border:1px solid rgba(129,140,248,.35);
        vertical-align:middle; }
      h2, h3, h4, h5 { position:relative; padding-left:20px !important; }
      h2::before, h3::before, h4::before, h5::before {
        content:""; position:absolute; left:0; top:.2em; bottom:.2em; width:4px;
        border-radius:3px; background:linear-gradient(180deg,#38bdf8,#818cf8); }
      hr { border:none; border-top:1px solid #232a38; margin:1.15rem 0; }
      .stDownloadButton button, .stButton button {
        border-radius:10px; border:1px solid #2f3a4d; background:#1b2130;
        color:#dbe3f0; font-weight:600; transition:.15s ease; }
      .stDownloadButton button:hover, .stButton button:hover {
        border-color:#38bdf8; color:#fff; box-shadow:0 0 0 2px rgba(56,189,248,.15); }
      [data-testid="stDataFrame"] { border-radius:12px; overflow:hidden;
        border:1px solid #232a38; }
      [data-testid="stSidebar"] { background:#0b0e14; border-right:1px solid #1c2230; }
    </style>
    """,
    unsafe_allow_html=True,
)

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
def _rg(t: float):
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        r, g, b = 255, int(255 * (t / 0.5)), 60
    else:
        r, g, b = int(255 * (1 - (t - 0.5) / 0.5)), 200, 70
    return r, g, b


def grad_col(s):
    vals = pd.to_numeric(s, errors="coerce")
    lo, hi = vals.min(), vals.max()
    rng = (hi - lo) if (pd.notna(hi) and pd.notna(lo) and hi != lo) else 0
    out = []
    for v in vals:
        if pd.isna(v):
            out.append("")
            continue
        t = 0.5 if rng == 0 else (float(v) - float(lo)) / float(rng)
        r, g, b = _rg(t)
        out.append(f"background-color: rgba({r},{g},{b},0.28); font-weight:600")
    return out


def fmt_tabela(styled, df):
    """'%' (1 casa) nas porcentagens; inteiros sem '.0'; 1 casa so quando ha
    decimal; texto intacto; NA vira travessao."""
    fmt = {}
    for c in df.columns:
        if "%" in str(c):
            fmt[c] = "{:.1f}%"
            continue
        col = pd.to_numeric(df[c], errors="coerce")
        vals = col.dropna()
        if vals.empty:
            continue
        fmt[c] = "{:.0f}" if (vals == vals.round(0)).all() else "{:.1f}"
    return styled.format(fmt, na_rep="\u2014")


def kpi_card(col, label, value, sub="", icon="", accent="#3b82f6"):
    col.markdown(
        f"<div class='kpi'><div class='row'>"
        f"<div><div class='value' style='color:{accent}'>{value}</div>"
        f"<div class='label'>{label}</div></div>"
        f"<div class='icon'>{icon}</div></div>"
        f"<div class='foot' style=\"background:linear-gradient(90deg,{accent}26,"
        f"{accent}0d);border-top:1px solid {accent}40;color:{accent}\">"
        f"<span>{sub or ''}</span><span class='arrow'>↗</span></div></div>",
        unsafe_allow_html=True)


STATUS_COLOR = {"Critico": "#ff4b5c", "Atencao": "#ffb020",
                "Saudavel": "#3b82f6", "Oportunidade": "#22c55e"}
COER_LABEL = {"SUBIR": "🔺 Subir peso", "BAIXAR": "🔻 Baixar peso",
              "OK": "✅ Coerente", "OCIOSO": "⏸️ Ocioso", "SEM_DADO": "—"}
COER_COLOR = {"SUBIR": "#3b82f6", "BAIXAR": "#ff4b5c", "OK": "#22c55e",
              "OCIOSO": "#ffb020", "SEM_DADO": "#64748b"}


def _fmt(v):
    return f"{int(v):,}".replace(",", ".")


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("⚡ Prime — Controles")
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
    v["Conv/Lig %"] = (100.0 * v["Cadastradas"]
                       / v["Ligacoes"].where(v["Ligacoes"] > 0)).round(1)
    v = v.sort_values(["Cadastradas", "Conv/Lig %"], ascending=False).reset_index(drop=True)
    n = len(v)
    if "Curva" not in v.columns:
        v["Curva"] = ""
    v["Curva"] = v["Curva"].fillna("").astype(str).str.upper().str.strip()
    v["Curva sugerida"] = ["A" if i < n / 3 else "B" if i < 2 * n / 3 else "C"
                           for i in range(n)]
    _ordm = {"A": 1, "B": 2, "C": 3, "D": 4, "": 9}
    v["Ajuste"] = v.apply(
        lambda r: ("⬆️ promover" if _ordm.get(r["Curva sugerida"], 9) < _ordm.get(r["Curva"], 9)
                   else "⬇️ rebaixar" if _ordm.get(r["Curva sugerida"], 9) > _ordm.get(r["Curva"], 9)
                   else "✓ ok"), axis=1)
    v.insert(0, "#", range(1, n + 1))

    _mis = int((v["Curva sugerida"] != v["Curva"]).sum())
    m1, m2, m3 = st.columns(3)
    kpi_card(m1, "Operadores", f"{n}", f"min {_min} ligacoes", "🧑‍💼", "#8b5cf6")
    kpi_card(m2, "Cadastradas (total)", _fmt(int(v["Cadastradas"].sum())),
             "no periodo", "📝", "#22c55e")
    kpi_card(m3, "Media cadastr./op", f"{v['Cadastradas'].mean():.1f}",
             f"{_mis} em curva diferente", "📊", "#38bdf8")
    st.markdown("")

    def _cor_aj(x):
        return ("color:#22c55e;font-weight:700" if "promover" in str(x)
                else "color:#ff4b5c;font-weight:700" if "rebaixar" in str(x)
                else "color:#8b95a7")

    cols = ["#", "Nome", "Supervisor", "Curva", "Curva sugerida", "Ajuste",
            "Ligacoes", "Cadastradas", "Conv/Lig %", "Dias"]
    show = v[[c for c in cols if c in v.columns]]
    sty = show.style.map(_cor_aj, subset=["Ajuste"])
    for gc in ["Cadastradas", "Conv/Lig %"]:
        if gc in show.columns:
            sty = sty.apply(grad_col, subset=[gc], axis=0)
    sty = fmt_tabela(sty, show)
    st.dataframe(sty, use_container_width=True, hide_index=True, height=520)
    st.download_button("⬇️ Exportar (CSV)",
                       show.to_csv(index=False).encode("utf-8-sig"),
                       f"operadores_neo_{dt_ini:%Y%m%d}.csv", "text/csv")
    st.caption("Curva atual = Curva ABC do portal (produção). Curva sugerida = "
               "terços por cadastradas/conversão no período (melhores → A).")
    st.stop()

# =========================== CAMPANHAS ===================================== #
k1, k2, k3, k4, k5, k6 = st.columns(6)
kpi_card(k1, "Ligacoes", _fmt(kpi["ligacoes"]), "discadas no periodo", "📞", "#3b82f6")
kpi_card(k2, "Propostas Cadastradas", _fmt(kpi["cadastradas"]), "no periodo", "📝", "#22c55e")
kpi_card(k3, "Conversao", f"{kpi['conv']:.1f}%", "cadastradas / abordagens", "🎯", "#38bdf8")
kpi_card(k4, "Campanhas rodando", f"{kpi['rodando']}", "com discagem", "⚙️", "#8b5cf6")
kpi_card(k5, "Criticas", f"{kpi['criticas']}", "acao urgente", "🚨", "#ff4b5c")
kpi_card(k6, "Oportunidades", f"{kpi['oportunidades']}", "escalar peso", "🚀", "#22c55e")

st.markdown("")

# --- Saude da base (discador) ---
_tot_base = float(df_camp["Total da Base"].sum()) if "Total da Base" in df_camp else 0.0
_tot_disp = float(df_camp["Disponiveis"].sum()) if "Disponiveis" in df_camp else 0.0
_pct_disp = (100.0 * _tot_disp / _tot_base) if _tot_base else 0.0
if _tot_base:
    st.markdown("##### Saude da base (discador) 🗃️")
    b1, b2, b3 = st.columns(3)
    kpi_card(b1, "Base total", _fmt(_tot_base), "nomes na fila", "🗃️", "#64748b")
    kpi_card(b2, "Disponiveis", _fmt(_tot_disp), f"{_pct_disp:.0f}% da base", "♻️", "#38bdf8")
    kpi_card(b3, "Consumida", f"{100 - _pct_disp:.0f}%", "ja trabalhada/bloqueada", "🔥", "#ffb020")
    st.markdown("")

if acoes:
    st.subheader("Acoes recomendadas 🧠")
    _cls = {"CRITICO": "crit", "ATENCAO": "aten", "OPORTUNIDADE": "opor", "INFO": "info"}
    for a in acoes[:8]:
        cur = (f"<span class='curvapill'>Curva {a['Curva']}</span>"
               if a.get("Curva") else "")
        st.markdown(
            f"<div class='card {_cls.get(a['Severidade'], 'info')}'>"
            f"<div class='t'>{a['Titulo']} — <span style='opacity:.8'>"
            f"{a['Campanha']}</span>{cur}</div>"
            f"<div class='m'>{a['Detalhe']}</div></div>",
            unsafe_allow_html=True)

st.subheader("Diagnostico por campanha 📋")
diag = df_camp.copy().sort_values("Codigo")
diag["Coerencia"] = diag["Coerencia"].map(lambda c: COER_LABEL.get(c, c))
cols = ["Codigo", "Campanha", "Curva", "Peso Config", "Peso Disc", "Peso Sugerido",
        "Coerencia", "Ligacoes", "% Abordagem", "Cadastradas", "% Conversao",
        "Disponivel %", "Hit Rate %", "Status"]
diag = diag[[c for c in cols if c in diag.columns]]
sty = diag.style
for gc in ["% Conversao", "Cadastradas", "% Abordagem", "Disponivel %", "Hit Rate %"]:
    if gc in diag.columns:
        sty = sty.apply(grad_col, subset=[gc], axis=0)
sty = sty.map(lambda v: f"color:{STATUS_COLOR.get(v, '')};font-weight:700"
              if v in STATUS_COLOR else "", subset=["Status"])
sty = fmt_tabela(sty, diag)
st.dataframe(sty, use_container_width=True, hide_index=True, height=430)
st.download_button("⬇️ Exportar diagnostico (CSV)",
                   diag.to_csv(index=False).encode("utf-8-sig"),
                   f"campanhas_neo_{dt_ini:%Y%m%d}.csv", "text/csv")

# --- Mapa de conversao x volume ---
_mapa = df_camp[df_camp["Ligacoes"] > 0].copy()
if not _mapa.empty and _mapa["% Conversao"].notna().any():
    st.subheader("Mapa de conversao × volume 🗺️")
    _mapa["% Conversao"] = pd.to_numeric(_mapa["% Conversao"], errors="coerce").fillna(0)
    fig = px.scatter(
        _mapa, x="Ligacoes", y="% Conversao", size="Cadastradas",
        color="Status", color_discrete_map=STATUS_COLOR,
        hover_name="Campanha", size_max=40,
        labels={"Ligacoes": "Ligacoes", "% Conversao": "Conversao %"})
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font_color="#c3cad6", height=420,
                      legend=dict(orientation="h", y=-0.2))
    fig.update_xaxes(gridcolor="#232a38"); fig.update_yaxes(gridcolor="#232a38")
    st.plotly_chart(fig, use_container_width=True)

if disc is not None and not disc.empty:
    st.subheader("Visao do discador 🎧")
    dd = E.normalizar_discador(disc)
    dcols = ["Codigo", "Peso Disc", "Hit Rate %", "Penetracao %", "Total da Base",
             "Disponiveis", "Livres", "Bloqueados"]
    dd = dd[[c for c in dcols if c in dd.columns]].sort_values(
        "Disponiveis", ascending=False) if not dd.empty else dd
    dsty = dd.style
    for gc in ["Hit Rate %", "Penetracao %", "Disponiveis"]:
        if gc in dd.columns:
            dsty = dsty.apply(grad_col, subset=[gc], axis=0)
    dsty = fmt_tabela(dsty, dd)
    st.dataframe(dsty, use_container_width=True, hide_index=True)


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
