"""Painel NEO ENERGIA — operacao (fonte: Portal Ayty CRM, sem API)."""
from __future__ import annotations

import hmac
import json
import os
import re
import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
      [data-testid="stForm"] { background:linear-gradient(160deg,#1b2130,#12161f);
        border:1px solid #262d3d; border-radius:16px; padding:18px 20px;
        box-shadow:0 10px 30px rgba(0,0,0,.4); }
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
import historico            # noqa: E402
from config import PROJETO, THRESHOLDS, now_br, today_br  # noqa: E402


# --------------------------------------------------------------------------- #
# Login do painel: multiusuario via [credentials] (usuario -> senha), ou senha
# unica via NEO_PANEL_SENHA (usuario 'admin'). Sem nada configurado -> aberto.
# --------------------------------------------------------------------------- #
def _load_credentials() -> dict:
    try:
        c = dict(st.secrets.get("credentials", {}))
        if c:
            return {str(k): str(v) for k, v in c.items()}
    except Exception:
        pass
    raw = os.environ.get("NEO_CREDENTIALS", "")
    if raw:
        try:
            return {str(k): str(v) for k, v in json.loads(raw).items()}
        except Exception:
            pass
    s = os.environ.get("NEO_PANEL_SENHA", "")
    return {"admin": s} if s else {}


def _require_login():
    creds = _load_credentials()
    if not creds:
        return  # sem credenciais -> painel aberto
    if st.session_state.get("auth_user"):
        return
    st.markdown("<div style='height:7vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.05, 1])
    with mid:
        st.markdown(
            "<div style='text-align:center;margin-bottom:2px'>"
            "<div style='font-size:2.8rem;line-height:1'>⚡</div>"
            "<div style='font-size:1.55rem;font-weight:800;letter-spacing:.3px;"
            "color:#f5f7fa'>Prime Performance</div>"
            "<div style='color:#8b95a7;font-size:.82rem;margin-top:2px'>"
            "Acesso restrito — entre com seu usuario</div></div>",
            unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Usuario", placeholder="usuario",
                              label_visibility="collapsed")
            p = st.text_input("Senha", type="password", placeholder="senha",
                              label_visibility="collapsed")
            ok = st.form_submit_button("Entrar", use_container_width=True)
        if ok:
            exp = creds.get(u.strip())
            if exp is not None and hmac.compare_digest(p, str(exp)):
                st.session_state["auth_user"] = u.strip()
                st.rerun()
            else:
                st.error("Usuario ou senha invalidos.")
    st.stop()


_require_login()


# --------------------------------------------------------------------------- #
# Carga de dados (cache 15 min). Cada relatorio roda em sua PROPRIA sessao do
# portal, em paralelo (o portal serializa requests da mesma sessao, entao 1
# sessao por job e o que realmente acelera).
# --------------------------------------------------------------------------- #
def _job(fn):
    """Abre uma sessao propria e executa fn(pa). DataFrame vazio em falha."""
    try:
        pa = P.PortalAyty().login()
        return fn(pa)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _carregar_cfg():
    """Config de campanha (peso/curva) — muda pouco, cache de 1h."""
    return _job(lambda pa: pa.config_campanha_grupo(PROJETO))


@st.cache_data(ttl=900, show_spinner="Consultando o portal…")
def carregar_campanhas(di, dfim):
    """Performance + Discador (paralelos) + Config (cache proprio de 1h)."""
    pid = P.PROJETOS_PORTAL[PROJETO]
    _r = P.RELATORIOS[pid]
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_perf = ex.submit(_job, lambda pa: pa.fetch_relatorio(
            pid, _r["performance_operacao"], di, dfim))
        f_disc = ex.submit(_job, lambda pa: pa.estatisticas_discador(
            PROJETO, detalhado=True))
        perf, disc = f_perf.result(), f_disc.result()
    cfg = _carregar_cfg()   # geralmente cache HIT (instantaneo)
    return perf, disc, cfg


@st.cache_data(ttl=900, show_spinner="Consultando operadores…")
def carregar_operadores_range(di, dfim):
    """Curva ABC + TMO por operador para um periodo proprio (aba Operadores)."""
    pid = P.PROJETOS_PORTAL[PROJETO]
    _r = P.RELATORIOS[pid]
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_abc = ex.submit(_job, lambda pa: pa.fetch_relatorio(
            pid, _r["curva_abc_usuario"], di, dfim))
        f_tmo = ex.submit(_job, lambda pa: pa.fetch_relatorio(
            pid, _r["tmo_operador"], di, dfim))
        return f_abc.result(), f_tmo.result()


@st.cache_data(ttl=120, show_spinner=False)
def _carregar_treino():
    return treino.carregar()


@st.cache_data(ttl=1800, show_spinner=False)
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


@st.cache_data(ttl=43200, show_spinner="Carregando historico (D-1)…")
def _hist_do_dia(d1):
    """Sincroniza ate D-1 e devolve o historico ja PREPARADO.

    Cacheado por data de D-1 (ttl 12h de seguranca) -> na pratica carrega uma
    unica vez por dia e fica em memoria; nao rele a planilha a cada interacao.
    """
    try:
        historico.atualizar_ate(d1, dias_janela=40, max_fetch=10)
    except Exception:
        pass
    try:
        return historico.preparar(treino.carregar_historico())
    except Exception:
        return pd.DataFrame()


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
    decimal; texto intacto; NA vira travessao. Tolerante a valores nao-numericos
    (nao quebra a renderizacao)."""
    def _mk(spec):
        def _f(x):
            try:
                return spec.format(x)
            except (ValueError, TypeError):
                return "—" if pd.isna(x) else str(x)
        return _f

    fmt = {}
    for c in df.columns:
        col = pd.to_numeric(df[c], errors="coerce")
        vals = col.dropna()
        if vals.empty:
            continue
        if "%" in str(c):
            fmt[c] = _mk("{:.1f}%")
            continue
        fmt[c] = _mk("{:.0f}" if (vals == vals.round(0)).all() else "{:.1f}")
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
if st.session_state.get("auth_user"):
    st.sidebar.caption(f"👤 {st.session_state['auth_user']}")
    if st.sidebar.button("🚪 Sair", use_container_width=True):
        st.session_state.pop("auth_user", None)
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

_view = st.radio("Visao", ["📊 Campanhas", "🧑‍💼 Operadores", "📈 Historico"],
                 horizontal=True, label_visibility="collapsed")

# =========================== HISTORICO ===================================== #
if _view == "📈 Historico":
    st.subheader("Analitico historico (D-1) 📈")
    _d1 = today_br() - timedelta(days=1)
    _ok_tr, _ = _status_treino()
    if not _ok_tr:
        st.info("Historico indisponivel — configure `TREINO_SHEET_ID` e "
                "`GCP_SERVICE_ACCOUNT_JSON` nos secrets.")
        st.stop()
    h = _hist_do_dia(_d1)

    cc = st.columns([3, 1, 1])
    cc[0].caption("Snapshot diario dos totais (Performance de Operacao). "
                  "Atualiza automaticamente olhando para D-1.")
    if cc[1].button("↻ Preencher 60 dias", use_container_width=True,
                    help="Busca no portal os dias faltantes (pode demorar)."):
        with st.spinner("Coletando historico do portal…"):
            _nn = historico.atualizar_ate(_d1, dias_janela=60, max_fetch=60)
        _hist_do_dia.clear()
        st.success(f"{_nn} dias adicionados ao historico.")
        st.rerun()
    if cc[2].button("🧹 Refazer", use_container_width=True,
                    help="Limpa e recoleta os ultimos 60 dias (corrige formatos)."):
        with st.spinner("Refazendo historico…"):
            treino.limpar_historico()
            _nn = historico.atualizar_ate(_d1, dias_janela=60, max_fetch=60)
        _hist_do_dia.clear()
        st.success(f"Historico refeito: {_nn} dias.")
        st.rerun()

    if h.empty:
        st.info("Sem historico ainda. Clique em **Preencher 60 dias** para iniciar.")
        st.stop()

    _hoje = today_br()
    _mes = h[(h["data"].dt.month == _hoje.month) & (h["data"].dt.year == _hoje.year)]
    cad_mes = float(_mes["cadastradas"].sum())
    conf_mes = float(_mes["confirmadas"].sum())
    canc_mes = float(_mes["canceladas"].sum())
    abord_mes = float(_mes["abordagens"].sum())
    conv_mes = (100.0 * cad_mes / abord_mes) if abord_mes else 0.0
    cancel_pct = (100.0 * canc_mes / cad_mes) if cad_mes else 0.0
    # vendas por operador por dia = total de vendas / total de operador-dia,
    # considerando SO os dias que tem contagem de operadores.
    if "operadores" in _mes.columns:
        _vd = _mes[_mes["operadores"].fillna(0) > 0]
        _opdias = float(_vd["operadores"].sum())
        _mvop = (float(_vd["cadastradas"].sum()) / _opdias) if _opdias > 0 else 0.0
    else:
        _mvop = 0.0
    _u = h.iloc[-1]
    _p = h.iloc[-2] if len(h) >= 2 else None
    _delta = (int(_u["cadastradas"] - _p["cadastradas"]) if _p is not None else None)

    g1, g2, g3, g4, g5 = st.columns(5)
    kpi_card(g1, "Cadastradas no mes", _fmt(cad_mes),
             f"{_mes['data'].dt.day.nunique()} dias com dado", "📝", "#22c55e")
    kpi_card(g2, "Conversao no mes", f"{conv_mes:.1f}%", "cadastradas / abordagens",
             "🎯", "#38bdf8")
    kpi_card(g3, "Cancelamento", f"{cancel_pct:.1f}%", "canceladas / cadastradas",
             "🚫", "#ffb020")
    kpi_card(g4, "Vendas/operador/dia", f"{_mvop:.1f}", "media do mes",
             "🧑‍💼", "#14b8a6")
    kpi_card(g5, f"Ultimo dia ({_u['data']:%d/%m})", _fmt(_u["cadastradas"]),
             (f"{_delta:+d} vs dia anterior" if _delta is not None else "cadastradas"),
             "📅", "#8b5cf6")
    st.markdown("")

    # meta + projecao
    mc1, mc2, mc3 = st.columns(3)
    meta = mc1.number_input("Meta mensal (cadastradas)", 0, 1_000_000, 0, 100)
    _dias_mes = calendar.monthrange(_hoje.year, _hoje.month)[1]
    _dias_dado = max(int(_mes["data"].dt.day.nunique()), 1)
    proj = cad_mes / _dias_dado * _dias_mes
    mc2.metric("Projecao do mes", _fmt(proj),
               f"media {cad_mes / _dias_dado:.0f}/dia")
    if meta > 0:
        mc3.metric("Meta atingida", f"{100 * cad_mes / meta:.0f}%",
                   f"projecao {100 * proj / meta:.0f}%")

    # evolucao diaria
    fig = go.Figure()
    fig.add_bar(x=h["data"], y=h["cadastradas"], name="Cadastradas",
                marker_color="#22c55e")
    fig.add_scatter(x=h["data"], y=h["conv_pct"], name="Conversao %",
                    yaxis="y2", mode="lines+markers", line=dict(color="#38bdf8"))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#c3cad6", height=380, margin=dict(t=30, b=10),
        legend=dict(orientation="h", y=1.12),
        yaxis=dict(title="Cadastradas", gridcolor="#232a38"),
        yaxis2=dict(title="Conversao %", overlaying="y", side="right",
                    showgrid=False))
    fig.update_xaxes(gridcolor="#232a38")
    st.plotly_chart(fig, use_container_width=True)

    # tabela historico
    show = h.sort_values("data", ascending=False).copy()
    show["data"] = show["data"].dt.strftime("%d/%m/%Y")
    show = show.rename(columns={
        "data": "Data", "ligacoes": "Ligacoes", "abordagens": "Abordagens",
        "cadastradas": "Cadastradas", "confirmadas": "Confirmadas",
        "canceladas": "Canceladas", "conv_pct": "Conversao %",
        "abord_pct": "Abordagem %", "campanhas": "Campanhas",
        "operadores": "Operadores", "vendas_op": "Vendas/op"})
    hsty = show.style
    for gc in ["Cadastradas", "Conversao %"]:
        if gc in show.columns:
            hsty = hsty.apply(grad_col, subset=[gc], axis=0)
    hsty = fmt_tabela(hsty, show)
    st.dataframe(hsty, use_container_width=True, hide_index=True, height=360)
    st.download_button("⬇️ Exportar historico (CSV)",
                       show.to_csv(index=False).encode("utf-8-sig"),
                       "historico_neo.csv", "text/csv")
    st.stop()

# =========================== OPERADORES ==================================== #
if _view == "🧑‍💼 Operadores":
    st.subheader("Operadores — producao 🧑‍💼")
    oc1, oc2, oc3 = st.columns([1.2, 1, 1])
    _modo_op = oc1.radio("Janela", ["Mes vigente", "Personalizado"],
                         key="op_range_modo", label_visibility="collapsed")
    if _modo_op == "Personalizado":
        _op_ini = oc2.date_input("De", today_br().replace(day=1), key="op_de")
        _op_fim = oc3.date_input("Ate", today_br(), key="op_ate")
    else:
        _op_ini = today_br().replace(day=1)
        _op_fim = today_br()
    if _op_ini > _op_fim:
        st.warning("A data inicial nao pode ser maior que a final.")
        st.stop()
    st.caption(f"Periodo analisado: {_op_ini:%d/%m/%Y} a {_op_fim:%d/%m/%Y}")
    _abc, _tmo = carregar_operadores_range(_op_ini, _op_fim)
    op = E.operadores(_abc, _tmo)
    if op.empty:
        st.info("Sem dados de operadores no periodo.")
        st.stop()
    _min = st.slider("Min. ligacoes p/ ranquear", 0, 2000, 100, 50)
    v = op[op["Ligacoes"].fillna(0) >= _min].copy()
    v["Conv/Lig %"] = (100.0 * v["Cadastradas"]
                       / v["Ligacoes"].where(v["Ligacoes"] > 0)).round(1)
    if "Abordagens" in v.columns:
        v["% Abordagem"] = (100.0 * v["Abordagens"]
                            / v["Ligacoes"].where(v["Ligacoes"] > 0)).round(1)
    if "Dias" in v.columns:
        v["Vendas/dia"] = (v["Cadastradas"]
                           / v["Dias"].where(v["Dias"] > 0)).round(2)
    v = v.sort_values(["Cadastradas", "Conv/Lig %"], ascending=False).reset_index(drop=True)
    n = len(v)
    v.insert(0, "#", range(1, n + 1))

    # sinal de queima de mailing (alto volume com conversao/abordagem baixas)
    _ligmed = float(v["Ligacoes"].median()) if n else 0.0
    _convmed = float(v["Conv/Lig %"].median(skipna=True)) if n else 0.0
    _abmed = (float(v["% Abordagem"].median(skipna=True))
              if "% Abordagem" in v.columns and v["% Abordagem"].notna().any() else 0.0)

    def _mailing(r):
        _alto = r["Ligacoes"] >= _ligmed
        _cv = 0.0 if pd.isna(r["Conv/Lig %"]) else float(r["Conv/Lig %"])
        _ab = float(r["% Abordagem"]) if ("% Abordagem" in r.index
                                          and pd.notna(r["% Abordagem"])) else None
        _ab_ruim = (_abmed > 0 and _ab is not None and _ab < 0.5 * _abmed)
        if _alto and (_cv < 0.5 * _convmed or _ab_ruim):
            return "🔥 queimando"
        if _alto and _cv < _convmed:
            return "⚠️ atencao"
        return "✓ ok"

    v["Mailing"] = v.apply(_mailing, axis=1)
    _queima = int((v["Mailing"] == "🔥 queimando").sum())

    m1, m2, m3, m4 = st.columns(4)
    kpi_card(m1, "Operadores", f"{n}", f"min {_min} ligacoes", "🧑‍💼", "#8b5cf6")
    kpi_card(m2, "Cadastradas (total)", _fmt(int(v["Cadastradas"].sum())),
             "no periodo", "📝", "#22c55e")
    _totdias = float(v["Dias"].sum()) if "Dias" in v.columns else 0.0
    _md = (float(v["Cadastradas"].sum()) / _totdias) if _totdias > 0 else 0.0
    kpi_card(m3, "Media vendas/op/dia", f"{_md:.1f}", "por dia trabalhado",
             "📊", "#38bdf8")
    kpi_card(m4, "Risco de queima", f"{_queima}", "operadores 🔥", "🔥", "#ff4b5c")
    st.markdown("")

    def _cor_mail(x):
        _s = str(x)
        if "🔥" in _s:
            return "background-color:rgba(255,75,92,.22);color:#ff4b5c;font-weight:700"
        if "⚠️" in _s:
            return "color:#ffb020;font-weight:700"
        return "color:#8b95a7"

    cols = ["#", "Nome", "Supervisor", "Ligacoes", "Abordagens", "% Abordagem",
            "Cadastradas", "Vendas/dia", "Conv/Lig %", "Mailing", "Dias"]
    show = v[[c for c in cols if c in v.columns]]
    sty = show.style.map(_cor_mail, subset=["Mailing"])
    for gc in ["Cadastradas", "Vendas/dia", "Conv/Lig %", "% Abordagem"]:
        if gc in show.columns:
            sty = sty.apply(grad_col, subset=[gc], axis=0)
    sty = fmt_tabela(sty, show)
    st.dataframe(sty, use_container_width=True, hide_index=True, height=520)
    st.download_button("⬇️ Exportar (CSV)",
                       show.to_csv(index=False).encode("utf-8-sig"),
                       f"operadores_neo_{_op_ini:%Y%m%d}_{_op_fim:%Y%m%d}.csv", "text/csv")
    st.caption("Vendas/dia = cadastradas ÷ dias. 🔥 = alto volume com conversao/"
               "abordagem bem abaixo da media (possivel queima de mailing). "
               "Abordagens estimadas via tempo do TMO.")
    st.stop()

# =========================== CAMPANHAS ===================================== #
try:
    perf, disc, cfg = carregar_campanhas(dt_ini, dt_fim)
except Exception as e:
    st.error(f"Falha ao consultar o portal: {e}")
    st.stop()
df_camp, acoes = E.analisar(perf, disc, cfg, thr)
if df_camp.empty:
    st.info("Sem campanhas com dados no periodo.")
    st.stop()
kpi = E.resumo_kpis(df_camp)

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

if disc is not None and not disc.empty:
    _dd = E.normalizar_discador(disc)
    if not _dd.empty:
        st.subheader("Visao do discador 🎧")
        _nomes = dict(zip(df_camp["Codigo"], df_camp["Campanha"]))
        _dd["Campanha"] = _dd["Codigo"].map(_nomes).fillna(_dd["Codigo"].astype(str))
        _dcols = ["Campanha", "Peso Disc", "Hit Rate %", "Penetracao %",
                  "Total da Base", "Disponiveis", "Livres", "Fin. Tentativa",
                  "Bloqueados"]
        _dd = _dd[[c for c in _dcols if c in _dd.columns]].sort_values(
            "Disponiveis", ascending=False)
        _dsty = _dd.style
        for _gc in ["Hit Rate %", "Penetracao %", "Disponiveis"]:
            if _gc in _dd.columns:
                _dsty = _dsty.apply(grad_col, subset=[_gc], axis=0)
        _dsty = fmt_tabela(_dsty, _dd)
        st.dataframe(_dsty, use_container_width=True, hide_index=True)

st.subheader("Diagnostico por campanha 📋")
diag = df_camp.copy().sort_values("Codigo").rename(columns={"Peso Disc": "Peso Atual"})
diag["Coerencia"] = diag["Coerencia"].map(lambda c: COER_LABEL.get(c, c))
cols = ["Codigo", "Campanha", "Curva", "Peso Atual", "Peso Sugerido",
        "Coerencia", "Ligacoes", "% Abordagem", "Cadastradas", "% Conversao",
        "Disponivel %", "Fin. Tentativa", "Hit Rate %", "Status"]
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
                    "avaliador": st.session_state.get("auth_user") or "local",
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
                _err = getattr(treino, "_ERRO_SALVAR", "")
                st.error("Nao consegui salvar — verifique credenciais/planilha."
                         + (f"\n\nDetalhe: {_err}" if _err else ""))

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
