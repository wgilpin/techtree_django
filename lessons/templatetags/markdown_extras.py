"""Custom template tags and filters for Markdown conversion."""

import re
import markdown
import uuid  # Use uuid for unique placeholders
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()


def isolate_latex(text):
    """
    Isolates LaTeX blocks ($...$ and $$...$$) using unique placeholders.
    Returns the modified text and a dictionary mapping placeholders to original LaTeX blocks.
    """
    latex_map = {}

    def replace_latex(match):
        latex_block = match.group(0)
        # Use a simpler placeholder format without underscores
        placeholder = f"LATEXBLOCK{uuid.uuid4().hex}"
        latex_map[placeholder] = latex_block
        return placeholder

    # Process display math ($$ ... $$) first
    text = re.sub(r"\$\$(.*?)\$\$", replace_latex, text, flags=re.DOTALL)
    # Process inline math ($ ... $)
    text = re.sub(r"\$(.*?)\$", replace_latex, text, flags=re.DOTALL)

    return text, latex_map


def restore_latex(html, latex_map):
    """Restores the original LaTeX blocks from placeholders."""
    for placeholder, latex_block in latex_map.items():
        # Use a lambda in re.sub to treat latex_block as a literal replacement string
        html = re.sub(
            rf"<p>{placeholder}</p>|{placeholder}", lambda match: latex_block, html
        )
    return html


@register.filter(name="markdownify")
@stringfilter
def markdownify(value: str) -> str:
    """
    Converts Markdown to HTML, preserving LaTeX blocks untouched.
    Input 'value' is assumed to have correct LaTeX syntax already fixed by the view.
    """
    # 1. Isolate LaTeX
    text_without_latex, latex_map = isolate_latex(value)

    # 2. Convert the remaining text (without LaTeX) to HTML
    html_without_latex = markdown.markdown(
        text_without_latex,
        extensions=[
            "markdown.extensions.fenced_code",
            "markdown.extensions.tables",
        ],
        # Ensure output format is html, not xhtml which might cause issues
        output_format="html",
    )

    # 3. Restore the original LaTeX blocks
    html = restore_latex(html_without_latex, latex_map)

    return mark_safe(html)


@register.filter(name="markdownify_chat")
@stringfilter
def markdownify_chat(value: str) -> str:
    """
    Converts Markdown to HTML for chat, preserving LaTeX blocks untouched.
    Input 'value' is assumed to have correct LaTeX syntax already fixed by the view.
    """
    # 1. Isolate LaTeX
    text_without_latex, latex_map = isolate_latex(value)

    # 2. Convert the remaining text (without LaTeX) to HTML
    html_without_latex = markdown.markdown(
        text_without_latex,
        extensions=[
            "markdown.extensions.fenced_code",
            "markdown.extensions.tables",
            "markdown.extensions.nl2br",  # Keep nl2br for chat
        ],
        output_format="html",
    )

    # 3. Restore the original LaTeX blocks
    html = restore_latex(html_without_latex, latex_map)

    return mark_safe(html)
