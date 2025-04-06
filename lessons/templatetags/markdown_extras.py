"""
Custom template tags and filters for Markdown conversion.

Provides filters to convert Markdown text to HTML, with special handling
for fenced code blocks (```) and LaTeX math expressions ($...$ and $$...$$).
"""

import re
import sys # Add this import
import markdown
import uuid  # Use uuid for unique placeholders
import html # Add this import
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()


# --- Code Block Handling ---

def isolate_code_blocks(text: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """
    Isolates fenced code blocks (```lang\ncode\n```) using unique placeholders.

    Args:
        text: The input string containing markdown and potentially code blocks.

    Returns:
        A tuple containing:
            - The text with code blocks replaced by placeholders.
            - A dictionary mapping placeholders to tuples of (language, code_content).
              Language can be an empty string if not specified.
    """
    code_map: dict[str, tuple[str, str]] = {}

    def replace_code(match: re.Match) -> str:
        """Replaces a matched code block with a placeholder."""
        language = match.group(1).strip()
        code_content = match.group(2) # Keep original indentation and newlines
        placeholder = f"CODEBLOCK{uuid.uuid4().hex}"
        code_map[placeholder] = (language, code_content)
        return placeholder

    # Regex to find ```optional_lang\n(content)\n``` blocks where ``` is on its own line.
    # DOTALL allows '.' to match newlines within the code block
    # MULTILINE allows ^ and $ to match start/end of lines
    # Non-greedy match (.*?) for content ensures it stops at the first ^```$
    # Use named groups 'lang' and 'code'. Match ``` at start of line.
    # Use (?:.|\n)*? for non-greedy multi-line content matching.
    # Match closing ``` at start of line. Requires re.MULTILINE flag only.
    code_block_pattern = r"^```(?P<lang>\w*)\n(?P<code>(?:.|\n)*?)\n^```$"
    processed_text = re.sub(code_block_pattern, replace_code, text, flags=re.MULTILINE)

    return processed_text, code_map


def restore_code_blocks(html_text: str, code_map: dict[str, tuple[str, str]]) -> str:
    """
    Restores the original code blocks from placeholders into formatted HTML.

    Args:
        html_text: The HTML string processed by markdown, containing placeholders.
        code_map: The dictionary mapping placeholders to (language, code_content).

    Returns:
        The HTML string with code blocks properly formatted using <pre><code>.
    """
    for placeholder, (language, code_content) in code_map.items():
        # Escape the code content to prevent XSS and render correctly
        escaped_code = html.escape(code_content)
        # Determine the class attribute for the <code> tag
        lang_class = f' class="language-{language}"' if language else ""
        # Format the code block using <pre> and <code>
        code_html = f'<pre><code{lang_class}>{escaped_code}</code></pre>'

        # Replace the placeholder. Handle cases where markdown might wrap it in <p> tags.
        # Use a lambda to treat code_html as a literal replacement string.
        html_text = re.sub(
            rf"<p>{placeholder}</p>|{placeholder}", lambda match: code_html, html_text
        )
    return html_text

# --- LaTeX Handling ---
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
    print("\n--- Entering restore_latex ---", file=sys.stderr)
    print(f"Initial HTML:\n{html}\n", file=sys.stderr)
    print(f"Latex Map: {latex_map}\n", file=sys.stderr)
    for placeholder, latex_block in latex_map.items():
        print(f"Processing placeholder: {placeholder}", file=sys.stderr)
        print(f"  Original latex_block from map: {repr(latex_block)}", file=sys.stderr)

        # 1. Convert DB double backslashes to the single backslashes MathJax needs.
        mathjax_ready_block = latex_block.replace('\\\\', '\\')
        print(f"  mathjax_ready_block (\\\\ -> \\): {repr(mathjax_ready_block)}", file=sys.stderr)

        # 2. Prepare for re.sub's string replacement processing by escaping backslashes again.
        # This ensures re.sub interprets \\f as \f, not a form feed or other escape.
        sub_replacement_string = mathjax_ready_block.replace('\\', '\\\\')
        print(f"  sub_replacement_string (\\ -> \\\\ for re.sub): {repr(sub_replacement_string)}", file=sys.stderr)

        # 3. Replace placeholder using the prepared string (NO lambda).
        print(f"  HTML before re.sub for {placeholder}:\n{html}\n", file=sys.stderr)
        html_before = html
        # re.sub will process the \\f back to \f during substitution.
        html = re.sub(rf"<p>{placeholder}</p>|{placeholder}", sub_replacement_string, html)
        if html == html_before:
            print(f"  WARNING: No replacement occurred for {placeholder}", file=sys.stderr)
        else:
            print(f"  HTML after re.sub for {placeholder}:\n{html}\n", file=sys.stderr)
    print("--- Exiting restore_latex ---", file=sys.stderr)
    return html


# --- Modified Filters ---

@register.filter(name="markdownify")
@stringfilter
def markdownify(value: str) -> str:
    """
    Converts a Markdown string into HTML.

    This filter processes Markdown text, handling fenced code blocks and LaTeX
    math expressions separately to ensure correct rendering.

    Args:
        value: The input string containing Markdown text.

    Returns:
        A safe HTML string representing the rendered content.
    """
    print("\n--- Entering markdownify ---", file=sys.stderr)
    print(f"Original value:\n{repr(value)}\n", file=sys.stderr)
    # 1. Isolate Code Blocks first
    text_without_code, code_map = isolate_code_blocks(value)
    print(f"Text after isolate_code_blocks:\n{repr(text_without_code)}\n", file=sys.stderr)
    print(f"Code Map: {code_map}\n", file=sys.stderr)
    # 2. Isolate LaTeX from the remaining text
    text_without_code_latex, latex_map = isolate_latex(text_without_code)
    print(f"Text after isolate_latex:\n{repr(text_without_code_latex)}\n", file=sys.stderr)
    print(f"Latex Map: {latex_map}\n", file=sys.stderr)

    # 3. Convert the remaining text to HTML (NO fenced_code extension)
    print("Calling markdown.markdown...", file=sys.stderr)
    html_intermediate = markdown.markdown(
        text_without_code_latex,
        extensions=[
            # "markdown.extensions.fenced_code", # REMOVED
            "markdown.extensions.tables",
        ],
        output_format="html",
    )
    print(f"HTML after markdown.markdown:\n{html_intermediate}\n", file=sys.stderr)

    # 4. Restore LaTeX blocks
    print("Calling restore_latex...", file=sys.stderr)
    html_with_latex = restore_latex(html_intermediate, latex_map)
    print(f"HTML after restore_latex:\n{html_with_latex}\n", file=sys.stderr)
    # 5. Restore Code blocks
    print("Calling restore_code_blocks...", file=sys.stderr)
    final_html = restore_code_blocks(html_with_latex, code_map)
    print(f"Final HTML after restore_code_blocks:\n{final_html}\n", file=sys.stderr)
    print("--- Exiting markdownify ---", file=sys.stderr)

    return mark_safe(final_html)


@register.filter(name="markdownify_chat")
@stringfilter
def markdownify_chat(value: str) -> str:
    """
    Converts a Markdown string into HTML suitable for chat messages.

    Similar to `markdownify`, but includes the `nl2br` extension to convert
    newlines into <br> tags, which is common for chat interfaces.

    Args:
        value: The input string containing Markdown text.

    Returns:
        A safe HTML string representing the rendered content with line breaks.
    """
    # 1. Isolate Code Blocks first
    text_without_code, code_map = isolate_code_blocks(value)
    # 2. Isolate LaTeX from the remaining text
    text_without_code_latex, latex_map = isolate_latex(text_without_code)

    # 3. Convert the remaining text to HTML (NO fenced_code extension)
    html_intermediate = markdown.markdown(
        text_without_code_latex,
        extensions=[
            # "markdown.extensions.fenced_code", # REMOVED
            "markdown.extensions.tables",
            "markdown.extensions.nl2br", # Keep nl2br for chat
        ],
        output_format="html",
    )

    # 4. Restore LaTeX blocks
    html_with_latex = restore_latex(html_intermediate, latex_map)
    # 5. Restore Code blocks
    final_html = restore_code_blocks(html_with_latex, code_map)

    return mark_safe(final_html)
