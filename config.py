"""Configuracao do painel NEO ENERGIA (portal-only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Fuso do Brasil (a nuvem roda em UTC).
TZ_BR = timezone(timedelta(hours=-3))


def now_br() -> datetime:
    return datetime.now(TZ_BR).replace(tzinfo=None)


def today_br():
    return now_br().date()


# Projeto operacional no portal (tenant NEO).
PROJETO = "NEO"

# Limiares da analise (conversao = cadastradas / abordagens, em %).
THRESHOLDS: dict[str, float] = {
    "min_ligacoes": 50,       # volume minimo p/ avaliar uma campanha
    "conv_baixa": 1.0,        # abaixo disso: conversao ruim
    "conv_alta": 3.0,         # acima disso: oportunidade
    "abordagem_baixa": 20.0,  # % abordagem baixa (contactabilidade)
    "disp_baixa_pct": 10.0,   # base disponivel baixa (% do total no discador)
    "hit_rate_baixo": 3.0,    # hit rate baixo no discador (%)
    "cancel_alto": 0.30,      # razao de cancelamento alta
    # calibracao do peso sugerido
    "peso_ramp_frac": 0.4,
    "peso_ramp_min": 3,
    "peso_expoente": 0.6,
}
