# scripts/html_a_markdown.py
#
# Limpia páginas HTML de artículos (p. ej. las secciones de las ADA Standards of Care guardadas
# desde el navegador) y las convierte a Markdown listo para indexar en el RAG (data/guias/).
# Solo usa la biblioteca estándar. Se ejecuta sobre TUS copias descargadas; el texto de las guías
# no se versiona (ver .gitignore y data/guias/README.md).
#
# Qué conserva: títulos (##, ###, ####), párrafos, listas y tablas del cuerpo del artículo.
# Qué descarta: menús, cabeceras y pies, botones, scripts y estilos, controles de figuras y tablas,
# marcadores de cita numéricos y la LISTA DE REFERENCIAS (ruido para el retrieval).
#
# Uso:
#   uv run python scripts/html_a_markdown.py "C:/ruta/6. Glycemic Goals....html" \
#       --out data/guias/ADA_2024_S06_metas_glucemicas_e_hipoglucemia.md
#   uv run python scripts/html_a_markdown.py *.html --out-dir data/guias   # nombre = archivo .md

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Contenedor del cuerpo del artículo (en orden de preferencia)
ROOT_CLASSES = ("widget-ArticleFulltext", "article-body")

# Elementos que se descartan completos (con todo lo que contienen)
SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "button", "form", "select",
             "svg", "iframe", "input", "img", "figure"}
SKIP_CLASSES = {
    "ref-list", "backreferences", "js-splitview-ref-list", "table-modal", "toolbar", "article-metadata",
    "footer-links-group", "fig-expansion", "fig-orig", "graphic-wrap", "section-jump-link",
    "js-article-jump-link", "article-content-filter", "modal", "download-slide",
    "google-scholar-ref-link", "crossref-doi", "adsDoiReference",
}
HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
BLOCK_TAGS = {"p", "li", "div", "section", "ul", "ol", "table", "tr", "caption", "blockquote"}
VOID_TAGS = {"br", "hr", "meta", "link", "input", "img", "wbr", "source", "area", "base", "col"}


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool, bool]] = []  # (tag, skip, is_root)
        self.skip_depth = 0
        self.in_root = False
        self.root_seen = False
        self.heading: str | None = None
        self.list_stack: list[str] = []
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.row: list[str] | None = None
        self.buf: list[str] = []

    # -- utilidades ---------------------------------------------------
    def _emit_block(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()  # \s incluye saltos de línea y \xa0
        self.buf = []
        if not text:
            return
        if self.heading:
            self.out.append(f"\n{self.heading} {text}\n")
        elif self.list_stack:
            marker = "-" if self.list_stack[-1] == "ul" else "1."
            self.out.append(f"{'  ' * (len(self.list_stack) - 1)}{marker} {text}")
        else:
            self.out.append(f"\n{text}\n")

    # -- eventos ------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag == "br" and self.in_root and not self.skip_depth:
                self.buf.append(" ")
            return
        d = dict(attrs)
        classes = set((d.get("class") or "").split())
        is_root = (not self.root_seen and bool(classes & set(ROOT_CLASSES)))
        skip = tag in SKIP_TAGS or bool(classes & SKIP_CLASSES) or d.get("aria-hidden") == "true"
        if is_root:
            self.in_root, self.root_seen = True, True
        self.stack.append((tag, skip, is_root))
        if skip:
            self.skip_depth += 1
        if not self.in_root or self.skip_depth:
            return

        if tag in HEADING_TAGS:
            self._emit_block()
            self.heading = HEADING_TAGS[tag]
        elif tag in ("ul", "ol"):
            self._emit_block()
            self.list_stack.append(tag)
        elif tag == "table":
            self._emit_block()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in BLOCK_TAGS and self.table is None:
            self._emit_block()

    def handle_endtag(self, tag):
        if tag in VOID_TAGS or not self.stack:
            return
        # Cierra hasta el tag coincidente (tolera HTML mal formado)
        while self.stack:
            open_tag, skip, is_root = self.stack.pop()
            if skip:
                self.skip_depth -= 1
            if is_root:
                self._emit_block()
                self.in_root = False
            if open_tag == tag:
                break
        if not self.in_root or self.skip_depth:
            return

        if tag in HEADING_TAGS:
            self._emit_block()
            self.heading = None
        elif tag in ("ul", "ol"):
            self._emit_block()
            if self.list_stack:
                self.list_stack.pop()
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "/"))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self._flush_table()
        elif tag in BLOCK_TAGS and self.table is None:
            self._emit_block()

    def handle_data(self, data):
        if not self.in_root or self.skip_depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.buf.append(data)

    # -- tablas -------------------------------------------------------
    def _flush_table(self) -> None:
        rows, self.table = self.table or [], None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self.out.append("\n" + "\n".join(lines) + "\n")


def _clean_text(md: str) -> str:
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    # Marcadores de cita numéricos sueltos: "(1,2)", "[3]" y rangos "(5–8)"
    md = re.sub(r"\s*[\(\[]\s*\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\s*[\)\]]", "", md)
    md = re.sub(r"(?<=\S)[ \t]{2,}", " ", md)  # solo en medio de la línea: no rompe la sangría de listas
    return md.strip() + "\n"


def html_a_markdown(html: str) -> str:
    """Convierte el HTML de un artículo a Markdown limpio. Lanza ValueError si no encuentra el cuerpo."""
    parser = _Converter()
    parser.feed(html)
    parser.close()
    if not parser.root_seen:
        raise ValueError("no se encontró el cuerpo del artículo (clases esperadas: "
                         + ", ".join(ROOT_CLASSES) + ")")
    md = _clean_text("\n".join(parser.out))
    if len(md) < 200:
        raise ValueError("el cuerpo del artículo salió casi vacío; revisá el HTML de entrada")
    return md


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML de un artículo → Markdown limpio para el RAG.")
    ap.add_argument("html", nargs="+", type=Path, help="archivo(s) HTML descargados")
    ap.add_argument("--out", type=Path, help="archivo de salida (solo con un HTML de entrada)")
    ap.add_argument("--out-dir", type=Path, help="carpeta de salida (un .md por HTML)")
    args = ap.parse_args()
    if bool(args.out) == bool(args.out_dir) or (args.out and len(args.html) != 1):
        ap.error("usá --out con un solo HTML, o --out-dir con varios")

    for path in args.html:
        md = html_a_markdown(path.read_text(encoding="utf-8", errors="replace"))
        target = args.out or (args.out_dir / f"{path.stem}.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        n_head = len(re.findall(r"^#{2,4} ", md, re.M))
        print(f"{path.name[:60]} → {target}  ({len(md):,} caracteres, {n_head} títulos)")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
