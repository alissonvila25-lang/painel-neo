"""
analista_treino.py — Store de "treino" do analista no Google Sheets.

Guarda, por campanha/dia, o peso que o analista considera IDEAL versus o
peso sugerido pelo painel, junto das features (conversao, virgens %, volume
disponivel, curva). Serve de base para medir concordancia e, numa fase 2,
recalibrar os parametros da formula para imitar o julgamento humano.

Requer uma CONTA DE SERVICO Google com acesso de edicao a planilha:
- credenciais em st.secrets['gcp_service_account'] (tabela TOML) ou na env
  GCP_SERVICE_ACCOUNT_JSON (string JSON);
- ID da planilha em TREINO_SHEET_ID (secret/env) ou o default abaixo.

Degrada com elegancia: qualquer falta de credencial/lib -> disponivel()=False
e as funcoes retornam vazio, sem derrubar o painel.
"""
from __future__ import annotations

import json
import os

import pandas as pd

# Planilha DEDICADA do NEO (reusa a mesma conta de servico do outro painel).
# Pode ser sobrescrito por TREINO_SHEET_ID (secret/env).
_SHEET_ID_DEFAULT = "1WsG0HuAMwgoqANEMgTslEE-_0_NRFdS1BMjAYBc6-mI"
_ABA = "treino_neo"
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

COLS = [
    "data", "timestamp", "avaliador", "codigo", "campanha", "curva",
    "peso_config", "peso_disc", "peso_sugerido", "peso_ideal", "conv",
    "disp_abs", "disp_pct", "rodando", "obs",
]


def _sheet_id() -> str:
    return (_find_secret_str("TREINO_SHEET_ID") or "").strip() or _SHEET_ID_DEFAULT


def _find_secret_str(key: str) -> str:
    """Procura uma chave string nos Secrets: env, nivel superior e dentro de
    qualquer [secao] (robusto contra a ordem do TOML)."""
    v = os.environ.get(key)
    if v:
        return v
    try:
        import streamlit as st
        if key in st.secrets and isinstance(st.secrets[key], str):
            return st.secrets[key]
        for k in st.secrets:
            try:
                sub = st.secrets[k]
                if hasattr(sub, "keys") and key in sub and isinstance(sub[key], str):
                    return sub[key]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _sa_info_ex() -> tuple[dict | None, str]:
    """(credenciais|None, motivo) da conta de servico."""
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"]), "ok"
    except Exception:
        pass
    raw = _find_secret_str("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw), "ok"
        except Exception as e:
            return None, (
                "GCP_SERVICE_ACCOUNT_JSON encontrado, mas o JSON esta invalido "
                f"({e}). Use aspas triplas SIMPLES ''' e cole o conteudo do .json "
                "exatamente como esta (sem editar as quebras de linha).")
    return None, (
        "GCP_SERVICE_ACCOUNT_JSON nao encontrado nos Secrets. Confirme que "
        "SALVOU e que as linhas do treino ficaram ANTES de [credentials].")


def _sa_info() -> dict | None:
    """Credenciais da conta de servico (dict) ou None."""
    return _sa_info_ex()[0]


def diagnostico_chaves() -> str:
    """Descreve (sem expor valores) quais chaves existem nos Secrets e onde
    esta o GCP_SERVICE_ACCOUNT_JSON. So nomes de chave, nunca conteudo."""
    partes = []
    try:
        import streamlit as st
        topo = [str(k) for k in st.secrets]
        partes.append("no topo: " + (", ".join(topo) or "(vazio)"))
        loc = "nao encontrado"
        if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
            loc = "topo"
        else:
            for k in st.secrets:
                try:
                    sub = st.secrets[k]
                    if hasattr(sub, "keys") and "GCP_SERVICE_ACCOUNT_JSON" in sub:
                        loc = f"dentro de [{k}]"
                        break
                except Exception:
                    continue
        if os.environ.get("GCP_SERVICE_ACCOUNT_JSON"):
            loc += " (+ presente no ambiente)"
        partes.append("GCP_SERVICE_ACCOUNT_JSON: " + loc)
        partes.append("tabela [gcp_service_account]: "
                      + ("sim" if "gcp_service_account" in st.secrets else "nao"))
    except Exception as e:
        partes.append(f"sem acesso a st.secrets ({e})")
    return " · ".join(partes)


def _client():
    """Cliente gspread autorizado, ou None se indisponivel."""
    info = _sa_info()
    if not info:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        return gspread.authorize(creds)
    except Exception:
        return None


def _ws_named(aba: str, cols: list[str]):
    """Worksheet `aba` (cria com cabecalho `cols` se nao existir), ou None."""
    gc = _client()
    if gc is None:
        return None
    try:
        import gspread
        sh = gc.open_by_key(_sheet_id())
        try:
            return sh.worksheet(aba)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(aba, rows=2000, cols=max(len(cols), 1))
            ws.append_row(cols)
            return ws
    except Exception:
        return None


def _ws():
    """Worksheet 'treino' (cria com cabecalho se nao existir), ou None."""
    return _ws_named(_ABA, COLS)


def _garantir_cabecalho(ws, cols: list[str]) -> None:
    """Garante que a primeira linha contenha `cols`.

    Se a aba ja existe com um cabecalho mais curto (versao antiga) e este e
    prefixo do novo, estende o cabecalho preservando o alinhamento das colunas
    antigas. Nao reordena nada.
    """
    try:
        head = ws.row_values(1)
    except Exception:
        head = []
    if not head:
        ws.update(values=[cols], range_name="A1")
    elif len(head) < len(cols) and head == cols[:len(head)]:
        ws.update(values=[cols], range_name="A1")


def disponivel() -> bool:
    """True se da para autenticar e abrir a planilha."""
    return status()[0]


def status() -> tuple[bool, str]:
    """(ok, motivo) — diagnostica em qual etapa o treino falha."""
    info, motivo = _sa_info_ex()
    if not info:
        return False, motivo
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception as e:
        return False, f"bibliotecas ausentes (gspread/google-auth): {e}"
    try:
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        gc = gspread.authorize(creds)
    except Exception as e:
        return False, f"credenciais invalidas: {type(e).__name__}: {e}"
    try:
        sh = gc.open_by_key(_sheet_id())
    except Exception as e:
        return False, (
            f"nao abriu a planilha (id comeca com '{_sheet_id()[:10]}...'): "
            f"{type(e).__name__}. Confira o TREINO_SHEET_ID, se a planilha foi "
            f"compartilhada como Editor com o client_email, e se a Google "
            f"Sheets API esta ativa. Detalhe: {e}")
    try:
        try:
            sh.worksheet(_ABA)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(_ABA, rows=2000, cols=len(COLS))
            ws.append_row(COLS)
    except Exception as e:
        return False, f"planilha ok, mas falhou na aba '{_ABA}': {e}"
    return True, "ok"


def salvar(rows: list[dict]) -> int:
    """Anexa avaliacoes. Retorna quantas linhas gravou (0 em falha)."""
    if not rows:
        return 0
    ws = _ws()
    if ws is None:
        return 0
    try:
        _garantir_cabecalho(ws, COLS)
        valores = [[_cel(r.get(c)) for c in COLS] for r in rows]
        ws.append_rows(valores, value_input_option="USER_ENTERED")
        return len(valores)
    except Exception:
        return 0


def carregar() -> pd.DataFrame:
    """Historico completo de avaliacoes. Vazio em falha."""
    ws = _ws()
    if ws is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()


# --- log de aplicacoes de peso no portal (auditoria + desfazer manual) ---
_ABA_LOG = "log_pesos_neo"
COLS_LOG = ["data", "hora", "avaliador", "projeto", "campanha_id", "curva",
            "peso_antes", "peso_depois", "ok"]


def salvar_log(rows: list[dict]) -> int:
    """Anexa linhas ao log de aplicacao de pesos. Retorna quantas gravou."""
    if not rows:
        return 0
    ws = _ws_named(_ABA_LOG, COLS_LOG)
    if ws is None:
        return 0
    try:
        valores = [[_cel(r.get(c)) for c in COLS_LOG] for r in rows]
        ws.append_rows(valores, value_input_option="USER_ENTERED")
        return len(valores)
    except Exception:
        return 0


def _cel(v):
    """Normaliza valor para celula (evita NaN/None virando 'nan')."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return v


# --- calibracao automatica dos parametros do Peso Sugerido ---
_ABA_CAL = "calibracao_neo"
COLS_CAL = ["timestamp", "avaliador", "peso_expoente",
            "mae_antes", "mae_depois", "n_aval"]


def salvar_calibracao(row: dict) -> bool:
    """Anexa uma linha de calibracao aplicada. True se gravou."""
    ws = _ws_named(_ABA_CAL, COLS_CAL)
    if ws is None:
        return False
    try:
        ws.append_row([_cel(row.get(c)) for c in COLS_CAL],
                      value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


def carregar_calibracao() -> dict:
    """Ultima calibracao aplicada (premio_virgem/peso_expoente), ou {}."""
    ws = _ws_named(_ABA_CAL, COLS_CAL)
    if ws is None:
        return {}
    try:
        recs = ws.get_all_records()
        if not recs:
            return {}
        last = recs[-1]
        out = {}
        for k in ("peso_expoente",):
            try:
                out[k] = float(last.get(k))
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return {}

