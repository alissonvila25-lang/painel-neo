# Painel NEO ENERGIA ⚡

Painel de operação do cliente **NEO ENERGIA**, alimentado **apenas pelo Portal
Ayty CRM** (este cliente não tem API). Versão simplificada do painel de
performance, com foco em campanhas, discador e operadores.

## O que mostra
- **Campanhas**: ligações, % abordagem, conversão (cadastradas/abordagens),
  peso configurado × peso do discador × **peso sugerido**, coerência, base
  disponível e hit rate. Ações recomendadas (base esgotada, conversão baixa,
  oportunidades).
- **Operadores**: ranking por produção, curva ABC atual (A/B/C/D) e sugestão
  de divisão por terços.
- Visão do discador (base disponível/bloqueada, hit rate, penetração).

## Fonte de dados (portal, sem API)
- Performance de Operação (161), Curva ABC Usuário (167), TMO (145),
  Estatísticas do Discador (254) e Config Campanha/Grupo (221) do tenant
  `app76` / projeto NEO ENERGIA (1564).

## Rodar localmente
```powershell
$env:AYTY_PORTAL_USER="09810747900"
$env:AYTY_PORTAL_SENHA="<senha>"
streamlit run app.py
```

## Deploy (Streamlit Cloud)
1. Suba este diretório para um repositório.
2. Em *Settings → Secrets*, cole o conteúdo de
   `.streamlit/secrets.toml.example` preenchido (com a senha real).
3. Opcional: defina `NEO_PANEL_SENHA` para exigir login no painel.

## Treinamento / auto-calibração
Reusa a **mesma conta de serviço Google** do outro painel, numa **planilha
dedicada do NEO**. Cole o **mesmo `GCP_SERVICE_ACCOUNT_JSON`** nos secrets e
**compartilhe a planilha do NEO como Editor** com o `client_email` dessa conta
de serviço. O `TREINO_SHEET_ID` já aponta por padrão para a planilha do NEO; as
abas (`treino_neo` / `calibracao_neo`) são criadas automaticamente.

## Observações
- A conversão nativa do portal vem zerada; o painel calcula
  `cadastradas / abordagens`.
- Sem "base virgem" no portal deste tenant, o **peso sugerido** é simplificado
  (conversão + base disponível), com trava de rampa e de conversão baixa.
- A curva por campanha raramente vem preenchida no NEO; a curva relevante é a
  **Curva ABC por operador**.
