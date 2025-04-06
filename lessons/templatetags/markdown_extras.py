"""
Custom template tags and filters for Markdown conversion.

Provides filters to convert Markdown text to HTML, with special handling
for fenced code blocks (```) and LaTeX math expressions ($...$ and $$...$$).
"""

import html
import re
import sys # Keep for restore_latex logging
import uuid
import markdown
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()


# --- LaTeX Handling (Keep Existing) ---
def isolate_latex(text):
    """
    Isolates LaTeX blocks ($...$ and $$...$$) using unique placeholders.
    Returns the modified text and a dictionary mapping placeholders to original LaTeX blocks.
    """
    latex_map = {}

    def replace_latex(match):
        latex_block = match.group(0)
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

    for placeholder, latex_block in latex_map.items():
        print(f"Processing placeholder: {placeholder}", file=sys.stderr)
        print(f"  Original latex_block: {repr(latex_block)}", file=sys.stderr)

        # SUPER DIRECT APPROACH FOR ALIGNED ENVIRONMENT
        if "\\begin{aligned}" in latex_block:
            print(f"  Found aligned environment", file=sys.stderr)

            # Replace \\n with actual newlines
            fixed_latex = latex_block.replace("\\n", "\n")
            print(f"  After \\n -> newline: {repr(fixed_latex)}", file=sys.stderr)

            # Replace \\begin with \begin and \\end with \end
            fixed_latex = fixed_latex.replace("\\\\begin", "\\begin").replace(
                "\\\\end", "\\end"
            )
            print(f"  After \\\\begin -> \\begin: {repr(fixed_latex)}", file=sys.stderr)

            # Replace \\\\ with \\ for line breaks
            fixed_latex = fixed_latex.replace("\\\\\\\\", "\\\\")
            print(f"  After \\\\\\\\ -> \\\\: {repr(fixed_latex)}", file=sys.stderr)

            # Replace remaining \\ with \ for math operators
            # Use regex with negative lookahead to avoid replacing \\ at end or before newline
            fixed_latex = re.sub(r"\\\\(?!$|\\n|\n)", r"\\", fixed_latex)
            print(f"  After careful \\\\ -> \\: {repr(fixed_latex)}", file=sys.stderr)

            mathjax_ready_block = fixed_latex
        else:
            # For other LaTeX, convert all double backslashes to single backslashes
            mathjax_ready_block = latex_block.replace("\\\\", "\\")

        print(f"  Final mathjax_ready_block: {repr(mathjax_ready_block)}", file=sys.stderr)

        # Replace the placeholder in the HTML
        # Use a lambda to ensure the replacement is treated as a literal string
        html = re.sub(
            rf"<p>{placeholder}</p>|{placeholder}", lambda m: mathjax_ready_block, html
        )

    print("--- Exiting restore_latex ---", file=sys.stderr)
    return html


# --- Refactored Filters ---

@register.filter(name="markdownify")
@stringfilter
def markdownify(value: str) -> str:
    """
    Converts a Markdown string into HTML.
    Handles fenced code blocks and LaTeX math expressions separately using placeholders.
    """
    print(f"\n--- Entering markdownify ---")
    print(f"Original value: {repr(value)}")

    code_block_placeholders = {} # Stores {start_placeholder: raw_code_content}

    def replace_code_delimiters(match: re.Match) -> str:
        """Replaces ```lang\\ncode...``` with start/end placeholders."""
        lang = match.group('lang').strip()
        # IMPORTANT: Keep raw code content with \\n escapes
        raw_code_content = match.group('code')
        block_uuid = uuid.uuid4().hex
        start_placeholder = f"CODEBLOCK_START_{lang}_{block_uuid}_" # Underscore suffix for easier regex
        end_placeholder = f"_CODEBLOCK_END_{block_uuid}"
        # Store the raw content associated with the start placeholder
        code_block_placeholders[start_placeholder] = raw_code_content
        print(f"  Replacing code block. Lang: {lang}, UUID: {block_uuid}. Storing raw content: {repr(raw_code_content)}")
        # Return only placeholders, content is stored separately
        return f"{start_placeholder}{end_placeholder}"

    # 1. Replace code block delimiters with placeholders, storing content separately
    # Regex to find blocks starting with optional whitespace then ```lang followed by literal \\n.
    # Use \A for start of string OR \n for start of line.
    # Use DOTALL for content, MULTILINE for ^ anchors on closing ```.
    code_block_pattern = r"(?:\A|\n)\s*```(?P<lang>\w*)\\n(?P<code>.*?)^\s*```\s*$" # Match literal \\n after lang
    text_with_code_placeholders = re.sub(
        code_block_pattern, replace_code_delimiters, value, flags=re.DOTALL | re.MULTILINE
    )
    print(f"Text after replacing code delimiters: {repr(text_with_code_placeholders)}")
    print(f"Stored code content map: {code_block_placeholders}")

    # Check if any replacements happened
    if value == text_with_code_placeholders and "```" in value: # Added check for ``` presence
        print("  WARNING: No code block delimiters were replaced. Check regex and input.")
        # Attempt a simpler pattern just in case (less strict)
        print("  Trying simpler regex pattern...")
        simple_pattern = r"```(?P<lang>\w*)\\n(?P<code>.*?)```"
        text_with_code_placeholders = re.sub(
            simple_pattern, replace_code_delimiters, value, flags=re.DOTALL
        )
        print(f"  Text after simpler regex attempt: {repr(text_with_code_placeholders)}")
        print(f"  Stored code content map after simpler attempt: {code_block_placeholders}")


    # 2. Isolate LaTeX from the remaining text (which now has code placeholders)
    text_without_latex, latex_map = isolate_latex(text_with_code_placeholders)
    print(f"Text after isolate_latex: {repr(text_without_latex)}")
    print(f"Latex Map: {latex_map}")

    # 3. Convert the main text to HTML (placeholders are treated as text)
    # Replace \\n with \n for main markdown content *before* conversion
    text_to_render = text_without_latex.replace("\\n", "\n")
    print(f"Text sent to markdown.markdown: {repr(text_to_render)}")
    html_intermediate = markdown.markdown(
        text_to_render,
        extensions=["markdown.extensions.tables"], # No fenced_code needed
        output_format="html",
    )
    print(f"HTML after markdown.markdown: {html_intermediate}")

    # 4. Restore LaTeX blocks first
    html_with_latex = restore_latex(html_intermediate, latex_map)
    print(f"HTML after restore_latex: {html_with_latex}")

    # 5. Restore Code blocks using the stored content
    final_html = html_with_latex
    # Find start placeholders and insert the formatted code block
    for start_placeholder, raw_code_content in code_block_placeholders.items():
        match = re.match(r"CODEBLOCK_START_(?P<lang>\w*)_(?P<uuid>[a-f0-9]+)_", start_placeholder)
        if match:
            lang = match.group('lang')
            uuid_val = match.group('uuid')
            end_placeholder = f"_CODEBLOCK_END_{uuid_val}"

            print(f"  Restoring code block. Lang: {lang}, UUID: {uuid_val}")
            print(f"  Raw Code Content: {repr(raw_code_content)}")

            # Process the stored raw code content: replace \\n, trim, escape
            # IMPORTANT: Replace \\n from the original raw content here
            code_with_newlines = raw_code_content.replace('\\n', '\n')
            trimmed_code = code_with_newlines.strip()
            escaped_code = html.escape(trimmed_code)
            lang_class = f' class="language-{lang}"' if lang else ""
            code_html = f'<pre><code{lang_class}>{escaped_code}</code></pre>'
            print(f"  Generated code_html: {code_html}")

            # Replace the START...END placeholder sequence with the generated HTML
            # Need to handle potential <p> tags around placeholders
            # Escape placeholders for regex safety
            start_safe = re.escape(start_placeholder)
            end_safe = re.escape(end_placeholder)
            placeholder_pattern = rf"<p>\s*{start_safe}\s*{end_safe}\s*</p>|{start_safe}\s*{end_safe}"

            final_html_before = final_html
            final_html = re.sub(placeholder_pattern, lambda m: code_html, final_html)

            if final_html == final_html_before:
                 print(f"  WARNING: Code block for {start_placeholder} not replaced.")
            else:
                 print(f"  HTML after replacing {start_placeholder}: {final_html}")
        else:
            print(f"  ERROR: Could not parse start placeholder {start_placeholder}")


    print(f"Final HTML: {final_html}")
    print("--- Exiting markdownify ---")
    return mark_safe(final_html)


@register.filter(name="markdownify_chat")
@stringfilter
def markdownify_chat(value: str) -> str:
    """
    Converts a Markdown string into HTML suitable for chat messages.
    Handles fenced code blocks and LaTeX math expressions separately using placeholders.
    Includes nl2br extension for chat formatting.
    """
    print(f"\n--- Entering markdownify_chat ---")
    print(f"Original value: {repr(value)}")

    code_block_placeholders = {} # Stores {start_placeholder: raw_code_content}

    def replace_code_delimiters(match: re.Match) -> str:
        """Replaces ```lang\\ncode\\n``` with start/end placeholders."""
        lang = match.group('lang').strip()
        raw_code_content = match.group('code') # Includes \\n
        block_uuid = uuid.uuid4().hex
        start_placeholder = f"CODEBLOCK_START_{lang}_{block_uuid}_"
        end_placeholder = f"_CODEBLOCK_END_{block_uuid}"
        code_block_placeholders[start_placeholder] = raw_code_content
        print(f"  Replacing code block. Lang: {lang}, UUID: {block_uuid}. Storing raw content: {repr(raw_code_content)}")
        return f"{start_placeholder}{end_placeholder}"

    # 1. Replace code block delimiters
    # Use \A for start of string OR \n for start of line.
    code_block_pattern = r"(?:\A|\n)\s*```(?P<lang>\w*)\\n(?P<code>.*?)^\s*```\s*$" # Match literal \\n after lang
    text_with_code_placeholders = re.sub(
        code_block_pattern, replace_code_delimiters, value, flags=re.DOTALL | re.MULTILINE
    )
    print(f"Text after replacing code delimiters: {repr(text_with_code_placeholders)}")
    if value == text_with_code_placeholders and "```" in value:
        print("  WARNING: No code block delimiters were replaced in chat. Trying simpler regex...")
        simple_pattern = r"```(?P<lang>\w*)\\n(?P<code>.*?)```"
        text_with_code_placeholders = re.sub(
            simple_pattern, replace_code_delimiters, value, flags=re.DOTALL
        )
        print(f"  Text after simpler regex attempt: {repr(text_with_code_placeholders)}")


    # 2. Isolate LaTeX
    text_without_latex, latex_map = isolate_latex(text_with_code_placeholders)
    print(f"Text after isolate_latex: {repr(text_without_latex)}")

    # 3. Convert main text to HTML with nl2br
    # Replace \\n with \n for main markdown content *before* conversion
    text_to_render = text_without_latex.replace("\\n", "\n")
    print(f"Text sent to markdown.markdown: {repr(text_to_render)}")
    html_intermediate = markdown.markdown(
        text_to_render,
        extensions=["markdown.extensions.tables", "markdown.extensions.nl2br"], # Add nl2br
        output_format="html",
    )
    print(f"HTML after markdown.markdown: {html_intermediate}")

    # 4. Restore LaTeX blocks
    html_with_latex = restore_latex(html_intermediate, latex_map)
    print(f"HTML after restore_latex: {html_with_latex}")

    # 5. Restore Code blocks
    final_html = html_with_latex
    for start_placeholder, raw_code_content in code_block_placeholders.items():
        match = re.match(r"CODEBLOCK_START_(?P<lang>\w*)_(?P<uuid>[a-f0-9]+)_", start_placeholder)
        if match:
            lang = match.group('lang')
            uuid_val = match.group('uuid')
            end_placeholder = f"_CODEBLOCK_END_{uuid_val}"
            print(f"  Restoring code block. Lang: {lang}, UUID: {uuid_val}")

            code_with_newlines = raw_code_content.replace('\\n', '\n')
            trimmed_code = code_with_newlines.strip()
            escaped_code = html.escape(trimmed_code)
            lang_class = f' class="language-{lang}"' if lang else ""
            code_html = f'<pre><code{lang_class}>{escaped_code}</code></pre>'

            start_safe = re.escape(start_placeholder)
            end_safe = re.escape(end_placeholder)
            placeholder_pattern = rf"<p>\s*{start_safe}\s*{end_safe}\s*</p>|{start_safe}\s*{end_safe}"
            final_html = re.sub(placeholder_pattern, lambda m: code_html, final_html)
        else:
             print(f"  ERROR: Could not parse start placeholder {start_placeholder}")


    print(f"Final HTML: {final_html}")
    print("--- Exiting markdownify_chat ---")
    return mark_safe(final_html)
