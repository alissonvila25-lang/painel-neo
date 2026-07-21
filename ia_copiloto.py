"""Copiloto de calibragem via Anthropic Claude.

O analista discorda (ou nao) da sugestao automatica de peso e conversa com a IA
sobre o porque. A IA usa SO os numeros fornecidos + a logica do painel.

Sem ANTHROPIC_API_KEY nos secrets/env -> `disponivel()` = False e o painel
simplesmente nao mostra o chat. Modelo configuravel via ANTHROPIC_MODEL.
"""
from __future__ import annotations

import os

_MODEL_DEFAULT = "claude-3-5-haiku-latest"

SYSTEM = (
    "Voce e um copiloto de calibragem de PESOS de campanhas de discador (call "
    "center outbound). O peso define quanto esforco de discagem uma campanha "
    "recebe. O analista humano pode discordar da sugestao automatica e definir "
    "um 'Peso Ideal'. Seu papel: discutir o porque com base NOS NUMEROS da "
    "campanha e na logica do painel, de forma curta e objetiva, em portugues do "
    "Brasil. Reconheca quando o analista tem razao; explique quando faz sentido "
    "manter a sugestao. NUNCA invente numeros — use apenas os fornecidos. Se "
    "faltar dado, diga. Seja direto: no maximo ~130 palavras por resposta."
)


def _key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _model() -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or _MODEL_DEFAULT).strip()


def disponivel() -> bool:
    return bool(_key())


def _contexto(info: dict) -> str:
    linhas = [f"- {k}: {v}" for k, v in info.items() if v not in (None, "")]
    return "Dados da campanha em discussao:\n" + "\n".join(linhas)


def responder(mensagens: list[dict], info: dict, logica: str) -> str:
    """mensagens: [{'role':'user'|'assistant','content':str}]. Retorna texto."""
    if not disponivel():
        return ("IA indisponivel: configure ANTHROPIC_API_KEY nos secrets do app "
                "para ativar o copiloto.")
    try:
        import anthropic
    except Exception:
        return "Biblioteca 'anthropic' ausente no ambiente (adicione ao requirements)."
    try:
        client = anthropic.Anthropic(api_key=_key())
        sistema = f"{SYSTEM}\n\n== LOGICA DO PAINEL ==\n{logica}\n\n== {_contexto(info)}"
        msgs = [{"role": m["role"], "content": str(m["content"])}
                for m in mensagens if m.get("content")]
        resp = client.messages.create(
            model=_model(), max_tokens=600, system=sistema, messages=msgs)
        partes = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "\n".join(partes).strip() or "(a IA nao retornou texto)"
    except Exception as e:
        return f"Erro ao consultar a IA: {type(e).__name__}: {e}"


def resumo_racional(mensagens: list[dict], limite: int = 500) -> str:
    """Junta as falas do analista (role user) num texto curto para o campo obs."""
    falas = [str(m["content"]).strip() for m in mensagens
             if m.get("role") == "user" and m.get("content")]
    txt = " | ".join(falas)
    return (txt[:limite] + "…") if len(txt) > limite else txt
