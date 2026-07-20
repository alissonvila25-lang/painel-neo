"""Pre-aquecedor de cache: abre o app num navegador headless, acorda/loga e
espera os dados carregarem, deixando o cache do Streamlit quente.

Variaveis de ambiente:
  APP_URL     URL do app (obrigatorio)
  PANEL_USER  usuario do painel (se houver login)
  PANEL_PASS  senha do painel
"""
import os
import time

from playwright.sync_api import sync_playwright

URL = os.environ["APP_URL"]
USER = os.environ.get("PANEL_USER", "")
PASS = os.environ.get("PANEL_PASS", "")

WAKE_SELECTORS = ('button:has-text("get this app back up")',
                  'button:has-text("Yes, get")',
                  'button:has-text("wake")')


def _acordar(page):
    """Clica no botao de 'wake up' (procura na pagina e em todos os frames)."""
    for ctx in [page] + list(page.frames):
        for sel in WAKE_SELECTORS:
            try:
                if ctx.locator(sel).count() > 0:
                    ctx.locator(sel).first.click()
                    print("  app estava dormindo -> acordando", flush=True)
                    page.wait_for_timeout(25000)
                    return True
            except Exception:
                pass
    return False


def _app_frame(page, timeout_s=120):
    """No *.streamlit.app o app roda dentro de um iframe (url com '/~/')."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for fr in page.frames:
            if "/~/" in (fr.url or ""):
                return fr
        _acordar(page)
        page.wait_for_timeout(2000)
    return page.main_frame


def _login(fr):
    if not USER:
        print("  sem PANEL_USER -> login pulado", flush=True)
        return False
    try:
        fr.wait_for_selector('input[type="password"]', timeout=90000)
    except Exception:
        print("  tela de login nao apareceu (painel aberto?) -> segue", flush=True)
        return False
    try:
        campos = fr.locator('[data-testid="stForm"] input')
        campos.nth(0).fill(USER)
        fr.locator('input[type="password"]').first.fill(PASS)
        fr.get_by_role("button", name="Entrar").first.click()
        print("  login enviado", flush=True)
        try:
            fr.wait_for_selector('input[type="password"]', state="detached", timeout=30000)
            print("  login OK (entrou no painel)", flush=True)
        except Exception:
            print("  AVISO: ainda na tela de login (credenciais?)", flush=True)
        return True
    except Exception as e:
        print("  ERRO no login:", e, flush=True)
        return False


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(60000)
    print(f"abrindo {URL}", flush=True)
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(8000)   # deixa comecar a renderizar
    _acordar(page)
    fr = _app_frame(page)
    print(f"  frame do app: {fr.url}", flush=True)
    _login(fr)
    # espera o carregamento pesado dos relatorios (aquece o cache)
    print("aguardando carga dos relatorios...", flush=True)
    page.wait_for_timeout(100000)
    print("cache aquecido (fim da espera)", flush=True)
    browser.close()
