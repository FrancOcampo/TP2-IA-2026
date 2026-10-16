# tests/test_html_a_markdown.py
#
# Conversor de artículos HTML a Markdown (scripts/html_a_markdown.py). Determinístico, con un HTML
# sintético que imita la estructura de la página (cuerpo, referencias, menús, tablas).

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "html_a_markdown", Path(__file__).resolve().parent.parent / "scripts" / "html_a_markdown.py")
conv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conv)

_HTML = """
<html><head><title>x</title><style>.a{color:red}</style><script>var x = 1;</script></head><body>
<nav><a>Menú principal</a><a>Iniciar sesión</a></nav>
<div class="widget-ArticleFulltext">
  <div class="article-metadata">Compartir · Descargar</div>
  <div class="article-section-wrapper">
    <h2 class="section-title jumplink-heading">Metas glucémicas</h2>
    <h3 class="section-title">Hipoglucemia</h3>
    <p>Recomendación 6.5a: la hipoglucemia de nivel 2 es &lt; 54 mg/dL<a class="xref-bibr">(12,13)</a>.
       Segunda oración.<br>Con salto.</p>
    <ul><li>Primer punto</li><li>Segundo punto <ul><li>Anidado</li></ul></li></ul>
    <figure><img src="f.png"><figcaption>Figura 1 descartada</figcaption></figure>
    <div class="table-wrap">
      <table><tr><th>Nivel</th><th>Umbral</th></tr><tr><td>1</td><td>&lt; 70 | mg/dL</td></tr></table>
      <div class="table-modal"><table><tr><td>DUPLICADO</td></tr></table></div>
    </div>
    <p>Texto final de la sección, con contenido suficiente para superar el mínimo de longitud del conversor.</p>
  </div>
  <div class="ref-list"><div class="ref"><div class="ref-content">1. Referencia bibliográfica descartada</div></div></div>
</div>
<footer>Pie de página descartado</footer>
</body></html>
"""


def test_conserva_titulos_parrafos_listas_y_tablas():
    md = conv.html_a_markdown(_HTML)
    assert "## Metas glucémicas" in md and "### Hipoglucemia" in md
    assert "Recomendación 6.5a: la hipoglucemia de nivel 2 es < 54 mg/dL." in md
    assert "- Primer punto" in md and "  - Anidado" in md
    assert "| Nivel | Umbral |" in md and "| 1 | < 70 / mg/dL |" in md


def test_descarta_menus_referencias_figuras_y_duplicados():
    md = conv.html_a_markdown(_HTML)
    for ruido in ("Menú principal", "Iniciar sesión", "Compartir", "Referencia bibliográfica",
                  "Figura 1 descartada", "DUPLICADO", "Pie de página", "var x", "color:red"):
        assert ruido not in md, ruido


def test_quita_marcadores_de_cita_pero_conserva_numeros_de_recomendacion():
    md = conv.html_a_markdown(_HTML)
    assert "(12,13)" not in md
    assert "6.5a" in md


def test_sin_cuerpo_del_articulo_falla_claro():
    with pytest.raises(ValueError, match="no se encontró el cuerpo"):
        conv.html_a_markdown("<html><body><p>otra página</p></body></html>")


def test_cuerpo_casi_vacio_falla_claro():
    with pytest.raises(ValueError, match="casi vacío"):
        conv.html_a_markdown('<div class="widget-ArticleFulltext"><p>corto</p></div>')


def test_corta_desde_el_titulo_de_referencias():
    html = ('<div class="widget-ArticleFulltext"><h2>Metas</h2>'
            '<p>' + 'Contenido clínico útil. ' * 12 + '</p>'
            '<h2>References</h2><p>Texto legal repetido en cada artículo.</p>'
            '<h2>Otro título posterior</h2><p>Nada de esto debe quedar.</p></div>')
    md = conv.html_a_markdown(html)
    assert "## Metas" in md and "Contenido clínico útil" in md
    for descartado in ("References", "Texto legal", "Otro título", "Nada de esto"):
        assert descartado not in md, descartado
