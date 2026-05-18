from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
BUILD_DOCS_DIR = PROJECT_ROOT / "build" / "docs"


@dataclass(frozen=True)
class DocSpec:
    source: str
    pdf: str
    title: str
    badge: str
    subtitle: str
    html_output: str | None = None


DOCS = (
    DocSpec("README.md", "README.pdf", "口腔機能・栄養評価", "Overview", "配布・運用の全体像", "README.html"),
    DocSpec("DEPLOY_SYNOLOGY_JA.md", "DEPLOY_SYNOLOGY_JA.pdf", "Synology + Tailscale 配置手順", "Admin", "管理者向け配置手順", "DEPLOY_SYNOLOGY_JA.html"),
    DocSpec("OPERATIONS_MANUAL_JA.md", "OPERATIONS_MANUAL_JA.pdf", "初心者向け操作マニュアル", "Manual", "現場利用者向けの操作手順", "OPERATIONS_MANUAL_PDF_JA.html"),
    DocSpec("ST_CLAUDE_UPDATE_GUIDE_JA.md", "ST_CLAUDE_UPDATE_GUIDE_JA.pdf", "言語聴覚士向け Claude 画面修正手順", "ST", "言語聴覚士が Claude で index.html を作って管理者へ渡すまでの手順", "ST_CLAUDE_UPDATE_GUIDE_JA.html"),
    DocSpec("TAILSCALE_CLIENT_GUIDE_JA.md", "TAILSCALE_CLIENT_GUIDE_JA.pdf", "Windows 利用者向け Tailscale 接続ガイド", "Windows", "Windows 利用者向け配布資料", "TAILSCALE_CLIENT_GUIDE_JA.html"),
    DocSpec("TAILSCALE_TABLET_GUIDE_JA.md", "TAILSCALE_TABLET_GUIDE_JA.pdf", "タブレット利用者向け Tailscale 接続ガイド", "Tablet", "iPad / Android 利用者向け配布資料", "TAILSCALE_TABLET_GUIDE_JA.html"),
    DocSpec("TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md", "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf", "タブレット利用者向け案内文テンプレート", "Template", "管理者向け配布文テンプレート", "TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html"),
    DocSpec("TAILSCALE_TABLET_QR_SHEET_JA.md", "TAILSCALE_TABLET_QR_SHEET_JA.pdf", "タブレット利用者向け QR 案内シート", "Handout", "印刷配布向け QR 案内", "TAILSCALE_TABLET_QR_SHEET_JA.html"),
)


def resolve_edge_path(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    resolved = shutil.which("msedge.exe")
    if resolved:
        return Path(resolved)

    raise FileNotFoundError("Microsoft Edge was not found.")


def parse_inline(text: str) -> str:
    token_re = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)")
    parts: list[str] = []
    cursor = 0

    for match in token_re.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]))
        code_value, strong_value, link_label, link_target = match.groups()
        if code_value is not None:
            parts.append(f"<code>{html.escape(code_value)}</code>")
        elif strong_value is not None:
            parts.append(f"<strong>{parse_inline(strong_value)}</strong>")
        else:
            safe_target = html.escape(link_target, quote=True)
            parts.append(f'<a href="{safe_target}">{parse_inline(link_label)}</a>')
        cursor = match.end()

    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def flush_paragraph(output: list[str], paragraph_lines: list[str]) -> None:
    if not paragraph_lines:
        return
    merged = " ".join(line.strip() for line in paragraph_lines if line.strip())
    if merged:
        output.append(f"<p>{parse_inline(merged)}</p>")
    paragraph_lines.clear()


def flush_list(output: list[str], list_kind: str | None, list_items: list[str]) -> None:
    if not list_kind or not list_items:
        list_items.clear()
        return
    items_html = "".join(f"<li>{item}</li>" for item in list_items)
    output.append(f"<{list_kind}>{items_html}</{list_kind}>")
    list_items.clear()


def render_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    output: list[str] = []
    paragraph_lines: list[str] = []
    list_kind: str | None = None
    list_items: list[str] = []
    code_lines: list[str] = []
    code_language = ""
    in_code_block = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if in_code_block:
            if stripped.startswith("```"):
                code_html = html.escape("\n".join(code_lines))
                class_attr = f' class="language-{html.escape(code_language, quote=True)}"' if code_language else ""
                output.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
                code_lines.clear()
                code_language = ""
                in_code_block = False
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            flush_paragraph(output, paragraph_lines)
            flush_list(output, list_kind, list_items)
            list_kind = None
            code_language = stripped[3:].strip()
            in_code_block = True
            continue

        if not stripped:
            flush_paragraph(output, paragraph_lines)
            flush_list(output, list_kind, list_items)
            list_kind = None
            continue

        image_match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", stripped)
        if image_match:
            flush_paragraph(output, paragraph_lines)
            flush_list(output, list_kind, list_items)
            list_kind = None
            alt_text, image_path = image_match.groups()
            normalized_image_path = image_path.replace("\\", "/")
            figure_classes = ["figure"]
            if "assets/manual_beginner/" in normalized_image_path:
                figure_classes.append("figure--screenshot")
            elif "assets/qr/" in normalized_image_path:
                figure_classes.append("figure--qr")
            figure_class_attr = " ".join(figure_classes)
            output.append(
                f'<figure class="{figure_class_attr}">'
                f'<img src="{html.escape(image_path, quote=True)}" alt="{html.escape(alt_text, quote=True)}">'
                f"<figcaption>{html.escape(alt_text)}</figcaption>"
                "</figure>"
            )
            continue

        heading_match = re.fullmatch(r"(#{1,3})\s+(.*)", stripped)
        if heading_match:
            flush_paragraph(output, paragraph_lines)
            flush_list(output, list_kind, list_items)
            list_kind = None
            hashes, heading_text = heading_match.groups()
            level = len(hashes)
            output.append(f"<h{level}>{parse_inline(heading_text)}</h{level}>")
            continue

        ordered_match = re.fullmatch(r"\d+\.\s+(.*)", stripped)
        if ordered_match:
            flush_paragraph(output, paragraph_lines)
            if list_kind not in {None, "ol"}:
                flush_list(output, list_kind, list_items)
            list_kind = "ol"
            list_items.append(parse_inline(ordered_match.group(1)))
            continue

        unordered_match = re.fullmatch(r"-\s+(.*)", stripped)
        if unordered_match:
            flush_paragraph(output, paragraph_lines)
            if list_kind not in {None, "ul"}:
                flush_list(output, list_kind, list_items)
            list_kind = "ul"
            list_items.append(parse_inline(unordered_match.group(1)))
            continue

        if list_kind:
            flush_list(output, list_kind, list_items)
            list_kind = None

        paragraph_lines.append(stripped)

    flush_paragraph(output, paragraph_lines)
    flush_list(output, list_kind, list_items)
    return "\n".join(output)


def build_html_document(doc: DocSpec, body_html: str, *, base_href: str | None) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    base_tag = f'<base href="{html.escape(base_href, quote=True)}">' if base_href else ""
    return f"""<!DOCTYPE html>
<html lang=\"ja\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    {base_tag}
    <title>{html.escape(doc.title)}</title>
    <style>
        :root {{
            --ink: #1f2937;
            --muted: #5b6472;
            --line: #d6dbe4;
            --accent: #0f766e;
            --accent-soft: #ecfdf5;
            --paper: #ffffff;
            --page: #eef3f9;
            --shadow: rgba(15, 23, 42, 0.08);
            --code: #0f172a;
            --code-bg: #f8fafc;
        }}
        * {{ box-sizing: border-box; }}
        html {{ background: var(--page); }}
        body {{ margin: 0; background: var(--page); color: var(--ink); font-family: \"BIZ UDPGothic\", \"Yu Gothic UI\", Meiryo, sans-serif; line-height: 1.78; }}
        .toolbar {{ position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 24px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,0.94); backdrop-filter: blur(8px); }}
        .toolbar__title {{ font-size: 15px; font-weight: 700; letter-spacing: .02em; }}
        .toolbar__meta {{ color: var(--muted); font-size: 12px; }}
        .toolbar__actions {{ display: flex; gap: 10px; }}
        .button {{ appearance: none; border: 1px solid var(--accent); background: var(--accent); color: #fff; border-radius: 999px; padding: 10px 16px; font-size: 13px; font-weight: 700; cursor: pointer; }}
        .button--ghost {{ background: transparent; color: var(--accent); }}
        .page {{ width: min(100%, 980px); margin: 28px auto 56px; padding: 0 16px; }}
        .sheet {{ background: var(--paper); border-radius: 20px; box-shadow: 0 12px 32px var(--shadow); padding: 34px 42px 44px; }}
        .cover {{ margin-bottom: 28px; padding-bottom: 20px; border-bottom: 2px solid var(--line); }}
        .cover__badge {{ display: inline-block; margin-bottom: 12px; padding: 6px 12px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .02em; }}
        .cover h1 {{ margin: 0 0 10px; font-size: 32px; line-height: 1.3; color: #0f172a; }}
        .cover__subtitle {{ margin: 0 0 8px; color: var(--muted); font-size: 15px; }}
        .cover__meta {{ margin: 0; color: var(--muted); font-size: 12px; }}
        .print-tip {{ margin: 0 0 24px; padding: 12px 14px; border: 1px solid #b7d7d1; border-radius: 14px; background: #f0fdfa; color: #115e59; font-size: 13px; }}
        h2, h3, figure, pre {{ break-inside: avoid; page-break-inside: avoid; }}
        h2 {{ margin: 28px 0 14px; padding: 12px 16px; border-left: 6px solid var(--accent); background: var(--accent-soft); color: #0f172a; font-size: 24px; line-height: 1.45; break-after: avoid-page; page-break-after: avoid; }}
        h3 {{ margin: 26px 0 10px; color: #0f172a; font-size: 20px; line-height: 1.45; break-after: avoid-page; page-break-after: avoid; }}
        p {{ margin: 0 0 12px; font-size: 15px; }}
        ol, ul {{ margin: 0 0 16px 1.5em; padding: 0; }}
        li {{ margin-bottom: 6px; padding-left: 4px; }}
        p, li {{ orphans: 2; widows: 2; }}
        code {{ padding: 0.08em 0.35em; border-radius: 6px; background: #eef2ff; color: #1d4ed8; font-family: Consolas, \"Cascadia Code\", monospace; font-size: 0.95em; }}
        pre {{ margin: 0 0 18px; padding: 16px 18px; overflow: auto; border: 1px solid var(--line); border-radius: 14px; background: var(--code-bg); }}
        pre code {{ padding: 0; background: transparent; color: var(--code); font-size: 13px; white-space: pre-wrap; }}
        a {{ color: #0b57d0; text-decoration: none; }}
        strong {{ color: #0f172a; }}
        figure {{ margin: 18px 0 14px; border: 1px solid var(--line); border-radius: 16px; overflow: hidden; background: #fff; }}
        figure img {{ display: block; width: 100%; height: auto; background: #f8fafc; }}
        .figure--screenshot {{ max-width: 820px; margin-left: auto; margin-right: auto; }}
        .figure--screenshot img {{ max-height: 72vh; object-fit: contain; }}
        .figure--qr {{ max-width: 420px; margin-left: auto; margin-right: auto; }}
        .figure--qr img {{ padding: 18px; object-fit: contain; }}
        figcaption {{ padding: 10px 14px; border-top: 1px solid var(--line); background: #f8fafc; color: var(--muted); font-size: 13px; }}
        .footer-note {{ margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
        @page {{ size: A4; margin: 10mm 11mm 12mm; }}
        @media print {{
            html, body {{ background: #fff; }}
            .toolbar {{ display: none; }}
            .page {{ width: auto; margin: 0; padding: 0; }}
            .sheet {{ box-shadow: none; border-radius: 0; padding: 0; }}
            figure {{ margin: 10px 0 12px; }}
            .figure--screenshot {{ max-width: 168mm; }}
            .figure--screenshot img {{ max-height: 170mm; }}
            .figure--qr {{ max-width: 74mm; }}
            .figure--qr img {{ max-height: 74mm; padding: 10px; }}
            a {{ color: inherit; text-decoration: none; }}
        }}
    </style>
</head>
<body>
    <div class=\"toolbar\">
        <div>
            <div class=\"toolbar__title\">資料ビュー</div>
            <div class=\"toolbar__meta\">{html.escape(doc.title)} / Generated from {html.escape(doc.source)} / {generated_at}</div>
        </div>
        <div class=\"toolbar__actions\">
            <button class=\"button button--ghost\" type=\"button\" onclick=\"window.print()\">印刷</button>
            <button class=\"button\" type=\"button\" onclick=\"window.scrollTo({{ top: 0, behavior: 'smooth' }})\">先頭へ</button>
        </div>
    </div>
    <div class=\"page\">
        <article class=\"sheet\">
            <header class=\"cover\">
                <div class=\"cover__badge\">{html.escape(doc.badge)}</div>
                <h1>{html.escape(doc.title)}</h1>
                <p class=\"cover__subtitle\">{html.escape(doc.subtitle)}</p>
                <p class=\"cover__meta\">Generated from {html.escape(doc.source)} / {generated_at}</p>
            </header>
            <div class=\"print-tip\">PDF 化するときは A4 でそのまま印刷できます。見出し、図、コードブロックが崩れにくく、改ページの空きが大きくなりすぎないように調整しています。</div>
            {body_html}
            <div class=\"footer-note\">Source: {html.escape(doc.source)} / Generated by build_docs.py</div>
        </article>
    </div>
</body>
</html>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def strip_leading_h1(body_html: str) -> str:
    return re.sub(r"^\s*<h1>.*?</h1>\s*", "", body_html, count=1, flags=re.DOTALL)


def render_doc_html(doc: DocSpec, *, base_href: str | None, output_path: Path) -> None:
    source_path = PROJECT_ROOT / doc.source
    body_html = render_markdown(source_path.read_text(encoding="utf-8"))
    body_html = strip_leading_h1(body_html)
    document_html = build_html_document(doc, body_html, base_href=base_href)
    write_text(output_path, document_html)


def print_pdf(edge_path: Path, html_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    temp_pdf_path = pdf_path.with_name(f"{pdf_path.stem}.tmp.pdf")
    if temp_pdf_path.exists():
        temp_pdf_path.unlink()
    command = [
        str(edge_path),
        "--headless",
        "--disable-gpu",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=4000",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={temp_pdf_path}",
        html_path.as_uri(),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Edge timed out while generating {pdf_path.name}") from error
    if completed.returncode != 0:
        raise RuntimeError(f"Edge failed for {pdf_path.name} with exit code {completed.returncode}")

    try:
        os.replace(temp_pdf_path, pdf_path)
    except PermissionError:
        fallback_path = pdf_path.with_name(f"{pdf_path.stem}.updated.pdf")
        if fallback_path.exists():
            fallback_path.unlink()
        os.replace(temp_pdf_path, fallback_path)
        print(f"Locked target skipped, wrote: {fallback_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge-path", default=None)
    args = parser.parse_args()

    edge_path = resolve_edge_path(args.edge_path)
    BUILD_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_base_href = PROJECT_ROOT.resolve().as_uri().rstrip("/") + "/"

    for doc in DOCS:
        build_html_path = BUILD_DOCS_DIR / (Path(doc.source).stem + ".html")
        render_doc_html(doc, base_href=file_base_href, output_path=build_html_path)
        print_pdf(edge_path, build_html_path, PROJECT_ROOT / doc.pdf)
        if doc.html_output:
            render_doc_html(doc, base_href=None, output_path=PROJECT_ROOT / doc.html_output)
        print(f"Generated: {doc.pdf}")


if __name__ == "__main__":
    main()