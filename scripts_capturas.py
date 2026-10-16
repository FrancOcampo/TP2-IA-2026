"""Capturas automaticas de la UI Gradio para el pitch (Playwright)."""
import pathlib, sys, time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7860"
OUT = pathlib.Path("docs/capturas")
OUT.mkdir(parents=True, exist_ok=True)
PACIENTES = ["P001", "P002", "P003", "P004"]


def shot(page, name, full=True):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    print("OK", path)


def pick_patient(page, pid):
    dd = page.get_by_label("Paciente", exact=True)
    dd.click()
    page.wait_for_timeout(300)
    page.get_by_role("option", name=pid, exact=False).first.click()
    page.wait_for_timeout(300)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.goto(URL, wait_until="load", timeout=60000)
        page.wait_for_timeout(1500)
        shot(page, "00-inicio")

        for pid in PACIENTES:
            pick_patient(page, pid)
            page.get_by_role("button", name="Analizar paciente").click()
            page.wait_for_timeout(1000)
            for _ in range(60):
                if not page.locator(".progress-text, .generating").count():
                    break
                page.wait_for_timeout(1000)
            page.wait_for_timeout(1500)
            shot(page, f"01-consulta-{pid}")

        # Chat de seguimiento (sobre el ultimo reporte)
        try:
            chat = page.get_by_role("textbox").last
            chat.click()
            chat.fill("Que recomendaciones de seguimiento sugerís para este paciente?")
            chat.press("Enter")
            page.wait_for_timeout(8000)
            shot(page, "02-chat-seguimiento")
        except Exception as e:
            print("chat skip:", e)

        # Observabilidad
        try:
            page.get_by_role("tab", name="Observabilidad").click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="Refrescar").first.click()
            page.wait_for_timeout(2500)
            shot(page, "03-observabilidad")
        except Exception as e:
            print("obs skip:", e)

        # Evaluacion
        try:
            page.get_by_role("tab", name="Evaluación").click()
            page.wait_for_timeout(800)
            shot(page, "04-evaluacion")
        except Exception as e:
            print("eval skip:", e)

        b.close()


if __name__ == "__main__":
    main()
