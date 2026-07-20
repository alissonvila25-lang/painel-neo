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
                print("  app estava dormindo -> acordando")
                pg.wait_for_timeout(20000)
                return
        except Exception:
            pass


def _login(pg):
    try:
        if USER and pg.locator('input[type="password"]').count() > 0:
            campos = pg.locator('[data-testid="stForm"] input')
            campos.nth(0).fill(USER)
            pg.locator('input[type="password"]').first.fill(PASS)
            pg.get_by_role("button", name="Entrar").first.click()
            print("  login enviado")
            pg.wait_for_timeout(5000)
    except Exception as e:
        print("  login pulado:", e)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_default_timeout(60000)
    print(f"abrindo {URL}")
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(10000)   # deixa renderizar
    _acordar(page)
    _login(page)
    # espera o carregamento pesado dos relatorios (aquece o cache)
    page.wait_for_timeout(100000)
    print("cache aquecido (fim da espera)")
    browser.close()
