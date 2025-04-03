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
            'pymdownx.arithmatex',             # Add Arithmatex back
            # 'markdown.extensions.extra',     # Keep disabled
        ],
        extension_configs={
            'pymdownx.arithmatex': {
                'generic': True  # Use generic mode for KaTeX/MathJax compatibility
            }
        }
        # Removed extension_configs for arithmatex to test default behavior
    )
    return mark_safe(html)
