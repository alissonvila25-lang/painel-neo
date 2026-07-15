"""Cliente do Portal Ayty CRM.

Extrai relatorios do portal (DynamicQuery) como DataFrame usando apenas
`requests` (sem navegador). Fluxo validado:
  1. GET Login.aspx  -> captura __VIEWSTATE/__EVENTVALIDATION
  2. POST login (com Referer + Origin, obrigatorios) -> sessao autenticada
  3. POST Default.aspx selecionando o projeto -> menu com GUIDs de sessao
  4. GET pagina do relatorio -> captura os campos do form
  5. POST Pesquisar com formato CSV -> servidor transmite o arquivo

Credenciais (via variaveis de ambiente / secrets — NUNCA hardcodar):
  AYTY_PORTAL_USER   (login do cliente)
  AYTY_PORTAL_SENHA  (obrigatoria)
  AYTY_PORTAL_BASE   (opcional; default = tenant NEO/app76)
  AYTY_PORTAL_ORIGIN (opcional)
"""
from __future__ import annotations

import datetime as _dt
import io
import os
import re

import pandas as pd
import requests

BASE = os.environ.get(
    "AYTY_PORTAL_BASE",
    "https://app76.digitalcontact.cloud/AYTY/AppINTEGRACAO/"
    "AytyPortalExFrontEndWeb",
)
ORIGIN = os.environ.get("AYTY_PORTAL_ORIGIN", "https://app76.digitalcontact.cloud")
LOGIN_URL = f"{BASE}/Views/Login.aspx"
DEFAULT_URL = f"{BASE}/Views/Default.aspx"
REPORT_URL = f"{BASE}/Views/Manager/DynamicQuery.aspx"

# pIdProject no combobox do portal (ctl00$cmbProjectList) — tenant NEO ENERGIA.
PROJETOS_PORTAL: dict[str, int] = {
    "NEO": 1564,       # NEO ENERGIA (operacional)
    "DISCADOR": 305,   # DIALER SYSTEM (estatisticas de discador)
}

# Sub-projeto (value do combo obrigatorio ctl09$comboBox) do Estatisticas
# Discador (projeto 305, pIdMenu 254). O discador atende o projeto operacional.
DISCADOR_MENU = 254
DISCADOR_SUBPROJ: dict[str, int] = {
    "NEO": 1564,
}

# Tela de configuracao (grid editavel DynamicEditorList) do projeto 305 que
# mostra o peso REAL e a curva (via nome do grupo) que os analistas definem.
CONFIG_CAMPANHA_MENU = 221  # "Configurar Campanha no Grupo de Atendimento"
_CURVA_RE = re.compile(r"CURVA\s+([A-Za-z0-9]+)")
_COD_RE = re.compile(r"^\s*0*(\d+)\s*-")


def _cod_campanha(nome: object) -> int | None:
    """'000234 - ASSISTY ...' -> 234."""
    if not nome:
        return None
    m = _COD_RE.match(str(nome))
    return int(m.group(1)) if m else None

# pIdMenu conhecidos por projeto (IDs estaveis; o GUID e resolvido em runtime).
# Tenant NEO ENERGIA (pIdProject=1564). Nomes livres -> pIdMenu.
RELATORIOS: dict[int, dict[str, int]] = {
    1564: {  # NEO ENERGIA
        "performance_operacao": 161,
        "performance_operacao_v2": 6008,
        "resumo_mailing": 162,
        "tmo_operador": 145,
        "curva_abc_usuario": 167,
        "curva_abc_supervisor": 166,
        "ligacoes_gravacoes": 146,
        "performance_vendas": 149,
        "vendas_por_operador": 151,
    },
}

_LINK_RE = re.compile(
    r"DynamicQuery\.aspx\?pIdMenu=(\d+)&(?:amp;)?pIdProject=(\d+)"
    r"&(?:amp;)?pIdUser=(\d+)&(?:amp;)?pNuGuid=([0-9a-fA-F\-]+)"
)


class PortalError(RuntimeError):
    """Falha de autenticacao ou de acesso ao portal."""


class PortalAyty:
    """Sessao autenticada no Portal Ayty CRM."""

    def __init__(self, usuario: str | None = None, senha: str | None = None,
                 timeout: int = 120):
        self.usuario = usuario or os.environ.get("AYTY_PORTAL_USER", "")
        self._senha = senha or os.environ.get("AYTY_PORTAL_SENHA", "")
        self.timeout = timeout
        self.pid_user: str | None = None
        self._logado = False
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })

    # ------------------------------------------------------------------ login
    @staticmethod
    def _hidden(html: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for m in re.finditer(
            r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
            html,
        ):
            fields[m.group(1)] = m.group(2)
        return fields

    def login(self) -> "PortalAyty":
        if self._logado:
            return self
        if not self._senha:
            raise PortalError(
                "Senha ausente: defina a variavel de ambiente AYTY_PORTAL_SENHA."
            )
        r = self.s.get(LOGIN_URL, timeout=self.timeout)
        r.raise_for_status()
        f = self._hidden(r.text)
        form = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": f.get("__VIEWSTATE", ""),
            "__EVENTVALIDATION": f.get("__EVENTVALIDATION", ""),
            "hidScreenWidth": "1920",
            "hidScreenHeight": "1080",
            "txtDeLogin": self.usuario,
            "txtDePassword": self._senha,
            "btnOk": "Acessar",
        }
        # Referer + Origin sao obrigatorios (protecao anti-bot do portal).
        headers = {"Referer": LOGIN_URL, "Origin": ORIGIN}
        self.s.post(LOGIN_URL, data=form, headers=headers, timeout=self.timeout)
        # Confirma acessando o Default.aspx.
        d = self.s.get(DEFAULT_URL, timeout=self.timeout)
        if "Login.aspx" in d.url or "cmbProjectList" not in d.text:
            raise PortalError(
                "Login falhou (usuario/senha invalidos ou portal indisponivel)."
            )
        m = re.search(r"pIdUser=(\d+)", d.text)
        if m:
            self.pid_user = m.group(1)
        self._default_html = d.text
        self._logado = True
        return self

    # ------------------------------------------------------------------ menu
    def menu(self, pid_project: int) -> dict[int, str]:
        """Seleciona o projeto e retorna {pIdMenu: pNuGuid} (GUIDs da sessao)."""
        self.login()
        f = self._hidden(self._default_html)
        form = {
            "__EVENTTARGET": "ctl00$cmbProjectList",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": f.get("__VIEWSTATE", ""),
            "__EVENTVALIDATION": f.get("__EVENTVALIDATION", ""),
            "ctl00$cmbProjectList": str(pid_project),
        }
        headers = {"Referer": DEFAULT_URL, "Origin": ORIGIN}
        r = self.s.post(DEFAULT_URL, data=form, headers=headers,
                        timeout=self.timeout)
        guids: dict[int, str] = {}
        for menu_id, proj, usr, guid in _LINK_RE.findall(r.text):
            if self.pid_user is None and usr:
                self.pid_user = usr   # pIdUser real vem dos links do menu
            if int(proj) == pid_project:
                guids.setdefault(int(menu_id), guid)
        if not guids:
            raise PortalError(
                f"Nenhum relatorio encontrado para o projeto {pid_project}."
            )
        return guids

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _serialize_form(html: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for im in re.finditer(r"<input\b[^>]*>", html):
            tag = im.group(0)
            nm = re.search(r'name="([^"]+)"', tag)
            if not nm:
                continue
            name = nm.group(1)
            tp = (re.search(r'type="([^"]*)"', tag) or [None, "text"])[1].lower()
            val = re.search(r'value="([^"]*)"', tag)
            value = val.group(1) if val else ""
            if tp in ("submit", "button", "image", "reset"):
                continue
            if tp in ("checkbox", "radio"):
                if "checked" in tag.lower():
                    data[name] = value or "on"
                continue
            data[name] = value
        for sm in re.finditer(
            r'<select\b([^>]*)>(.*?)</select>', html, re.S | re.I
        ):
            attrs, inner = sm.group(1), sm.group(2)
            nm = re.search(r'name="([^"]+)"', attrs)
            if not nm:
                continue
            name = nm.group(1)
            # Listboxes de filtro desabilitadas (Filtrar desmarcado) nao sao
            # enviadas pelo navegador -> ignora.
            if re.search(r"\bdisabled\b", attrs, re.I):
                continue
            is_multi = re.search(r"\bmultiple\b", attrs, re.I) is not None
            selm = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected', inner)
            if selm:
                data[name] = selm.group(1)
            elif not is_multi:
                # Combo de selecao unica: navegador envia a 1a opcao por padrao.
                opts = re.findall(r'<option[^>]*value="([^"]*)"', inner)
                if opts:
                    data[name] = opts[0]
            # multi-select sem selecao -> omite (igual ao navegador)
        return data

    @staticmethod
    def _midnight_ms(d: _dt.date) -> int:
        return int(_dt.datetime(d.year, d.month, d.day,
                                tzinfo=_dt.timezone.utc).timestamp() * 1000)

    def _aplicar_datas(self, payload: dict[str, str], html: str,
                       dt_ini: _dt.date, dt_fim: _dt.date) -> None:
        pref = re.search(r'name="(ctl\d+)\$cldDtStart"', html)
        if not pref:
            return  # relatorio sem filtro de data
        p = pref.group(1)
        ini = dt_ini.strftime("%d/%m/%Y")
        fim = dt_fim.strftime("%d/%m/%Y")
        # Estado interno do DevExpress ASPxDateEdit: formato "MM/dd/yyyy:MM/dd/yyyy".
        # E o valor que o servidor efetivamente le; sem ele o filtro de data e ignorado.
        ini_c = f"{dt_ini.strftime('%m/%d/%Y')}:{dt_ini.strftime('%m/%d/%Y')}"
        fim_c = f"{dt_fim.strftime('%m/%d/%Y')}:{dt_fim.strftime('%m/%d/%Y')}"
        payload[f"{p}$cldDtStart"] = ini
        payload[f"{p}$cldDtFinish"] = fim
        payload[f"{p}$cldDtStart$DDD$C"] = ini_c
        payload[f"{p}$cldDtFinish$DDD$C"] = fim_c
        payload[f"{p}_cldDtStart_TS"] = str(self._midnight_ms(dt_ini))
        payload[f"{p}_cldDtFinish_TS"] = str(self._midnight_ms(dt_fim))
        payload[f"{p}$txtDtStart"] = "00:00:00"
        payload[f"{p}$txtDtFinish"] = "23:59:59"
        payload[f"{p}$txtDtStart$DDD$C"] = ini_c
        payload[f"{p}$txtDtFinish$DDD$C"] = fim_c
        payload[f"{p}_txtDtStart_TS"] = str(self._midnight_ms(dt_ini))
        payload[f"{p}_txtDtFinish_TS"] = str(self._midnight_ms(dt_fim) + 86399000)

    # -------------------------------------------------------------- extracao
    def fetch_relatorio(self, pid_project: int, pid_menu: int,
                        dt_ini: _dt.date | None = None,
                        dt_fim: _dt.date | None = None,
                        guids: dict[int, str] | None = None,
                        extra_fields: dict[str, str] | None = None) -> pd.DataFrame:
        """Baixa um relatorio (por pIdMenu) como DataFrame via export CSV.

        `extra_fields` sobrescreve campos do form (ex.: combo obrigatorio
        ctl09$comboBox do Estatisticas Discador, checkboxes de detalhe).
        """
        self.login()
        if guids is None:
            guids = self.menu(pid_project)
        guid = guids.get(pid_menu)
        if not guid:
            raise PortalError(
                f"pIdMenu {pid_menu} indisponivel no projeto {pid_project}."
            )
        url = (
            f"{REPORT_URL}?pIdMenu={pid_menu}&pIdProject={pid_project}"
            f"&pIdUser={self.pid_user or '73'}&pNuGuid={guid}"
        )
        r = self.s.get(url, headers={"Referer": DEFAULT_URL}, timeout=self.timeout)
        payload = self._serialize_form(r.text)
        payload["__EVENTTARGET"] = ""
        payload["__EVENTARGUMENT"] = ""
        payload["btnQuery"] = "Pesquisar"
        for base in ("cmbIdFormatType", "cmbIdFormatTypeTop"):
            payload[base] = "CSV"
            payload[base + "_VI"] = "CSV"
        if dt_ini and dt_fim:
            self._aplicar_datas(payload, r.text, dt_ini, dt_fim)
        if extra_fields:
            payload.update(extra_fields)
        resp = self.s.post(url, data=payload, headers={"Referer": url},
                           timeout=max(self.timeout, 180))
        ctype = resp.headers.get("Content-Type", "").lower()
        cd = (resp.headers.get("Content-Disposition") or "").lower()
        if "csv" not in ctype and "attachment" not in cd:
            raise PortalError(
                f"Relatorio {pid_menu} nao retornou CSV (Content-Type={ctype!r})."
            )
        return pd.read_csv(
            io.BytesIO(resp.content), sep=";", encoding="latin-1", decimal=",",
            dtype=str,
        )

    def relatorio(self, projeto: str, nome: str,
                  dt_ini: _dt.date | None = None,
                  dt_fim: _dt.date | None = None) -> pd.DataFrame:
        """Atalho: fetch por nome amigavel (ver RELATORIOS)."""
        pid = PROJETOS_PORTAL[projeto]
        pid_menu = RELATORIOS[pid][nome]
        return self.fetch_relatorio(pid, pid_menu, dt_ini, dt_fim)

    def estatisticas_discador(self, projeto: str,
                              detalhado: bool = True) -> pd.DataFrame:
        """Estatisticas do discador (peso, buffer, disponiveis, bloqueios).

        `projeto` = "CPFL" ou "ENEL". Snapshot atual (sem filtro de data).
        `detalhado=True` inclui Spin/Hit Rate, Penetracao e colunas de
        finalizacao/bloqueio (checkboxes Versao detalhada + estatisticas de
        ligacao).
        """
        sub = DISCADOR_SUBPROJ.get(projeto)
        if sub is None:
            raise PortalError(f"Projeto {projeto!r} sem sub-projeto de discador.")
        extra = {"ctl09$comboBox": str(sub)}
        if detalhado:
            extra["ctl21$checkBox"] = "on"  # Versao detalhada
            extra["ctl24$checkBox"] = "on"  # hit/spin/penetracao
        return self.fetch_relatorio(
            PROJETOS_PORTAL["DISCADOR"], DISCADOR_MENU, extra_fields=extra,
        )

    # ------------------------------------------ config campanha x grupo
    @staticmethod
    def _sel_option(block: str, col: int) -> tuple[str, str]:
        """(value, texto) da <option selected> da coluna `col` (ddl) da linha."""
        m = re.search(
            rf'name="grdEditorList\$cell\d+_{col}\$ddl".*?</select>', block, re.S
        )
        if not m:
            return "", ""
        seg = m.group(0)
        om = re.search(
            r'<option[^>]*\bselected\b[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
            seg, re.S,
        ) or re.search(
            r'<option[^>]*value="([^"]*)"[^>]*\bselected\b[^>]*>(.*?)</option>',
            seg, re.S,
        )
        if not om:
            return "", ""
        import html as _h
        txt = _h.unescape(re.sub(r"<[^>]+>", "", om.group(2))).strip()
        return om.group(1), txt

    @staticmethod
    def _txt_value(block: str, col: int) -> str:
        """value do <input> txt da coluna `col` da linha."""
        m = re.search(
            rf'<input[^>]*name="grdEditorList\$cell\d+_{col}\$txt"[^>]*>', block
        )
        if not m:
            return ""
        v = re.search(r'value="([^"]*)"', m.group(0))
        return v.group(1) if v else ""

    @staticmethod
    def _serialize_row(block: str) -> dict[str, str]:
        """Campos de UMA linha de dados (celulas txt/ddl), como o navegador
        posta no Salvar. So grdEditorList$cell{N}_{col}$(txt|ddl)."""
        out: dict[str, str] = {}
        for m in re.finditer(
            r'<input\b[^>]*name="(grdEditorList\$cell\d+_\d+\$txt)"[^>]*>', block
        ):
            v = re.search(r'value="([^"]*)"', m.group(0))
            out[m.group(1)] = v.group(1) if v else ""
        for m in re.finditer(
            r'<select\b[^>]*name="(grdEditorList\$cell\d+_\d+\$ddl)"[^>]*>(.*?)</select>',
            block, re.S,
        ):
            name, inner = m.group(1), m.group(2)
            sel = (re.search(r'<option[^>]*\bselected\b[^>]*value="([^"]*)"', inner)
                   or re.search(r'<option[^>]*value="([^"]*)"[^>]*\bselected\b', inner))
            if sel:
                out[name] = sel.group(1)
            else:
                first = re.search(r'<option[^>]*value="([^"]*)"', inner)
                out[name] = first.group(1) if first else ""
        return out

    def config_campanha_grupo(self, projeto: str) -> pd.DataFrame:
        """Le a tela 'Configurar Campanha no Grupo de Atendimento'.

        Retorna o peso REAL configurado pelos analistas e a curva (extraida do
        nome do grupo de atendimento) por campanha. `projeto` = "CPFL"/"ENEL".
        Snapshot atual (sem filtro de data). Colunas: Projeto, Codigo, Campanha,
        Grupo de Atendimento, Curva, Peso, Peso %, Alterado em, Alterado por.
        """
        pid = PROJETOS_PORTAL.get(projeto)
        if pid is None:
            raise PortalError(f"Projeto {projeto!r} desconhecido.")
        self.login()
        guids = self.menu(PROJETOS_PORTAL["DISCADOR"])  # menu do projeto 305
        guid = guids.get(CONFIG_CAMPANHA_MENU)
        if not guid:
            raise PortalError(
                f"Menu {CONFIG_CAMPANHA_MENU} (config campanha) indisponivel."
            )
        url = (
            f"{REPORT_URL}?pIdMenu={CONFIG_CAMPANHA_MENU}&pIdProject=305"
            f"&pIdUser={self.pid_user or '73'}&pNuGuid={guid}"
        )
        r = self.s.get(url, headers={"Referer": DEFAULT_URL}, timeout=self.timeout)
        payload = self._serialize_form(r.text)
        payload["__EVENTTARGET"] = ""
        payload["__EVENTARGUMENT"] = ""
        payload["ctl04$comboBox"] = str(pid)   # Projeto
        payload["ctl15$comboBox"] = "1"          # Fila DEFAULT
        payload["ctl21$comboBox"] = "-1"         # Listar todas
        payload["btnQuery"] = "Pesquisar"
        resp = self.s.post(url, data=payload, headers={"Referer": url},
                           timeout=max(self.timeout, 180))
        blocks = re.split(r'<tr id="grdEditorList_DXDataRow\d+"', resp.text)[1:]
        registros: list[dict[str, str]] = []
        for block in blocks:
            _, campanha = self._sel_option(block, 2)
            _, grupo = self._sel_option(block, 3)
            peso = self._txt_value(block, 4)
            pct = self._txt_value(block, 5)
            alterado_em = self._txt_value(block, 23)
            alterado_por = self._txt_value(block, 24)
            if not campanha:
                continue
            cod = ""
            for tdm in re.finditer(r'<td[^>]*>(.*?)</td>', block, re.S):
                t = re.sub(r"<[^>]+>", "", tdm.group(1)).strip()
                if t.isdigit():
                    cod = t
                    break
            cm = _CURVA_RE.search(grupo)
            registros.append({
                "Projeto": projeto,
                "Codigo": cod,
                "Campanha": campanha,
                "Grupo de Atendimento": grupo,
                "Curva": cm.group(1).upper() if cm else "",
                "Peso": peso,
                "Peso %": pct,
                "Alterado em": alterado_em,
                "Alterado por": alterado_por,
            })
        return pd.DataFrame(registros)

    # -------------------------------------- gravacao de pesos (com dry-run)
    def aplicar_pesos(self, projeto: str,
                      alteracoes: dict[tuple[int, str], int],
                      dry_run: bool = True) -> dict:
        """Grava pesos na tela 'Configurar Campanha no Grupo' (botao Salvar).

        `alteracoes`: {(campanha_id, curva): novo_peso}. Ex.: {(234, "B"): 15}.
        `dry_run=True` (padrao): NAO envia nada — apenas retorna o preview do
        que mudaria. So com dry_run=False o POST de gravacao e enviado.

        Seguranca: busca a grid FRESCA, altera SO as celulas casadas por
        campanha+curva e reenvia a grid inteira com os demais valores intactos.

        Retorna dict: dry_run, n_linhas_grid, mudancas[], n_mudancas,
        nao_encontradas[], enviado, ok (+ status_http/erro quando envia).
        """
        pid = PROJETOS_PORTAL.get(projeto)
        if pid is None:
            raise PortalError(f"Projeto {projeto!r} desconhecido.")
        self.login()
        guids = self.menu(PROJETOS_PORTAL["DISCADOR"])
        guid = guids.get(CONFIG_CAMPANHA_MENU)
        if not guid:
            raise PortalError(
                f"Menu {CONFIG_CAMPANHA_MENU} (config campanha) indisponivel."
            )
        url = (
            f"{REPORT_URL}?pIdMenu={CONFIG_CAMPANHA_MENU}&pIdProject=305"
            f"&pIdUser={self.pid_user or '73'}&pNuGuid={guid}"
        )
        # 1) abre a tela e filtra o projeto (mesma consulta da leitura)
        r = self.s.get(url, headers={"Referer": DEFAULT_URL}, timeout=self.timeout)
        q = self._serialize_form(r.text)
        q["__EVENTTARGET"] = ""
        q["__EVENTARGUMENT"] = ""
        q["ctl04$comboBox"] = str(pid)
        q["ctl15$comboBox"] = "1"
        q["ctl21$comboBox"] = "-1"
        q["btnQuery"] = "Pesquisar"
        resp = self.s.post(url, data=q, headers={"Referer": url},
                           timeout=max(self.timeout, 180))
        html = resp.text
        # 2) payload de SALVAR montado EXATAMENTE como o navegador: apenas os
        # campos do topo + as celulas das linhas de dados. O _serialize_form
        # generico pega campos demais (templates/filtros ocultos) e o servidor
        # responde vazio; aqui enviamos so o essencial.
        def _hid(nome: str) -> str:
            m = re.search(rf'name="{re.escape(nome)}"[^>]*value="([^"]*)"', html)
            if m:
                return m.group(1)
            m = re.search(rf'value="([^"]*)"[^>]*name="{re.escape(nome)}"', html)
            return m.group(1) if m else ""

        save = {
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "__VIEWSTATE": _hid("__VIEWSTATE"),
            "cmbBindList": "", "cmbIdCampaign$ddl": "",
            "grdEditorList$DXSelInput": "",
            "grdEditorList$CallbackState": _hid("grdEditorList$CallbackState"),
            "btnUpdate": "Salvar",
            "clientUTCTimeZoneOffsetTime": "", "clientLocalTimeZoneOffsetTime": "",
        }
        for _blk in re.split(r'<tr id="grdEditorList_DXDataRow\d+"', html)[1:]:
            save.update(self._serialize_row(_blk))
        # 3) casa as alteracoes por (campanha_id, curva) -> celula de peso
        blocks = re.split(r'<tr id="grdEditorList_DXDataRow\d+"', html)[1:]
        mudancas: list[dict] = []
        encontradas: set[tuple[int, str]] = set()
        for block in blocks:
            _, campanha = self._sel_option(block, 2)
            _, grupo = self._sel_option(block, 3)
            cid = _cod_campanha(campanha)
            if cid is None:
                continue
            cm = _CURVA_RE.search(grupo)
            curva = cm.group(1).upper() if cm else ""
            cellm = re.search(
                r'name="(grdEditorList\$cell\d+_4\$txt)"[^>]*value="([^"]*)"',
                block)
            if not cellm:
                continue
            cell_name, peso_atual = cellm.group(1), cellm.group(2)
            chave = (int(cid), curva)
            if chave in alteracoes:
                encontradas.add(chave)
                novo = int(alteracoes[chave])
                if str(novo) != str(peso_atual).strip():
                    save[cell_name] = str(novo)
                    _rowm = re.search(r"cell(\d+)_4", cell_name)
                    mudancas.append({
                        "campanha_id": int(cid), "campanha": campanha,
                        "curva": curva, "grupo": grupo,
                        "peso_atual": peso_atual, "peso_novo": novo,
                        "celula": cell_name,
                        "_row": int(_rowm.group(1)) if _rowm else None,
                    })
        nao_encontradas = [k for k in alteracoes if k not in encontradas]
        # SELECAO: o "Salvar" so grava as linhas MARCADAS. O portal codifica a
        # selecao no campo grdEditorList$DXSelInput como uma flag T/F por linha
        # (indice visivel), truncando os F finais. Marca so as linhas alteradas.
        _sel = sorted(m["_row"] for m in mudancas if m.get("_row") is not None)
        if _sel:
            _maxi = _sel[-1]
            _sset = set(_sel)
            save["grdEditorList$DXSelInput"] = "".join(
                "T" if i in _sset else "F" for i in range(_maxi + 1))
        resultado = {
            "dry_run": dry_run, "n_linhas_grid": len(blocks),
            "mudancas": mudancas, "n_mudancas": len(mudancas),
            "nao_encontradas": nao_encontradas, "url": url, "enviado": False,
            "ok": True,
        }
        if dry_run or not mudancas:
            return resultado
        # 4) envio REAL (so com dry_run=False e havendo mudancas)
        try:
            r2 = self.s.post(url, data=save,
                             headers={"Referer": url, "Origin": ORIGIN},
                             timeout=max(self.timeout, 180))
            resultado["enviado"] = True
            resultado["status_http"] = r2.status_code
            # VERIFICA persistencia: 200 NAO significa salvo. Rele a grid e
            # confere se os pesos-alvo mudaram de fato.
            atual = self._ler_pesos_grid(url, pid)
            persistiu = all(
                atual.get((m["campanha_id"], m["curva"])) == str(m["peso_novo"])
                for m in mudancas)
            resultado["persistido"] = persistiu
            resultado["ok"] = persistiu
            if not persistiu:
                resultado["erro"] = (
                    "o portal respondeu OK mas NAO persistiu os pesos — o "
                    "'Salvar' desta tela usa outro mecanismo (callback). "
                    "Gravacao real ainda nao habilitada.")
        except Exception as e:  # noqa: BLE001
            resultado["ok"] = False
            resultado["erro"] = f"{type(e).__name__}: {e}"
        return resultado

    def _ler_pesos_grid(self, url: str, pid: int) -> dict:
        """Rele a grid de config e retorna {(campanha_id, curva): peso_str}."""
        r = self.s.get(url, headers={"Referer": DEFAULT_URL}, timeout=self.timeout)
        q = self._serialize_form(r.text)
        q.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "",
                  "ctl04$comboBox": str(pid), "ctl15$comboBox": "1",
                  "ctl21$comboBox": "-1", "btnQuery": "Pesquisar"})
        html = self.s.post(url, data=q, headers={"Referer": url},
                           timeout=max(self.timeout, 180)).text
        atual: dict = {}
        for block in re.split(r'<tr id="grdEditorList_DXDataRow\d+"', html)[1:]:
            _, campanha = self._sel_option(block, 2)
            _, grupo = self._sel_option(block, 3)
            cid = _cod_campanha(campanha)
            if cid is None:
                continue
            cm = _CURVA_RE.search(grupo)
            curva = cm.group(1).upper() if cm else ""
            atual[(int(cid), curva)] = str(self._txt_value(block, 4)).strip()
        return atual


if __name__ == "__main__":
    import sys

    portal = PortalAyty().login()
    print("Login OK. pIdUser =", portal.pid_user)
    proj = int(sys.argv[1]) if len(sys.argv) > 1 else 1499
    menu = portal.menu(proj)
    print(f"Projeto {proj}: {len(menu)} relatorios. pIdMenus:", sorted(menu)[:10])
