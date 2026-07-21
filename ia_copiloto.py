"""Copiloto de calibragem via Anthropic Claude.

O analista discorda (ou nao) da sugestao automatica de peso e conversa com a IA
sobre o porque. A IA usa SO os numeros fornecidos + a logica do painel.

Sem token/key nos secrets/env -> `disponivel()` = False e o painel simplesmente
nao mostra o chat. Provedores suportados (nesta ordem de prioridade):
  1) GitHub Models  -> GITHUB_MODELS_TOKEN (ou GITHUB_TOKEN), gratis com rate-limit,
     endpoint compativel com OpenAI. Modelo via IA_MODEL (padrao openai/gpt-4o-mini).
  2) Anthropic      -> ANTHROPIC_API_KEY (pago). Modelo via ANTHROPIC_MODEL.
"""
from __future__ import annotations

import os

_MODEL_GH_DEFAULT = "openai/gpt-4o-mini"        # GitHub Models (gratis, rate-limit)
_MODEL_ANTH_DEFAULT = "claude-3-5-haiku-latest"  # Anthropic (pago)
_GH_URL_DEFAULT = "https://models.github.ai/inference"

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


_STATUS: dict = {}


def ultimo_status() -> dict:
    """Ultimo status de rate-limit lido dos headers (GitHub Models)."""
    return dict(_STATUS)


def _gh_token() -> str:
    return (os.environ.get("GITHUB_MODELS_TOKEN")
            or os.environ.get("GITHUB_TOKEN") or "").strip()


def _anth_key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _provider() -> str:
    """Prioriza GitHub Models (gratis) se houver token; senao Anthropic."""
    if _gh_token():
        return "github"
    if _anth_key():
        return "anthropic"
    return ""


def disponivel() -> bool:
    return bool(_provider())


def _contexto(info: dict) -> str:
    linhas = [f"- {k}: {v}" for k, v in info.items() if v not in (None, "")]
    return "Dados da campanha em discussao:\n" + "\n".join(linhas)


def responder(mensagens: list[dict], info: dict, logica: str) -> str:
    """mensagens: [{'role':'user'|'assistant','content':str}]. Retorna texto."""
    prov = _provider()
    if not prov:
        return ("IA indisponivel: configure GITHUB_MODELS_TOKEN (GitHub Models, "
                "gratis) ou ANTHROPIC_API_KEY nos secrets do app.")
    sistema = f"{SYSTEM}\n\n== LOGICA DO PAINEL ==\n{logica}\n\n{_contexto(info)}"
    if prov == "github":
        return _resp_github(sistema, mensagens)
    return _resp_anthropic(sistema, mensagens)


def _resp_github(sistema: str, mensagens: list[dict]) -> str:
    """GitHub Models: endpoint compativel com OpenAI, autenticado por PAT."""
    try:
        from openai import OpenAI
    except Exception:
        return "Biblioteca 'openai' ausente no ambiente (adicione ao requirements)."
    try:
        base = (os.environ.get("GITHUB_MODELS_URL") or _GH_URL_DEFAULT).strip()
        model = (os.environ.get("IA_MODEL") or _MODEL_GH_DEFAULT).strip()
        client = OpenAI(base_url=base, api_key=_gh_token())
        msgs = [{"role": "system", "content": sistema}] + [
            {"role": m["role"], "content": str(m["content"])}
            for m in mensagens if m.get("content")]
        raw = client.chat.completions.with_raw_response.create(
            model=model, messages=msgs, max_tokens=600)
        try:
            h = raw.headers
            rem = (h.get("x-ratelimit-remaining-requests")
                   or h.get("x-ratelimit-remaining"))
            lim = (h.get("x-ratelimit-limit-requests")
                   or h.get("x-ratelimit-limit"))
            if rem is not None:
                _STATUS.clear()
                _STATUS.update({"remaining": rem, "limit": lim})
        except Exception:
            pass
        resp = raw.parse()
        return (resp.choices[0].message.content or "").strip() or "(sem resposta)"
    except Exception as e:
        return f"Erro ao consultar a IA (GitHub Models): {type(e).__name__}: {e}"


def _resp_anthropic(sistema: str, mensagens: list[dict]) -> str:
    try:
        import anthropic
    except Exception:
        return "Biblioteca 'anthropic' ausente no ambiente (adicione ao requirements)."
    try:
        model = (os.environ.get("ANTHROPIC_MODEL") or _MODEL_ANTH_DEFAULT).strip()
        client = anthropic.Anthropic(api_key=_anth_key())
        msgs = [{"role": m["role"], "content": str(m["content"])}
                for m in mensagens if m.get("content")]
        resp = client.messages.create(
            model=model, max_tokens=600, system=sistema, messages=msgs)
        partes = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "\n".join(partes).strip() or "(a IA nao retornou texto)"
    except Exception as e:
        return f"Erro ao consultar a IA (Anthropic): {type(e).__name__}: {e}"


def resumo_racional(mensagens: list[dict], limite: int = 500) -> str:
    """Junta as falas do analista (role user) num texto curto para o campo obs."""
    falas = [str(m["content"]).strip() for m in mensagens
             if m.get("role") == "user" and m.get("content")]
    txt = " | ".join(falas)
    return (txt[:limite] + "…") if len(txt) > limite else txt
