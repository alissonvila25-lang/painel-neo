"""Snapshot diario do NEO — coleta D-1 e grava no historico (Google Sheets).

Rodado pelo GitHub Action (cron) ou manualmente. Le credenciais do AMBIENTE:
  AYTY_PORTAL_USER, AYTY_PORTAL_SENHA, GCP_SERVICE_ACCOUNT_JSON, TREINO_SHEET_ID.
"""
import datetime as dt

import historico as H
import treino
from config import today_br

if __name__ == "__main__":
    ok, msg = treino.status()
    print(f"[snapshot] treino/planilha: ok={ok} — {msg}")
    _h = treino.carregar_historico()
    print(f"[snapshot] historico existente: {len(_h)} linha(s)")
    d1 = today_br() - dt.timedelta(days=1)
    # preenche qualquer dia faltante da ultima semana ate D-1 (robusto a falhas).
    n = H.atualizar_ate(d1, dias_janela=7, max_fetch=7)
    print(f"[snapshot] {n} dia(s) adicionados ate {d1:%Y-%m-%d}")
