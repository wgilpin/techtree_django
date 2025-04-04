"""Custom template tags and filters for Markdown conversion."""

import re
import markdown
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()

def preprocess_latex(text):
    """
    Pre-process LaTeX blocks to ensure proper rendering.
    
    This function:
    1. Ensures each LaTeX block ($$...$$) is on its own line with proper spacing
    2. Adds HTML comments around LaTeX blocks to protect them from Markdown processing
    """
    # Pattern to find LaTeX blocks (both inline and display)
    display_math_pattern = r'(\$\$.*?\$\$)'
    
    # Function to process each match
    def process_display_math(match):
        math = match.group(1)
        # Ensure the block is surrounded by newlines
        if not math.startswith('\n'):
            math = '\n' + math
        if not math.endswith('\n'):
            math = math + '\n'
        # Return with HTML comments to protect from Markdown
        return f"\n<!--latex-block-->{math}<!--end-latex-block-->\n"
    
    # Replace all LaTeX blocks
    processed_text = re.sub(display_math_pattern, process_display_math, text, flags=re.DOTALL)
    return processed_text

def postprocess_latex(html):
    """
    Post-process HTML to remove protection comments around LaTeX blocks.
    """
    # Remove the protection comments
    html = html.replace('<!--latex-block-->', '')
    html = html.replace('<!--end-latex-block-->', '')
    return html

@register.filter(name='markdownify')
@stringfilter
def markdownify(value: str) -> str:
    """
    Converts a Markdown string into HTML for main content (e.g., exposition).
    
    Pre-processes LaTeX blocks to ensure proper rendering.
    """
    # Pre-process LaTeX blocks
    preprocessed = preprocess_latex(value)
    
    # Convert to HTML
    html = markdown.markdown(
        preprocessed,
        extensions=[
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'pymdownx.arithmatex',
        ],
        extension_configs={
            'pymdownx.arithmatex': {
                'generic': True,
                'smart_dollar': False
            }
        }
    )
    
    # Post-process to remove protection comments
    html = postprocess_latex(html)
    
    return mark_safe(html)

@register.filter(name='markdownify_chat')
@stringfilter
def markdownify_chat(value: str) -> str:
    """
    Converts a Markdown string into HTML specifically for chat messages.
    
    Includes nl2br to handle line breaks common in chat.
    """
    html = markdown.markdown(
        value,
        extensions=[
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'markdown.extensions.nl2br',
            'pymdownx.arithmatex',
        ],
        extension_configs={
            'pymdownx.arithmatex': {
                'generic': True,
                'smart_dollar': False
            }
        }
    )
    return mark_safe(html)
