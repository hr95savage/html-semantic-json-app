# HTML to Semantic JSON Extractor

Extracts semantic structure from rendered HTML files and converts them to a structured JSON format optimized for SEO analysis.

## Features

- Extracts source metadata (URL, title, canonical, meta description)
- Identifies main content area (prioritizing `<main>` or `[role="main"]`)
- Extracts semantic blocks in reading order:
  - Headings (h1-h6, role="heading")
  - Paragraphs
  - Lists (ordered/unordered)
  - CTAs (buttons, links)
  - Tables
  - FAQs (from `<details>` or disclosure patterns)
  - Accordions
  - Tabsets
- Excludes sitewide chrome (header, nav, footer)
- Excludes forms, images, scripts, styles, JSON-LD
- Deduplicates similar blocks
- Validates single H1 requirement

## Installation

1. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

```bash
python html_to_semantic_json.py <html_file> [output_file]
```

Examples:
```bash
# Output to stdout
python html_to_semantic_json.py rendered_page.html

# Save to a specific file
python html_to_semantic_json.py rendered_page.html output.json

# Save to output folder
python html_to_semantic_json.py rendered_page.html output/page.json
```

If no output file is specified, JSON is printed to stdout. You can also redirect stdout:
```bash
python html_to_semantic_json.py rendered_page.html > output/page.json
```

## Output Format

```json
{
  "source": {
    "url": "https://example.com/",
    "title": "Page Title",
    "canonical": "https://example.com/",
    "meta_description": "Page description"
  },
  "blocks": [
    {
      "type": "heading",
      "level": 1,
      "text": "Main Heading"
    },
    {
      "type": "paragraph",
      "text": "Paragraph text..."
    },
    {
      "type": "list",
      "ordered": false,
      "items": ["Item 1", "Item 2"]
    },
    {
      "type": "cta",
      "text": "Click Here",
      "href": "https://example.com/action"
    },
    {
      "type": "faq",
      "question": "What is this?",
      "answer_blocks": [...]
    },
    {
      "type": "accordion",
      "title": "Section Title",
      "content_blocks": [...]
    },
    {
      "type": "tabset",
      "tabs": [
        {
          "title": "Tab 1",
          "content_blocks": [...]
        }
      ]
    },
    {
      "type": "table",
      "rows": [
        ["Header 1", "Header 2"],
        ["Data 1", "Data 2"]
      ]
    }
  ]
}
```

## Requirements

- Python 3.7+
- beautifulsoup4
- lxml

## Notes

- The extractor works on post-JS-execution HTML (rendered HTML)
- Main content is selected using text density analysis if no `<main>` tag is found
- Exactly one H1 is enforced (first H1 is kept if multiple exist)
- Form elements and their labels/placeholders are excluded
- Images, SVGs, and alt text are excluded
- Interactive content (FAQs, accordions, tabs) is extracted if present in the DOM
