# HTML to Semantic JSON Extractor - Plain English Explanation

## What This Script Does

This script takes a fully-rendered HTML page (after JavaScript has run) and extracts only the meaningful content, converting it into a clean JSON structure. Think of it as a smart content miner that ignores all the website "chrome" (navigation, headers, footers) and focuses on what actually matters for SEO analysis.

---

## The Setup

### Tools We Use
- **BeautifulSoup**: A Python library that reads and understands HTML structure
- **Regular Expressions**: Pattern matching to identify things like FAQ questions
- **JSON**: The output format that structures our extracted data

### How It Works (High Level)
1. Read the HTML file
2. Find the main content area (ignoring headers, navs, footers)
3. Walk through the content in reading order
4. Extract different types of blocks (headings, paragraphs, lists, etc.)
5. Clean up duplicates
6. Output everything as JSON

---

## The Rules - What We Include and Exclude

### ✅ WHAT WE INCLUDE

#### 1. Source Metadata
We grab basic page information from the HTML `<head>`:
- **URL**: The page's web address (from canonical link or og:url)
- **Title**: The page title (from `<title>` tag)
- **Canonical**: The preferred URL for this page
- **Meta Description**: The page description for search engines

#### 2. Main Content Area
We use a smart priority system to find the actual content:

**Priority 1**: Look for `<main>` tag or `role="main"` attribute
- If found, use that - it's explicitly marked as main content

**Priority 2**: If no main tag exists, we calculate "text density"
- We look at all containers (divs, articles, sections)
- We exclude anything inside header, nav, footer, or aside
- We calculate: (amount of text) ÷ (total HTML size)
- The container with the highest text density wins
- This finds the area with the most actual content vs. markup

**Fallback**: If nothing else works, we use the entire `<body>`

#### 3. Block Types We Extract

**Headings** (h1 through h6):
- We look for actual heading tags: `<h1>`, `<h2>`, etc.
- We also accept `role="heading"` with an `aria-level` attribute
- We preserve the hierarchy (h1 is most important, h6 is least)
- **Rule**: There must be exactly ONE h1. If there are multiple, we keep only the first one.

**Paragraphs**:
- Any `<p>` tags
- Standalone text that's significant (more than 10 characters)
- We filter out very short text (less than 15 chars) that looks like labels or stats
- We normalize whitespace (multiple spaces become one space)

**Lists**:
- Both ordered (`<ol>`) and unordered (`<ul>`) lists
- We extract each list item's text
- We mark whether it's ordered or not

**CTAs (Call-to-Action buttons/links)**:
- Buttons (`<button>`)
- Links (`<a>`) that look like buttons
- Elements with `role="button"`
- **BUT** we exclude:
  - Anything inside a `<form>`
  - Submit/reset buttons
  - Links that are just `javascript:` or `#`
- We capture the button text and the URL (if it's a link)

**Tables**:
- We extract all table rows
- Each row becomes an array of cell values
- We include both header cells (`<th>`) and data cells (`<td>`)

**Interactive Content**:

**FAQs**:
- Detected from `<details><summary>` patterns where the summary ends with "?"
- Or disclosure patterns (aria-expanded/aria-controls) that look like questions
- We check if text starts with question words: what, who, where, when, why, how, can, do, does, is, are, will, would
- Structure: question + answer_blocks (which can contain any other block types)

**Accordions**:
- Same as FAQs but without the question mark or question pattern
- Structure: title + content_blocks

**Tabsets**:
- Detected from `role="tablist"` containers
- We find all tabs and their corresponding panels
- We extract content from each tab panel
- Structure: array of tabs, each with a title and content_blocks

---

### ❌ WHAT WE EXCLUDE

#### 1. Sitewide Chrome (Navigation Elements)
- `<header>` tags
- `<nav>` tags  
- `<footer>` tags
- `<aside>` tags
- Elements with roles: `banner`, `navigation`, `contentinfo`, `complementary`

#### 2. Visual Elements (No Images)
- All `<img>` tags
- All `<svg>` tags
- All `<picture>` tags
- **Alt text is also excluded** (even though it's text, it's not visible rendered text)

#### 3. Technical/Non-Visible Elements
- `<script>` tags (JavaScript)
- `<style>` tags (CSS)
- `<noscript>` tags
- `<meta>` tags
- `<link>` tags

#### 4. Forms (Everything Form-Related)
- Entire `<form>` blocks
- All `<input>` fields
- All `<textarea>` fields
- All `<select>` dropdowns
- All `<label>` text
- Form buttons (submit, reset)
- Placeholder text
- Help text
- Validation messages
- **Why?** Forms are interactive UI elements, not content for SEO analysis

#### 5. JSON-LD and Tracking
- Any `<script type="application/ld+json">` (structured data)
- Tracking pixels, analytics scripts, etc.

---

## Special Processing Rules

### Deduplication
- If we find two blocks with identical text (normalized to lowercase), we keep only the first one
- This prevents duplicate content from responsive design or repeated widgets
- We normalize by: converting to lowercase, trimming whitespace, comparing structure

### Reading Order
- We process elements in the order they appear in the HTML
- This preserves the natural flow of content
- Children are processed before siblings

### Text Extraction
- We remove all HTML tags to get pure text
- We strip out scripts, styles, forms, images before extracting text
- We normalize whitespace (multiple spaces/newlines become single spaces)

### H1 Validation
- After extraction, we check: is there exactly one H1?
- If there are multiple H1s, we keep only the first one
- This enforces SEO best practices

---

## Output Structure

The final JSON has two main parts:

```json
{
  "source": {
    "url": "...",
    "title": "...",
    "canonical": "...",
    "meta_description": "..."
  },
  "blocks": [
    // Array of blocks in reading order
    // Each block has a "type" field
    // And type-specific fields
  ]
}
```

### Block Structure Examples

**Heading**:
```json
{
  "type": "heading",
  "level": 1,
  "text": "Main Title"
}
```

**Paragraph**:
```json
{
  "type": "paragraph",
  "text": "This is paragraph text..."
}
```

**List**:
```json
{
  "type": "list",
  "ordered": false,
  "items": ["Item 1", "Item 2", "Item 3"]
}
```

**CTA**:
```json
{
  "type": "cta",
  "text": "Click Here",
  "href": "https://example.com/page"
}
```

**FAQ**:
```json
{
  "type": "faq",
  "question": "What is this?",
  "answer_blocks": [
    { "type": "paragraph", "text": "This is the answer..." }
  ]
}
```

**Accordion**:
```json
{
  "type": "accordion",
  "title": "Section Title",
  "content_blocks": [...]
}
```

**Tabset**:
```json
{
  "type": "tabset",
  "tabs": [
    {
      "title": "Tab 1",
      "content_blocks": [...]
    },
    {
      "title": "Tab 2",
      "content_blocks": [...]
    }
  ]
}
```

**Table**:
```json
{
  "type": "table",
  "rows": [
    ["Header 1", "Header 2"],
    ["Data 1", "Data 2"]
  ]
}
```

---

## Why These Rules?

### SEO-Focused
- We extract semantic HTML structure, not CSS styling
- We focus on actual content, not navigation or UI chrome
- We preserve heading hierarchy for SEO analysis

### Clean Data
- No duplicate content
- No form noise
- No tracking/analytics clutter
- Pure, readable content structure

### Interactive Content Aware
- Modern websites use accordions, tabs, FAQs
- We extract the expanded content if it exists in the DOM
- This captures content that might be hidden but is still in the HTML

### Practical
- Works on post-JS-rendered HTML (what users actually see)
- Handles common patterns (details/summary, ARIA attributes)
- Gracefully handles missing elements (falls back to body if no main tag)

---

## Summary

This script is essentially a **content-focused HTML parser** that:
1. Finds the main content (ignoring navigation/chrome)
2. Extracts semantic blocks in reading order
3. Handles modern interactive content (FAQs, accordions, tabs)
4. Excludes everything that's not actual content (forms, images, scripts)
5. Outputs clean, structured JSON for SEO analysis

The result is a clean representation of what a human would read on the page, structured in a way that's perfect for analyzing SEO content, heading structure, and content quality.
