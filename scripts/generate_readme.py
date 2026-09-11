#!/usr/bin/env python3
"""
Generate bilingual README files from JSON data.
Primary language is Persian (README.md). English is secondary (README-en.md).
Each README links to the other.
Structure of each generated file:
  1. before.{lang}.md
  2. Summary table (name / style / weights / preview / details-link)
  3. Detailed sections for every font (## Name + fields + image + ---)
  4. after.{lang}.md
Inputs:
    data/config.json  - languages and output settings
    data/fonts.json   - font objects (plain JSON array)
    data/sections/    - before/after markdown snippets per language
Usage:
    python scripts/generate_readme.py
    python scripts/generate_readme.py --only fa
Standard library only.
"""
import argparse
import json
import re
import sys
from pathlib import Path
# ---------------------------------------------------------------------------
# Configurable defaults (edit these to change behaviour)
# ---------------------------------------------------------------------------
# Summary table columns (order matters)
SUMMARY_COLUMNS = [
    {
        "id": "preview-image",
        "title": {"en": "Preview", "fa": "پیش‌نمایش"},
        "align": "center",
        # "width": 140,
    },
    {
        "id": "name",
        "title": {"en": "Name", "fa": "نام"},
        # align omitted → follows the current language direction
    },
    {
        "id": "style",
        "title": {"en": "Style", "fa": "سبک"},
    },
    {
        "id": "weights",
        "title": {"en": "Weights", "fa": "وزن‌ها"},
        "type": "weights",
        "singular": {"en": "weight", "fa": "وزن"},
        "plural": {"en": "weights", "fa": "وزن"},
        "variableSuffix": {"en": "(variable)", "fa": "(متغیر)"},
    },
    {
        "id": "details",
        "title": {"en": "Details", "fa": "جزئیات"},
        "align": "center",
        "type": "anchor",
        "label": {"en": "<br><span style='font-size: 1.6rem'>↩</span>", "fa": "<br><span style='font-size: 1.6rem'>↩</span>"},
    },
]
# Fields shown in the per-font detail blocks (order matters).
# Omit "woff2" to keep it out by default.
DETAIL_FIELDS = [
    "description",
    "Designer",
    "style",
    "license",
    "supportedLanguages",
    "weights",
    "note",
    "source-link",
    "download-link",
]
# How link fields are labelled
LINK_LABELS = {
    "source-link": {"en": "Source", "fa": "منبع"},
    "download-link": {"en": "Download", "fa": "بارگیری"},
}
# Human-readable labels for other fields (used in detail blocks)
FIELD_LABELS = {
    "Designer": {"en": "Designer", "fa": "طراح"},
    "license": {"en": "License", "fa": "مجوز"},
    "description": {"en": "Description", "fa": "توضیحات"},
    "supportedLanguages": {"en": "Languages", "fa": "زبان‌ها"},
    "note": {"en": "Note", "fa": "یادداشت"},
    "family": {"en": "Family", "fa": "خانواده"},
    "style": {"en": "Style", "fa": "سبک"},
    "weights": {"en": "Weights", "fa": "وزن‌ها"},
}
# Human-readable names for language codes used in `supportedLanguages`.
# Values are keyed by README language and resolved like any other bilingual value.
LANGUAGE_NAMES = {
    "ar":  {"en": "Arabic",           "fa": "عربی"},
    "ckb": {"en": "Kurdish (Sorani)", "fa": "کردی سورانی"},
    "fa":  {"en": "Persian",          "fa": "فارسی"},
    "la":  {"en": "English",            "fa": "انگلیسی"},
    "ps":  {"en": "Pashto",           "fa": "پشتو"},
    "sd":  {"en": "Sindhi",           "fa": "سندی"},
    "ug":  {"en": "Uyghur",           "fa": "اویغوری"},
    "ur":  {"en": "Urdu",             "fa": "اردو"},
}
# Separator for joined list values, per README language
LIST_SEPARATOR = {"en": ", ", "fa": "، "}
# Primary / secondary language
PRIMARY_LANG = "fa"          # produces README.md
SECONDARY_LANG = "en"        # produces README-en.md
# Language switcher texts
LANG_SWITCH = {
    "fa": {"text": "English version", "url": "README-en.md"},
    "en": {"text": "نسخهٔ فارسی", "url": "README.md"},
}
# Text direction per language (overrides config.languages[].dir if set)
# Use "rtl" or "ltr"
LANG_DIR = {
    "fa": "rtl",
    "en": "ltr",
}
# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "data" / "config.json"
FONTS_FILE = ROOT / "data" / "fonts.json"
# Markdown table alignment separators.
# Also accept "ltr" / "rtl" as aliases for left / right so columns can
# control text direction in addition to visual alignment.
ALIGN_SEPARATORS = {
    "left": ":---",
    "ltr": ":---",
    "center": ":---:",
    "right": "---:",
    "rtl": "---:",
}
DIGIT_MAPS = {
    "persian": "۰۱۲۳۴۵۶۷۸۹",
    "arabic": "٠١٢٣٤٥٦٧٨٩",
}
def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)
def read_json(path: Path):
    if not path.exists():
        fail(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(
            f"Invalid JSON in {path.name} "
            f"(line {error.lineno}, column {error.colno}): {error.msg}"
        )
def read_section(path: Path) -> str:
    if not path.exists():
        fail(f"Missing section file: {path}")
    return path.read_text(encoding="utf-8").strip()
def localize_digits(text: str, lang_def: dict) -> str:
    kind = lang_def.get("digits", "latin")
    if kind == "latin":
        return text
    return text.translate(str.maketrans("0123456789", DIGIT_MAPS[kind]))
# ---------------------------------------------------------------------------
# Bilingual value handling
# ---------------------------------------------------------------------------
class Resolver:
    def __init__(self, language_codes):
        self.codes = set(language_codes)
    def check(self, value, context: str) -> None:
        if isinstance(value, dict):
            unknown = sorted(set(value) - self.codes)
            if unknown:
                fail(f"{context}: unknown language key(s): {', '.join(unknown)}")
            missing = sorted(self.codes - set(value))
            if missing:
                fail(f"{context}: missing translation for: {', '.join(missing)}")
    def resolve(self, value, lang: str) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            # Prefer exact language key, then any available value
            if lang in value and value[lang] is not None:
                return str(value[lang])
            # fallback order: fa → en → first value
            for fallback in ("fa", "en"):
                if fallback in value and value[fallback] is not None:
                    return str(value[fallback])
            return str(next(iter(value.values()), ""))
        return str(value)
def load_languages(config: dict) -> list:
    languages = config.get("languages")
    if not isinstance(languages, list) or not languages:
        fail("`config.languages` must be a non-empty list.")
    seen = []
    for item in languages:
        if not isinstance(item, dict):
            fail(f"Each language entry must be an object, got: {item!r}")
        code = item.get("code")
        output = item.get("output")
        if not code or not isinstance(code, str):
            fail(f"Language entry needs a string `code`: {item!r}")
        if not output or not isinstance(output, str):
            fail(f"Language '{code}' needs an `output` file name.")
        # Allow override from the top-level LANG_DIR map
        effective_dir = LANG_DIR.get(code, item.get("dir", "ltr"))
        if effective_dir not in ("ltr", "rtl"):
            fail(f"Language '{code}': invalid dir '{effective_dir}' (use ltr/rtl).")
        item["dir"] = effective_dir  # mutate so later code sees the effective value
        digits = item.get("digits", "latin")
        if digits not in ("latin", "persian", "arabic"):
            fail(
                f"Language '{code}': invalid digits '{digits}' "
                f"(use latin/persian/arabic)."
            )
        seen.append(code)
    duplicates = sorted({c for c in seen if seen.count(c) > 1})
    if duplicates:
        fail(f"Duplicate language code(s): {', '.join(duplicates)}")
    return languages
def load_sections(config: dict, languages: list) -> dict:
    sections_dir_value = config.get("sectionsDir", "data/sections")
    if not isinstance(sections_dir_value, str):
        fail("`config.sectionsDir` must be a string.")
    sections_dir = ROOT / sections_dir_value
    if not sections_dir.is_dir():
        fail(f"Sections directory not found: {sections_dir}")
    sections = {}
    for lang in languages:
        code = lang["code"]
        sections[code] = {
            "before": read_section(sections_dir / f"before.{code}.md"),
            "after": read_section(sections_dir / f"after.{code}.md"),
        }
    return sections
def load_fonts() -> list:
    fonts = read_json(FONTS_FILE)
    if not isinstance(fonts, list):
        fail("fonts.json must contain a JSON array of font objects.")
    if not fonts:
        fail("fonts.json is empty - nothing to render.")
    for index, font in enumerate(fonts, start=1):
        if not isinstance(font, dict):
            fail(f"fonts[{index}] must be an object.")
        if "name" not in font:
            fail(f"fonts[{index}] is missing required key 'name'.")
    return fonts
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    """Simple slug for anchor links (spaces → underscores)."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("_") or "font"
def font_anchor(font: dict) -> str:
    family = font.get("family")
    if isinstance(family, str) and family.strip():
        return re.sub(r"\s+", "_", family.strip().lower())
    name = font.get("name")
    if isinstance(name, dict):
        name = name.get("en") or next(iter(name.values()), "font")
    return slugify(str(name))
def md_escape(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "<br>").replace("|", "\\|")
def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
def wrap_url(url: str) -> str:
    url = url.strip()
    if any(ch in url for ch in " ()"):
        url = f"<{url}>"
    return url
def language_display_name(code: str, lang: str, resolver: Resolver) -> str:
    """Map a language code (e.g. 'ckb') to a readable name.
    Unknown codes are passed through unchanged, with a warning."""
    names = LANGUAGE_NAMES.get(code)
    if names is None:
        print(f"WARNING: unknown language code '{code}' in supportedLanguages",
              file=sys.stderr)
        return code
    return resolver.resolve(names, lang)
def display_name(font: dict, lang: str, resolver: Resolver) -> str:
    return resolver.resolve(font.get("name"), lang).strip() or "?"
def other_lang(lang: str) -> str:
    """Return the opposite of the primary/secondary language pair."""
    if lang == PRIMARY_LANG:
        return SECONDARY_LANG
    if lang == SECONDARY_LANG:
        return PRIMARY_LANG
    # Fallback for any unexpected language code
    return SECONDARY_LANG if lang == "fa" else PRIMARY_LANG
def bilingual_name(font: dict, lang: str, resolver: Resolver) -> tuple[str, str]:
    """Return (current_lang_name, other_lang_name). Empty string if missing."""
    current = display_name(font, lang, resolver)
    other = display_name(font, other_lang(lang), resolver)
    # Avoid showing the same name twice when both resolve to the same string
    if other and other != current:
        return current, other
    return current, ""
# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------
def build_weights_text(value: dict, col: dict, lang: str, lang_def: dict, resolver: Resolver) -> str:
    count = value.get("count", 1)
    unit_key = "singular" if count == 1 else "plural"
    unit = resolver.resolve(col.get(unit_key, {"en": "weight", "fa": "وزن"}), lang)
    text = f"{count} {unit}"
    if value.get("variable"):
        suffix = resolver.resolve(col.get("variableSuffix", {"en": "(variable)", "fa": "(متغیر)"}), lang)
        text += f" {suffix}"
    return localize_digits(text, lang_def)
def resolve_align(align_value, lang: str, lang_dir: str = "ltr") -> str:
    """Resolve column align.
    - plain string → same for all languages
    - dict → per-language value
    - None / omitted → follow the current language direction
      (rtl language → "rtl", ltr language → "left")
    """
    if isinstance(align_value, dict):
        if lang in align_value:
            return str(align_value[lang])
        for fallback in ("fa", "en"):
            if fallback in align_value:
                return str(align_value[fallback])
        return str(next(iter(align_value.values()), "left"))
    if align_value is None:
        # Default: match the reading direction of the current README language
        return "rtl" if lang_dir == "rtl" else "left"
    return str(align_value)
def build_summary_cell(
    col: dict, font: dict, lang: str, lang_def: dict, resolver: Resolver
) -> str:
    col_id = col["id"]
    col_type = col.get("type", "text")
    # align is only used for the markdown separator row; no per-cell dir wrappers
    if col_type == "anchor":
        label = resolver.resolve(col.get("label", {"en": "Details", "fa": "جزئیات"}), lang)
        anchor = font_anchor(font)
        return f"[{label}](#{anchor})"
    value = font.get(col_id)
    if value is None:
        return ""
    if col_type == "weights" or col_id == "weights":
        if not isinstance(value, dict):
            return ""
        return md_escape(build_weights_text(value, col, lang, lang_def, resolver))
    # preview-image
    if col_id.endswith("-image") or col_id == "preview-image":
        src = resolver.resolve(value, lang).strip()
        if not src:
            return ""
        alt = display_name(font, lang, resolver)
        width = col.get("width")
        if width:
            return (
                f'<img src="{html_escape(src)}" '
                f'width="{width}" alt="{html_escape(alt)}">'
            )
        return f"![{alt}]({wrap_url(src)})"
    # name column: current language first, other language on the next line (no parentheses)
    # Also embed a row anchor so detail headings can link back to this exact row.
    if col_id == "name":
        current, other = bilingual_name(font, lang, resolver)
        if not current:
            return ""
        row_id = f"row-{font_anchor(font)}"
        anchor_html = f'<a id="{row_id}"></a>'
        if other:
            # <br> keeps the second name on its own line inside the table cell
            return anchor_html + md_escape(f"{current}<br>{other}")
        return anchor_html + md_escape(current)
    # ordinary text / bilingual
    return md_escape(resolver.resolve(value, lang).strip())
def build_summary_table(
    fonts: list, lang_def: dict, resolver: Resolver
) -> str:
    lang = lang_def["code"]
    headers = []
    separators = []
    for col in SUMMARY_COLUMNS:
        headers.append(md_escape(resolver.resolve(col["title"], lang)))
        align = resolve_align(col.get("align"), lang, lang_def.get("dir", "ltr"))
        if align not in ALIGN_SEPARATORS:
            fail(f"Column '{col['id']}': invalid align '{align}'. "
                 f"Use one of: {', '.join(ALIGN_SEPARATORS)}")
        separators.append(ALIGN_SEPARATORS[align])
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separators) + " |",
    ]
    for font in fonts:
        cells = [
            build_summary_cell(col, font, lang, lang_def, resolver)
            for col in SUMMARY_COLUMNS
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
# ---------------------------------------------------------------------------
# Per-font detail blocks
# ---------------------------------------------------------------------------
def format_field_value(
    field: str, value, lang: str, lang_def: dict, resolver: Resolver
) -> str:
    """Return a ready-to-print markdown fragment for one field."""
    if value is None:
        return ""
    # Links (source / download) → special combined handling is done outside
    if field in ("source-link", "download-link"):
        return ""  # handled together later
    if field == "Designer":
        text = resolver.resolve(value, lang).strip()
        if not text:
            return ""
        label = resolver.resolve(FIELD_LABELS.get("Designer", "Designer"), lang)
        return f"**{label}:** {md_escape(text)}"
    if field == "supportedLanguages":
        if isinstance(value, list):
            names = [
                language_display_name(str(item).strip(), lang, resolver)
                for item in value
            ]
        else:
            # plain/bilingual string → split on commas, then map each part
            text = resolver.resolve(value, lang)
            names = [
                language_display_name(part.strip(), lang, resolver)
                for part in re.split(r"[,،]", text)
                if part.strip()
            ]
        names = [n for n in names if n]
        if not names:
            return ""
        separator = resolver.resolve(LIST_SEPARATOR, lang)
        label = resolver.resolve(
            FIELD_LABELS.get("supportedLanguages", "Languages"), lang
        )
        return f"**{label}:** {md_escape(separator.join(names))}"
    if field == "weights":
        if not isinstance(value, dict):
            return ""
        # reuse the weights formatter from summary
        fake_col = next((c for c in SUMMARY_COLUMNS if c["id"] == "weights"), {})
        text = build_weights_text(value, fake_col, lang, lang_def, resolver)
        label = resolver.resolve(FIELD_LABELS.get("weights", "Weights"), lang)
        return f"**{label}:** {md_escape(text)}"
    if field == "woff2":
        if not isinstance(value, dict) or not value:
            return ""
        items = [f"`{k}`: `{v}`" for k, v in sorted(value.items())]
        label = "WOFF2"
        return f"**{label}:**\n" + "\n".join(f"- {i}" for i in items)
    # generic bilingual / string field
    text = resolver.resolve(value, lang).strip()
    if not text:
        return ""
    label = resolver.resolve(
        FIELD_LABELS.get(field, field.replace("-", " ").title()), lang
    )
    return f"**{label}:** {md_escape(text)}"
def build_links_line(font: dict, lang: str, resolver: Resolver) -> str:
    parts = []
    for field in ("source-link", "download-link"):
        url = font.get(field)
        if not url or not isinstance(url, str) or not url.strip():
            continue
        label = resolver.resolve(LINK_LABELS.get(field, field), lang)
        parts.append(f"[{label}]({wrap_url(url.strip())})")
    if not parts:
        return ""
    return " - ".join(parts)
def build_font_details(
    fonts: list, lang_def: dict, resolver: Resolver
) -> str:
    lang = lang_def["code"]
    blocks = []
    for font in fonts:
        anchor = font_anchor(font)
        current = display_name(font, lang, resolver)
        # Bidirectional link: ↑ goes back to this font's row in the summary table
        title = f'[↑](#row-{anchor}) {current}'
        lines = [f'<a id="{anchor}"></a>', f"## {title}", ""]
        # ordered fields
        for field in DETAIL_FIELDS:
            if field in ("source-link", "download-link"):
                continue  # handled as a single links line
            rendered = format_field_value(
                field, font.get(field), lang, lang_def, resolver
            )
            if rendered:
                lines.append(rendered)
                lines.append("")
        # combined Source / Download line
        links = build_links_line(font, lang, resolver)
        if links:
            lines.append(links)
            lines.append("")
        # preview image again
        preview = font.get("preview-image")
        if preview:
            src = resolver.resolve(preview, lang).strip()
            if src:
                alt = current  # use current-language name for alt text
                lines.append(f"![{html_escape(alt)}]({wrap_url(src)})")
                lines.append("")
        lines.append("---")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------
def build_lang_switcher(lang: str) -> str:
    info = LANG_SWITCH.get(lang)
    if not info:
        return ""
    return f"**[{info['text']}]({info['url']})**\n"
def render_document(
    lang_def: dict,
    before: str,
    switcher: str,
    table: str,
    details: str,
    after: str,
) -> str:
    parts = []
    if lang_def.get("dir", "ltr") == "rtl":
        parts += ['<div dir="rtl">', ""]
    if before:
        parts += [before, ""]
    if switcher:
        parts += [switcher, ""]
    if table:
        parts += [table, ""]
    if details:
        parts += [details, ""]
    if after:
        parts += [after, ""]
    if lang_def.get("dir", "ltr") == "rtl":
        parts.append("</div>")
    return "\n".join(parts).rstrip() + "\n"
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate README files from data/fonts.json + data/config.json."
    )
    parser.add_argument(
        "--only",
        metavar="LANG",
        help="generate only the output of this language code (e.g. fa)",
    )
    args = parser.parse_args()
    config = read_json(CONFIG_FILE)
    if not isinstance(config, dict):
        fail("config.json must contain a JSON object.")
    languages = load_languages(config)
    codes = [lang["code"] for lang in languages]
    if args.only and args.only not in codes:
        fail(f"Unknown language '{args.only}'. Defined languages: {', '.join(codes)}")
    selected = [l for l in languages if not args.only or l["code"] == args.only]
    resolver = Resolver(codes)
    fonts = load_fonts()
    sections = load_sections(config, languages)
    # Force output names according to primary/secondary convention
    output_map = {
        PRIMARY_LANG: "README.md",
        SECONDARY_LANG: "README-en.md",
    }
    documents = []
    for lang_def in selected:
        lang = lang_def["code"]
        table = build_summary_table(fonts, lang_def, resolver)
        details = build_font_details(fonts, lang_def, resolver)
        switcher = build_lang_switcher(lang)
        content = render_document(
            lang_def,
            sections[lang]["before"],
            switcher,
            table,
            details,
            sections[lang]["after"],
        )
        out_name = output_map.get(lang, lang_def["output"])
        documents.append((ROOT / out_name, content))
    for path, content in documents:
        path.write_text(content, encoding="utf-8")
        print(f"OK: {path.name} written ({len(fonts)} fonts).")
if __name__ == "__main__":
    main()
