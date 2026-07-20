"""Pre-aquecedor de cache: abre o app num navegador headless, acorda/loga e
espera os dados carregarem, deixando o cache do Streamlit quente.

Variaveis de ambiente:
  APP_URL     URL do app (obrigatorio)
  PANEL_USER  usuario do painel (se houver login)
  PANEL_PASS  senha do painel
"""
import os

from playwright.sync_api import sync_playwright

URL = os.environ["APP_URL"]
USER = os.environ.get("PANEL_USER", "")
PASS = os.environ.get("PANEL_PASS", "")


def _acordar(pg):
    """Clica no botao de 'wake up' se o app estiver dormindo."""
    for sel in ('button:has-text("get this app back up")',
                'button:has-text("Yes, get")',
                'button:has-text("wake")'):
        try:
            if pg.locator(sel).count() > 0:
                pg.locator(sel).first.click()
                print("  app estava dormindo -> acordando", flush=True)
                pg.wait_for_timeout(25000)
                return True
        except Exception:
            pass
    return False


def _esperar_senha(pg, timeout_ms=60000):
    """Espera o campo de senha aparecer (cold start do Streamlit e' lento)."""
    try:
        pg.wait_for_selector('input[type="password"]', timeout=timeout_ms)
        return True
    except Exception:
        return False


def _login(pg):
    if not USER:
        print("  sem PANEL_USER -> login pulado", flush=True)
        return False
    # tenta ate a tela de login aparecer, acordando o app se preciso
    for _ in range(3):
        if _esperar_senha(pg, 60000):
            break
        if not _acordar(pg):
            break
    if pg.locator('input[type="password"]').count() == 0:
        print("  ERRO: campo de senha nao apareceu -> login nao feito", flush=True)
        return False
    try:
        campos = pg.locator('[data-testid="stForm"] input')
        campos.nth(0).fill(USER)
        pg.locator('input[type="password"]').first.fill(PASS)
        pg.get_by_role("button", name="Entrar").first.click()
        print("  login enviado", flush=True)
        try:
            pg.wait_for_selector('input[type="password"]', state="detached", timeout=30000)
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
    _login(page)
    # espera o carregamento pesado dos relatorios (aquece o cache)
    print("aguardando carga dos relatorios...", flush=True)
    page.wait_for_timeout(100000)
    print("cache aquecido (fim da espera)", flush=True)
    browser.close()
