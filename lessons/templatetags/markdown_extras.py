"""Custom template tags and filters for Markdown conversion."""

import markdown
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(name='markdownify')
@stringfilter
def markdownify(value: str) -> str:
    """
    Converts a Markdown string into HTML.

    Uses the 'markdown' library with common extensions enabled.
    Marks the output as safe for HTML rendering.
    """
    # Enable common extensions for better formatting (e.g., tables, fenced code)
    # Use a more minimal set of extensions to avoid potential conflicts with LaTeX delimiters
    html = markdown.markdown(
        value,
        extensions=[
            'markdown.extensions.fenced_code', # Code blocks ```like this```
            'markdown.extensions.tables',      # Markdown tables
            'markdown.extensions.nl2br',       # Convert newlines to <br>
            # 'markdown.extensions.extra',     # Temporarily disable 'extra' to check for interference
        ]
    )
    return mark_safe(html)
