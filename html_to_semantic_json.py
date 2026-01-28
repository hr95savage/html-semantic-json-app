#!/usr/bin/env python3
"""
HTML to Semantic JSON Extractor

Extracts semantic structure from rendered HTML and converts it to a structured JSON format.
"""

import json
import html
import re
import sys
import hashlib
import argparse
from typing import Dict, List, Optional, Any, Set, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString
from urllib.parse import urljoin, urlparse
from copy import deepcopy


class HTMLToSemanticJSON:
    """Extracts semantic JSON structure from HTML."""
    
    # Visually hidden class patterns (only true screen-reader-only classes, not breakpoint-specific)
    HIDDEN_CLASS_PATTERNS = [
        'sr-only', 'screen-reader-text', 'visually-hidden', 'hidden',
        'elementor-screen-only', 'visuallyhidden', 'sr-only-text',
        'a11y-hidden', 'skip-link', 'screen-reader', 'sr-only-text'
        # Removed: 'elementor-hidden', 'elementor-invisible' (these match breakpoint classes like elementor-hidden-mobile)
    ]
    
    # Button-like class patterns for CTA detection
    BUTTON_CLASS_PATTERNS = [
        'button', 'btn', 'elementor-button', 'wp-block-button__link',
        'wp-element-button', 'cta', 'call-to-action'
    ]
    
    def __init__(self, html_content: str, config: Optional[Dict[str, Any]] = None):
        self.soup = BeautifulSoup(html_content, 'lxml')
        self.main_content = None
        self.main_content_id_index = {}  # ID -> element mapping within main_content
        self._is_blog_post_cache = None  # Cache for blog post page detection
        self.consumed_panel_nodes = set()  # Track panel elements that have been extracted as part of tabsets
        
        # Default configuration
        default_config = {
            "eyebrow_mode": "annotate",  # options: annotate | drop | keep
            "drop_blog_feeds_on_non_blog_pages": True,
            "strict_seo_mode": False,
            "drop_breakpoint_hidden": False  # If True, remove breakpoint-hidden nodes (default False for SEO docs)
        }
        
        # Merge user config with defaults
        if config:
            default_config.update(config)
        self.config = default_config
        
    def extract(self) -> Dict[str, Any]:
        """Main extraction method."""
        source = self._extract_source_metadata()
        blocks, validation = self._extract_blocks()
        
        return {
            "source": source,
            "blocks": blocks,
            "validation": validation
        }
    
    def _extract_source_metadata(self) -> Dict[str, str]:
        """Extract source metadata from HTML head."""
        source = {
            "url": "",
            "title": "",
            "canonical": "",
            "meta_description": ""
        }
        
        # Extract title
        title_tag = self.soup.find('title')
        if title_tag:
            source["title"] = title_tag.get_text(strip=True)
        
        # Extract canonical URL
        canonical = self.soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            source["canonical"] = canonical['href']
            source["url"] = canonical['href']
        
        # If no canonical, try og:url
        if not source["url"]:
            og_url = self.soup.find('meta', property='og:url')
            if og_url and og_url.get('content'):
                url = og_url['content']
                source["url"] = url
                source["canonical"] = url
        
        # Extract meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            source["meta_description"] = meta_desc['content']
        else:
            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                source["meta_description"] = og_desc['content']
        
        return source
    
    def _extract_blocks(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract all blocks from main content and return validation."""
        main_content = self._find_main_content()
        if not main_content:
            return [], {"status": "warn", "h1_count": 0, "messages": ["No H1 found in extracted blocks."]}
        
        # Clone main content to avoid modifying original
        main_content_str = str(main_content)
        main_content_copy = BeautifulSoup(main_content_str, 'lxml')
        self.main_content = main_content_copy.find(main_content.name) or main_content_copy
        
        if not self.main_content:
            return []
        
        # Build ID index for main_content subtree
        self._build_id_index(self.main_content)
        
        # Prune unwanted nodes
        self._prune_unwanted_nodes(self.main_content)
        
        # Detect and convert counters to tables in HTML before extraction
        self._detect_and_convert_counters_in_html(self.main_content)
        
        # Extract blocks
        blocks = []
        self._extract_blocks_recursive(self.main_content, blocks)
        
        # Post-extraction counter detection disabled (HTML-level conversion is authoritative)
        
        # Annotate eyebrows (H5/H6 headings and paragraphs that match eyebrow pattern)
        blocks = self._annotate_eyebrows(blocks)
        
        # Post-process: Convert any remaining H5/H6 headings that match eyebrow pattern
        blocks = self._normalize_h5_h6_eyebrows(blocks)
        
        # Remove blog feed sections on non-blog pages
        blocks = self._remove_blog_feed_sections(blocks)

        # Section-scoped grid fallback (H2-scoped H4 card grids)
        blocks = self._section_scoped_grid_fallback(blocks)
        
        # Deduplicate blocks (with improved keys and nearby duplicate logic)
        blocks = self._deduplicate_blocks(blocks)
        
        # Validate H1 count (should be exactly one)
        h1_count = sum(
            1
            for b in blocks
            if b.get('type') == 'heading' and b.get('level') == 1
        )
        validation = {
            "status": "pass",
            "h1_count": h1_count,
            "messages": []
        }

        if h1_count == 0:
            validation["status"] = "warn"
            validation["messages"].append("No H1 found in extracted blocks.")
        elif h1_count > 1:
            original_h1_count = h1_count
            h1_seen = False
            filtered_blocks = []
            for block in blocks:
                if block.get('type') == 'heading' and block.get('level') == 1:
                    if not h1_seen:
                        filtered_blocks.append(block)
                        h1_seen = True
                else:
                    filtered_blocks.append(block)
            blocks = filtered_blocks
            h1_count = sum(
                1
                for b in blocks
                if b.get('type') == 'heading' and b.get('level') == 1
            )
            validation["status"] = "warn"
            validation["messages"].append(
                f"Multiple H1 headings found ({original_h1_count}). Kept the first."
            )

        validation["h1_count"] = h1_count
        
        return blocks, validation
    
    def _build_id_index(self, elem: Tag):
        """Build index of ID -> element within main_content subtree."""
        if isinstance(elem, Tag):
            elem_id = elem.get('id')
            if elem_id:
                self.main_content_id_index[elem_id] = elem
            for child in elem.children:
                if isinstance(child, Tag):
                    self._build_id_index(child)
    
    def _is_blog_post_page(self) -> bool:
        """Detect if current page is a blog post page (cached, URL-only detection)."""
        if self._is_blog_post_cache is not None:
            return self._is_blog_post_cache
        
        # Check URL patterns only (URL is the best signal)
        url = self._extract_source_metadata().get('url', '').lower()
        blog_url_patterns = [
            r'/\d{4}/\d{2}/\d{2}/',  # YYYY/MM/DD
            r'/blog/',
            r'/posts/',
        ]
        for pattern in blog_url_patterns:
            if re.search(pattern, url):
                self._is_blog_post_cache = True
                return True
        
        self._is_blog_post_cache = False
        return False
    
    def _is_blog_feed_section(self, elem: Tag) -> bool:
        """Detect if an element is a blog feed section."""
        if not isinstance(elem, Tag):
            return False
        
        # Must be a container element
        if elem.name not in ['div', 'section', 'article']:
            return False
        
        indicators = 0
        
        # Indicator 1: Section heading contains blog-related keywords
        headings = elem.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        for heading in headings:
            heading_text = self._get_visible_text_simple(heading).lower()
            blog_keywords = ['blog', 'latest posts', 'news', 'recent posts', 'articles']
            if any(keyword in heading_text for keyword in blog_keywords):
                indicators += 1
                break
        
        # Indicator 2: Repeated child pattern of date-like strings
        children = [c for c in elem.children if isinstance(c, Tag)]
        date_pattern = re.compile(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', re.I)
        date_pattern2 = re.compile(r'\d{4}[/-]\d{1,2}[/-]\d{1,2}')
        date_count = 0
        for child in children[:10]:  # Check first 10 children
            child_text = self._get_visible_text_simple(child)
            if date_pattern.search(child_text) or date_pattern2.search(child_text):
                date_count += 1
        
        if date_count >= 2:
            indicators += 1
        
        # Indicator 3: Post-title-like headings linking to blog URL patterns
        post_heading_links = elem.find_all('a')
        blog_link_count = 0
        for link in post_heading_links[:10]:
            href = link.get('href', '').lower()
            if any(pattern in href for pattern in ['/blog/', '/post/', '/article/', '/news/', r'/\d{4}/']):
                blog_link_count += 1
        
        if blog_link_count >= 2:
            indicators += 1
        
        # Indicator 4: Section is a feed/grid (repeating cards with same structure)
        if len(children) >= 3:
            # Check if children have similar structure (same tag names, similar class patterns)
            child_tags = [c.name for c in children[:5]]
            if len(set(child_tags)) == 1:  # All same tag type
                # Check if they have similar classes
                classes_list = [c.get('class', []) for c in children[:5]]
                if len(set(tuple(sorted(c)) for c in classes_list)) <= 2:  # 1-2 unique class patterns
                    indicators += 1
        
        # Need 2+ indicators to be considered a blog feed
        return indicators >= 2
    
    def _is_visually_hidden(self, elem: Tag) -> bool:
        """Check if element is visually hidden (excludes breakpoint-specific classes).
        
        Do NOT treat these as hidden:
        - elementor-hidden-mobile
        - elementor-hidden-tablet
        - elementor-hidden-desktop
        
        Only treat as hidden if you have global signals:
        - aria-hidden="true"
        - inline style includes display:none or visibility:hidden
        - known screen-reader-only classes (sr-only, screen-reader-text, etc.)
        """
        if not isinstance(elem, Tag):
            return False
        
        def _is_non_content_aria_hidden(target: Tag) -> bool:
            if not isinstance(target, Tag):
                return False
            if target.get('aria-hidden') != 'true':
                return False
            has_content_tags = target.find(
                ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'table']
            ) is not None
            text_len = len(target.get_text(strip=True) or "")
            return (not has_content_tags) and text_len < 10

        # Check aria-hidden (only treat as hidden if non-content)
        if _is_non_content_aria_hidden(elem):
            return True
        
        # Check inline styles first (global signal, not class-based)
        style = elem.get('style', '')
        if style:
            style_lower = style.lower()
            if 'display:none' in style_lower or 'display: none' in style_lower:
                return True
            if 'visibility:hidden' in style_lower or 'visibility: hidden' in style_lower:
                return True
        
        # Check classes (including parent classes - children inherit visibility)
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        
        # Explicitly exclude Elementor breakpoint classes (elementor-hidden-mobile, etc.)
        # These are viewport-specific, not globally hidden
        # Default behavior for SEO docs: include breakpoint-hidden content
        has_breakpoint_class = 'elementor-hidden-mobile' in class_str or \
                              'elementor-hidden-tablet' in class_str or \
                              'elementor-hidden-desktop' in class_str or \
                              'elementor-hidden-' in class_str
        
        # If element has breakpoint class and we're not dropping breakpoint-hidden content,
        # skip ALL class-based hidden checks (element and parents)
        if has_breakpoint_class:
            if self.config.get('drop_breakpoint_hidden', False):
                # Config says to drop breakpoint-hidden content
                return True
            else:
                # Keep breakpoint-hidden content - skip class-based hidden checks
                # Only check parents for global signals (aria-hidden)
                for parent in elem.parents:
                    if isinstance(parent, Tag):
                        if _is_non_content_aria_hidden(parent):
                            return True
                # No class-based hidden, no parent aria-hidden, no inline styles -> not hidden
                return False
        
        # Element does NOT have breakpoint class - check for true hidden classes
        for pattern in self.HIDDEN_CLASS_PATTERNS:
            if pattern.lower() in class_str:
                return True
        
        # Check parent elements for hidden classes (only if element doesn't have breakpoint class)
        for parent in elem.parents:
            if isinstance(parent, Tag):
                parent_classes = parent.get('class', [])
                parent_class_str = ' '.join(str(c) for c in parent_classes).lower()
                
                # Exclude breakpoint classes in parents too
                parent_has_breakpoint = 'elementor-hidden-mobile' in parent_class_str or \
                                       'elementor-hidden-tablet' in parent_class_str or \
                                       'elementor-hidden-desktop' in parent_class_str or \
                                       'elementor-hidden-' in parent_class_str
                
                if parent_has_breakpoint:
                    if not self.config.get('drop_breakpoint_hidden', False):
                        # Parent has breakpoint class and we're keeping breakpoint-hidden content
                        # Skip this parent's class check, but still check aria-hidden
                        if _is_non_content_aria_hidden(parent):
                            return True
                        continue
                    else:
                        # Config says to drop breakpoint-hidden content
                        return True
                
                # Check hidden patterns if parent doesn't have breakpoint classes
                for pattern in self.HIDDEN_CLASS_PATTERNS:
                    if pattern.lower() in parent_class_str:
                        return True
                
                # Check parent aria-hidden (global signal)
                if _is_non_content_aria_hidden(parent):
                    return True
        
        return False
    
    def _prune_unwanted_nodes(self, elem: Tag):
        """Prune unwanted nodes from the tree (prune-then-walk architecture)."""
        if not isinstance(elem, Tag):
            return
        
        # Remove unwanted tags (excluding icons - they're handled surgically)
        tags_to_remove = [
            'script', 'style', 'noscript', 'meta', 'link',
            'img', 'picture', 'source',  # Note: svg removed separately for surgical removal
            'form', 'input', 'textarea', 'select', 'label', 'option'
        ]
        
        # Remove chrome elements
        chrome_tags = {'header', 'nav', 'footer', 'aside'}
        chrome_roles = {'banner', 'navigation', 'contentinfo', 'complementary'}
        
        # Collect elements to remove (can't modify while iterating)
        to_remove = []
        
        for child in list(elem.children):
            if isinstance(child, Tag):
                # Remove unwanted tags
                if child.name in tags_to_remove:
                    to_remove.append(child)
                    continue
                
                # Remove chrome elements
                if child.name in chrome_tags:
                    to_remove.append(child)
                    continue
                
                if child.get('role') in chrome_roles:
                    to_remove.append(child)
                    continue
                
                # Remove visually hidden elements
                if self._is_visually_hidden(child):
                    to_remove.append(child)
                    continue
                
                # Recursively prune children
                self._prune_unwanted_nodes(child)
        
        # Remove collected elements
        for item in to_remove:
            item.decompose()
        
        # Surgical icon removal: remove only icon nodes, not parent containers
        self._remove_icons_surgically(elem)
    
    def _remove_icons_surgically(self, elem: Tag):
        """Surgically remove icon nodes only, preserving parent containers and text."""
        if not isinstance(elem, Tag):
            return
        
        # Find all icon elements to remove (use find_all to get all descendants)
        icons_to_remove = []
        
        # Find SVG elements (always remove - they're decorative)
        for svg in elem.find_all('svg'):
            icons_to_remove.append(svg)
        
        # Find <i> elements (often used for icons)
        for i_elem in elem.find_all('i'):
            # Check if it's likely an icon (has icon classes or is empty/minimal)
            classes = i_elem.get('class', [])
            class_str = ' '.join(str(c) for c in classes).lower()
            text = i_elem.get_text(strip=True)
            # If it has icon classes or is empty/minimal, it's likely an icon
            if ('icon' in class_str or 'fa-' in class_str or len(text) == 0 or len(text) < 3):
                icons_to_remove.append(i_elem)
        
        # Find elements with specific icon classes (Elementor, etc.)
        icon_class_patterns = [
            r'elementor-icon-list-icon',
            r'elementor-icon$',  # Exact match for elementor-icon (not elementor-icon-wrapper)
        ]
        for pattern in icon_class_patterns:
            for icon_elem in elem.find_all(class_=re.compile(pattern, re.I)):
                # Only remove if it's likely just an icon container
                # Check if it contains an svg or has minimal text
                has_svg = icon_elem.find('svg') is not None
                text = icon_elem.get_text(strip=True)
                # Remove if it has an SVG or has minimal text (< 10 chars)
                if has_svg or len(text) < 10:
                    icons_to_remove.append(icon_elem)
        
        # Remove icons (decompose removes the element but keeps parent)
        for icon in icons_to_remove:
            icon.decompose()
    
    def _detect_and_convert_counters_in_html(self, elem: Tag):
        """Detect counter patterns in HTML structure and convert to tables."""
        if not isinstance(elem, Tag):
            return
        
        # Look for containers with repeated children that look like counters
        # Common patterns: elementor-counter, stats containers, etc.
        # Don't process the root element itself (elem) - only its descendants
        for container in elem.find_all(['div', 'section', 'article'], recursive=True):
            if not isinstance(container, Tag):
                continue
            
            # Don't replace the main content container itself
            if container == elem or container == self.main_content:
                continue
            
            # Skip if container is too small or too large
            children = [c for c in container.children if isinstance(c, Tag)]
            if len(children) < 3 or len(children) > 20:
                continue
            
            # Skip if container is too large (more than 1000 chars of HTML),
            # unless it contains Elementor counter patterns.
            if len(str(container)) > 1000:
                has_elementor_counter = False
                for child in container.children:
                    if isinstance(child, Tag):
                        child_classes = child.get('class', [])
                        child_class_str = ' '.join(str(c) for c in child_classes).lower()
                        if 'elementor-widget-counter' in child_class_str:
                            has_elementor_counter = True
                            break
                if not has_elementor_counter:
                    continue
            
            # Look for counter pattern: each child has a number and a label
            counter_items = []
            for child in children:
                if self._is_visually_hidden(child):
                    continue
                
                value = None
                label = None
                
                # Pattern 1: Elementor counter structure - look for counter-number and counter-title classes
                number_elem = child.find(class_=re.compile(r'counter-number|elementor-counter-number', re.I))
                label_elem = child.find(class_=re.compile(r'counter-title|elementor-counter-title', re.I))
                
                if number_elem and label_elem:
                    value_text = self._get_visible_text_simple(number_elem).strip()
                    label_text = self._get_visible_text_simple(label_elem).strip()
                    if value_text and label_text and re.match(r'^[\d,\.]+\s*\+?', value_text) and len(label_text) < 40:
                        value = value_text
                        label = label_text
                
                # Pattern 2: Generic counter - look for number and label classes
                if not value or not label:
                    number_elem = child.find(class_=re.compile(r'number|count|value|stat', re.I))
                    label_elem = child.find(class_=re.compile(r'title|label|name|text', re.I))
                    
                    if number_elem and label_elem:
                        value_text = self._get_visible_text_simple(number_elem).strip()
                        label_text = self._get_visible_text_simple(label_elem).strip()
                        if value_text and label_text and re.match(r'^[\d,\.]+\s*\+?', value_text) and len(label_text) < 40:
                            value = value_text
                            label = label_text
                
                # Pattern 3: Number at start of text, label after
                if not value or not label:
                    child_text = self._get_visible_text_simple(child).strip()
                    if child_text:
                        match = re.match(r'^([\d,\.]+\s*\+?)\s+(.+)$', child_text)
                        if match:
                            value_text = match.group(1).strip()
                            label_text = match.group(2).strip()
                            if len(label_text) < 40:
                                value = value_text
                                label = label_text
                
                # Pattern 4: Check all descendants for number and label elements
                if not value or not label:
                    # Look for any element with numeric text
                    all_elems = child.find_all(True)  # All descendants
                    for desc in all_elems:
                        if self._is_visually_hidden(desc):
                            continue
                        desc_text = self._get_visible_text_simple(desc).strip()
                        if desc_text and re.match(r'^[\d,\.]+\s*\+?$', desc_text):
                            # Found a number, look for label nearby
                            # Check siblings
                            for sibling in desc.find_next_siblings():
                                if isinstance(sibling, Tag) and not self._is_visually_hidden(sibling):
                                    sibling_text = self._get_visible_text_simple(sibling).strip()
                                    if sibling_text and len(sibling_text) < 40 and not re.match(r'^[\d,\.]+\s*\+?', sibling_text):
                                        value = desc_text
                                        label = sibling_text
                                        break
                            # Check parent's other children
                            if not value or not label:
                                parent = desc.parent
                                if isinstance(parent, Tag):
                                    for sib in parent.children:
                                        if isinstance(sib, Tag) and sib != desc and not self._is_visually_hidden(sib):
                                            sib_text = self._get_visible_text_simple(sib).strip()
                                            if sib_text and len(sib_text) < 40 and not re.match(r'^[\d,\.]+\s*\+?', sib_text):
                                                value = desc_text
                                                label = sib_text
                                                break
                            if value and label:
                                break
                
                # Pattern 5: Check if child text is a label, look for number in siblings
                if not value or not label:
                    child_text = self._get_visible_text_simple(child).strip()
                    if child_text and len(child_text) < 40 and not re.match(r'^[\d,\.]+\s*\+?', child_text):
                        # This might be a label, check siblings for numbers
                        for sibling in child.find_previous_siblings():
                            if isinstance(sibling, Tag) and not self._is_visually_hidden(sibling):
                                sibling_text = self._get_visible_text_simple(sibling).strip()
                                if sibling_text and re.match(r'^[\d,\.]+\s*\+?$', sibling_text):
                                    value = sibling_text
                                    label = child_text
                                    break
                        # Also check next siblings
                        if not value or not label:
                            for sibling in child.find_next_siblings():
                                if isinstance(sibling, Tag) and not self._is_visually_hidden(sibling):
                                    sibling_text = self._get_visible_text_simple(sibling).strip()
                                    if sibling_text and re.match(r'^[\d,\.]+\s*\+?$', sibling_text):
                                        value = sibling_text
                                        label = child_text
                                        break
                
                if value and label:
                    counter_items.append((value, label))
            
            # If we found at least 3 counter items, convert to table
            # But exclude if it looks like a rating widget (has "rating" in labels)
            if len(counter_items) >= 3:
                # Check if this looks like a rating widget rather than stats
                has_rating = any('rating' in label.lower() for _, label in counter_items)
                if has_rating and len(set(v for v, _ in counter_items)) == 1:
                    # This is likely a rating widget, not a stats counter - skip it
                    continue
                
                # Create table HTML to avoid cross-soup tag issues
                rows_html = []
                for value, label in counter_items:
                    rows_html.append(
                        f"<tr><td>{html.escape(value)}</td><td>{html.escape(label)}</td></tr>"
                    )
                table_html = f"<table><tbody>{''.join(rows_html)}</tbody></table>"
                table = BeautifulSoup(table_html, 'lxml').find('table')
                
                # Replace container with table
                container.replace_with(table)
                # Continue processing other containers (don't return)
                continue
        
        # Recursively check children
        for child in elem.children:
            if isinstance(child, Tag):
                self._detect_and_convert_counters_in_html(child)
    
    def _find_main_content(self) -> Optional[Tag]:
        """Find main content area using priority rules."""
        # Priority 1: <main> or [role="main"]
        main_tag = self.soup.find('main') or self.soup.find(attrs={'role': 'main'})
        if main_tag:
            return main_tag
        
        # Priority 2: Find container with highest text density
        excluded_tags = {'header', 'nav', 'footer', 'aside'}
        excluded_roles = {'banner', 'navigation', 'contentinfo', 'complementary'}
        
        body = self.soup.find('body')
        if not body:
            return None
        
        candidates = []
        
        def is_excluded(elem: Tag) -> bool:
            if not isinstance(elem, Tag):
                return True
            if elem.name in excluded_tags:
                return True
            if elem.get('role') in excluded_roles:
                return True
            for parent in elem.parents:
                if isinstance(parent, Tag):
                    if parent.name in excluded_tags or parent.get('role') in excluded_roles:
                        return True
            return False
        
        def first_eligible_h1() -> Optional[Tag]:
            for h1 in self.soup.find_all('h1'):
                if not is_excluded(h1):
                    return h1
            return None
        
        def score_element(elem: Tag) -> float:
            """Calculate text density score."""
            if not isinstance(elem, Tag):
                return 0.0
            
            if elem.name in excluded_tags:
                return 0.0
            if elem.get('role') in excluded_roles:
                return 0.0
            
            for parent in elem.parents:
                if isinstance(parent, Tag):
                    if parent.name in excluded_tags or parent.get('role') in excluded_roles:
                        return 0.0
            
            text = self._get_visible_text_simple(elem)
            text_length = len(text.strip())
            
            if text_length == 0:
                return 0.0
            
            html_length = len(str(elem))
            if html_length == 0:
                return 0.0
            
            density = text_length / html_length
            
            if elem.name in {'article', 'section', 'div'}:
                density *= 1.2
            
            return density
        
        for elem in body.find_all(['main', 'article', 'section', 'div']):
            if not isinstance(elem, Tag):
                continue
            
            in_excluded = False
            for parent in elem.parents:
                if isinstance(parent, Tag):
                    if parent.name in excluded_tags or parent.get('role') in excluded_roles:
                        in_excluded = True
                        break
            if in_excluded:
                continue
            
            score = score_element(elem)
            if score > 0:
                candidates.append((score, elem))
        
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            eligible_h1 = first_eligible_h1()
            if eligible_h1 and eligible_h1 not in best.descendants and best is not eligible_h1:
                node = best
                while node and node.name != 'body':
                    if isinstance(node, Tag) and eligible_h1 in node.descendants:
                        if not is_excluded(node):
                            best = node
                            break
                    node = node.parent if isinstance(node.parent, Tag) else None
            return best
        
        return body
    
    def _get_visible_text_simple(self, elem: Tag) -> str:
        """Simple text extraction for scoring (no cloning)."""
        if not isinstance(elem, Tag):
            return ""
        # Skip hidden elements
        if self._is_visually_hidden(elem):
            return ""
        return elem.get_text(separator=' ', strip=True)
    
    def _is_navigation_link(self, elem: Tag) -> bool:
        """Check if link is a navigation link (not a CTA)."""
        if not isinstance(elem, Tag) or elem.name != 'a':
            return False
        
        # Check if inside list (navigation lists)
        for parent in elem.parents:
            if isinstance(parent, Tag):
                if parent.name in {'ul', 'ol'}:
                    # Check if it's a button group (unlikely in ul/ol)
                    parent_classes = parent.get('class', [])
                    parent_class_str = ' '.join(str(c) for c in parent_classes).lower()
                    if 'button' in parent_class_str or 'btn-group' in parent_class_str:
                        return False
                    return True
        
        # Check link text patterns
        text = self._get_visible_text_simple(elem).strip()
        text_lower = text.lower()
        nav_patterns = [
            r'^read more',
            r'^read full',
            r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # Dates
            r'^page \d+',
            r'^next',
            r'^previous',
            r'^prev',
        ]
        for pattern in nav_patterns:
            if re.match(pattern, text_lower):
                return True
        
        # Check for location/city patterns (City, ST or City, State)
        location_pattern = r'^[A-Z][a-z]+(?: [A-Z][a-z]+)?,\s*(?:[A-Z]{2}|[A-Z][a-z]+)$'
        if re.match(location_pattern, text):
            return True
        
        # Check if link is near many similar links (navigation pattern)
        if isinstance(elem.parent, Tag):
            siblings = [s for s in elem.parent.children if isinstance(s, Tag) and s.name == 'a']
            if len(siblings) > 3:
                # Check if siblings have similar patterns (location lists, etc.)
                similar_count = 0
                for sib in siblings:
                    sib_text = self._get_visible_text_simple(sib).strip()
                    # Check if similar format (location, or similar length/pattern)
                    if re.match(location_pattern, sib_text):
                        similar_count += 1
                    elif len(sib_text) > 0 and abs(len(sib_text) - len(text)) < 5:
                        similar_count += 1
                if similar_count >= 3:
                    return True
        
        # Check for navigation-related classes
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        nav_classes = ['nav', 'navigation', 'menu', 'link-list', 'location', 'city', 'blog-link']
        for nav_class in nav_classes:
            if nav_class in class_str:
                return True
        
        return False
    
    def _is_button_like(self, elem: Tag) -> bool:
        """Check if element looks like a button (strict CTA detection)."""
        if not isinstance(elem, Tag):
            return False
        
        # Skip if visually hidden
        if self._is_visually_hidden(elem):
            return False
        
        # Check if inside form - but allow CTAs that route to contact/quote pages
        is_inside_form = False
        for parent in elem.parents:
            if isinstance(parent, Tag) and parent.name == 'form':
                is_inside_form = True
                break
        
        if is_inside_form:
            # Allow CTAs that route to contact/quote pages even if near forms
            if elem.name == 'a' and elem.get('href'):
                href = elem.get('href', '').lower()
                contact_patterns = ['/contact', '/quote', 'tel:', 'mailto:']
                if any(pattern in href for pattern in contact_patterns):
                    # This is a contact/quote CTA - allow it even if near form
                    pass  # Continue to button-like checks below
                else:
                    # Inside form and not a contact/quote link - exclude
                    return False
            elif elem.name == 'button':
                # Check if it's an actual form submission control
                button_type = elem.get('type', '').lower()
                if button_type in {'submit', 'reset'}:
                    return False
                # Allow non-submit buttons even if inside form (they might route to contact pages)
                pass  # Continue to button-like checks below
            else:
                # Other elements inside form - exclude
                return False
        
        # Check for API endpoint links (exclude even if they have role="button")
        if elem.name == 'a' and elem.get('href'):
            href = elem.get('href', '').lower()
            # Exclude review widget API endpoints
            api_patterns = [
                r'trustindex\.io/api/',
                r'/api/',
                r'api\.',
            ]
            for pattern in api_patterns:
                if re.search(pattern, href):
                    return False
        
        # <button> elements (except submit/reset)
        if elem.name == 'button':
            button_type = elem.get('type', '').lower()
            if button_type in {'submit', 'reset'}:
                return False
            return True
        
        # role="button" - but exclude API endpoints
        if elem.get('role') == 'button':
            # Double-check it's not an API endpoint link
            if elem.name == 'a' and elem.get('href'):
                href = elem.get('href', '').lower()
                if any(re.search(p, href) for p in [r'trustindex\.io/api/', r'/api/', r'api\.']):
                    return False
            return True
        
        # <a> elements that look like buttons
        if elem.name == 'a':
            # Exclude navigation links
            if self._is_navigation_link(elem):
                return False
            
            # Text length check - reject if > 60 characters
            text = self._get_visible_text_simple(elem).strip()
            if len(text) > 60:
                return False
            
            # Full sentence check - reject if contains sentence-ending punctuation in middle
            if re.search(r'[.!?].+[.!?]', text):
                return False
            
            # Content check - reject if wraps multiple paragraphs or headings
            has_paragraph = elem.find('p') is not None
            has_heading = elem.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) is not None
            if has_paragraph or has_heading:
                return False
            
            classes = elem.get('class', [])
            class_str = ' '.join(str(c) for c in classes).lower()
            
            # STRICT: Only accept <a> as CTA if it has explicit button styling OR explicit action attributes
            # Check for button-like classes
            has_button_class = False
            for pattern in self.BUTTON_CLASS_PATTERNS:
                if pattern.lower() in class_str:
                    has_button_class = True
                    break
            
            # Check for explicit action attributes
            has_action_attr = bool(elem.get('data-action') or elem.get('data-cta'))
            
            # Require at least one: button classes OR action attributes
            if has_button_class or has_action_attr:
                return True
            
            # Remove aria-label fallback - too permissive
            # Only accept if explicitly styled as button
        
        return False
    
    def _is_inside_consumed_panel(self, elem: Tag) -> bool:
        """Check if element has a consumed panel ancestor."""
        if not isinstance(elem, Tag):
            return False
        for parent in elem.parents:
            if parent in self.consumed_panel_nodes:
                return True
        return False
    
    def _normalize_context(self, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        base = {"in_tab_panel": False, "in_nav": False, "depth": 0}
        if context:
            base.update(context)
        return base
    
    def _is_nav_container(self, elem: Tag) -> bool:
        if not isinstance(elem, Tag):
            return False
        if elem.name == 'nav':
            return True
        role = elem.get('role', '')
        return role == 'navigation'
    
    def _child_context(self, context: Dict[str, Any], child: Tag) -> Dict[str, Any]:
        next_context = dict(context)
        next_context["depth"] = context.get("depth", 0) + 1
        if context.get("in_nav"):
            next_context["in_nav"] = True
        else:
            next_context["in_nav"] = self._is_nav_container(child)
        return next_context
    
    def _extract_blocks_recursive(self, elem: Tag, blocks: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None):
        """Recursively extract blocks from element."""
        if not isinstance(elem, Tag):
            return
        
        context = self._normalize_context(context)
        
        # Skip if this element is consumed (part of extracted tabset panel)
        if elem in self.consumed_panel_nodes:
            return
        
        # Skip if element is inside a consumed panel subtree
        if self._is_inside_consumed_panel(elem):
            return
        
        # Skip if visually hidden
        if self._is_visually_hidden(elem):
            return
        
        # Skip blog feed sections on non-blog pages
        drop_blog_feeds = self.config.get("drop_blog_feeds_on_non_blog_pages", True)
        if drop_blog_feeds and not self._is_blog_post_page():
            if self._is_blog_feed_section(elem):
                return  # Skip this section entirely
        
        # Handle interactive content first
        # Check for pseudo-tabset (anchor-based tabs) before ARIA tabsets
        # Only detect and emit when elem is the actual container holding the anchor nav
        # This ensures tabset appears in correct reading order (where nav appears in DOM)
        pseudo_tabset = self._detect_pseudo_tabset(elem)
        if pseudo_tabset:
            container, anchor_list = pseudo_tabset
            # Only emit tabset if the detected container is elem itself
            # This ensures we emit at the correct position in DOM order
            if container == elem:
                tabset_block = self._extract_pseudo_tabset(container, anchor_list)
                if tabset_block:
                    blocks.append(tabset_block)
                    # Don't recurse into the container itself (panels are already consumed),
                    # but continue processing other children of elem that are NOT in the container
                    # This allows us to extract content that's a sibling of the tabset container
                    for child in elem.children:
                        if isinstance(child, Tag):
                            # Skip if child is the container or is inside the container
                            if child == container or child in container.descendants:
                                continue
                            # Process siblings of the container
                            self._extract_blocks_recursive(child, blocks)
                    return
            # If container is deeper (not elem), continue normal extraction
            # The tabset will be detected when we reach the actual container
        
        if elem.get('role') == 'tablist':
            tabset = self._extract_tabset(elem)
            if tabset:
                blocks.append(tabset)
                return
        
        if elem.name == 'details':
            accordion = self._extract_accordion_or_faq(elem)
            if accordion:
                blocks.append(accordion)
                return
        
        if elem.get('aria-expanded') is not None or (elem.get('aria-controls') and 
                                                      elem.get('role') != 'tab'):
            accordion = self._extract_disclosure_accordion(elem)
            if accordion:
                blocks.append(accordion)
                return
        
        if elem.get('role') == 'tabpanel' and self._is_in_tabset(elem):
            return
        
        # Extract regular content
        self._extract_blocks_from_element(elem, blocks, context)
    
    def _is_in_tabset(self, elem: Tag) -> bool:
        """Check if element is part of a tabset structure."""
        for parent in elem.parents:
            if isinstance(parent, Tag):
                if parent.get('role') == 'tablist':
                    return True
        return False
    
    def _extract_blocks_from_element(self, elem: Tag, blocks: List[Dict[str, Any]], context: Dict[str, Any]):
        """Extract blocks from a single element."""
        if not isinstance(elem, Tag):
            return
        
        # Check if elem itself is a semantic block container
        # If so, extract it and return (don't recurse into descendants to avoid duplicates)
        if elem.name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            heading = self._extract_heading(elem)
            if heading:
                blocks.append(heading)
            return  # Don't recurse - heading contains its own text
        
        if elem.name == 'p':
            para = self._extract_paragraph(elem)
            if para:
                blocks.append(para)
            return  # Don't recurse - paragraph contains its own text
        
        # Elementor/text-editor widgets often store text directly on a div
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        if any(key in class_str for key in ['text-editor', 'elementor-text-editor', 'elementor-widget-text-editor']):
            text = self._get_visible_text_simple(elem).strip()
            if text:
                para = self._create_paragraph(text)
                if para:
                    blocks.append(para)
            return
        
        if elem.name in {'ul', 'ol'}:
            list_block = self._extract_list(elem)
            if list_block:
                blocks.append(list_block)
            return  # Don't recurse - list contains its own items
        
        if elem.name == 'table':
            table = self._extract_table(elem)
            if table:
                blocks.append(table)
            return  # Don't recurse - table contains its own cells
        
        if elem.name == 'details':
            accordion = self._extract_accordion_or_faq(elem)
            if accordion:
                blocks.append(accordion)
            return  # Don't recurse - accordion content already extracted
        
        if elem.get('role') == 'tablist':
            tabset = self._extract_tabset(elem)
            if tabset:
                blocks.append(tabset)
            return  # Don't recurse - tabset content already extracted
        
        # Card grid detection (generic, shape-based)
        card_grid_blocks = self._detect_card_grid(elem, context)
        if card_grid_blocks:
            blocks.extend(card_grid_blocks)
            return  # Don't process children normally if we extracted as card grid
        
        # For non-semantic containers, process children and recurse to find nested content
        # Process children in order
        for child in elem.children:
            if isinstance(child, NavigableString):
                # Only extract text nodes from known text containers
                text = str(child).strip()
                if text and len(text) > 10:
                    # Get the actual parent of this text node (not the container elem)
                    parent = child.parent if hasattr(child, "parent") else elem
                    if isinstance(parent, Tag):
                        # Only extract from known text containers
                        # Remove generic div/section/article fallback - too permissive
                        if parent.name in {'p', 'li', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'summary'}:
                            para = self._create_paragraph(text)
                            if para:
                                blocks.append(para)
            elif isinstance(child, Tag):
                # Skip if visually hidden
                if self._is_visually_hidden(child):
                    continue
                
                # Capture CTA blocks explicitly before recursion
                if self._is_button_like(child):
                    cta = self._extract_cta(child)
                    if cta:
                        blocks.append(cta)
                        continue
                
                # Recursively process child - this will handle semantic blocks and recurse as needed
                child_context = self._child_context(context, child)
                self._extract_blocks_recursive(child, blocks, child_context)
    
    def _is_eyebrow_paragraph(self, block: Dict[str, Any], next_block: Optional[Dict[str, Any]], 
                                block_index: int, all_blocks: List[Dict[str, Any]]) -> bool:
        """Check if a paragraph block is an eyebrow label."""
        # Must be a paragraph
        if block.get('type') != 'paragraph':
            return False
        
        text = block.get('text', '').strip()
        
        # Text length < 40 characters
        if len(text) >= 40:
            return False
        
        # No sentence punctuation (. ! ?)
        if re.search(r'[.!?]', text):
            return False
        
        # Alphabetic or short slogan-like text (not just numbers/symbols)
        if not re.search(r'[a-zA-Z]', text):
            return False
        
        # Check if block is inside lists, tables, or FAQs (should not be eyebrow)
        # Look backwards to see if we're inside a list/table/faq structure
        for i in range(max(0, block_index - 10), block_index):
            prev_block = all_blocks[i]
            prev_type = prev_block.get('type')
            # If we see a list/table/faq before this block, we might be inside it
            # This is a heuristic - in practice, nested blocks would be in content_blocks
            if prev_type in ['list', 'table', 'faq', 'accordion']:
                # Check if this paragraph is likely part of that structure
                # (simple heuristic: if very close, might be related)
                if block_index - i <= 2:
                    return False
        
        # Immediately precedes a heading (h2 or h3)
        if next_block and next_block.get('type') == 'heading':
            next_level = next_block.get('level', 0)
            if 2 <= next_level <= 3:
                return True
        
        return False
    
    def _annotate_eyebrows(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Annotate eyebrow labels with meta.role = "eyebrow"."""
        eyebrow_mode = self.config.get("eyebrow_mode", "annotate")
        
        if eyebrow_mode == "keep":
            # Keep as regular paragraphs, no annotation
            return blocks
        
        result = []
        for i, block in enumerate(blocks):
            next_block = blocks[i + 1] if i + 1 < len(blocks) else None
            
            # Check if H5 or H6 heading is an eyebrow (convert to paragraph first)
            is_h5_h6_eyebrow = False
            if block.get('type') == 'heading' and block.get('level') >= 5:
                text = block.get('text', '').strip()
                # For H5/H6, allow ending punctuation (., !, ?) but not internal punctuation
                # This catches labels like "Still have questions?" and "WE STOP BUGS IN DFW."
                has_internal_punctuation = bool(re.search(r'[.!?].+', text))  # Punctuation not at end
                next_is_paragraph = bool(next_block and next_block.get('type') == 'paragraph')
                if (len(text) < 40 and 
                    not has_internal_punctuation and
                    re.search(r'[a-zA-Z]', text) and
                    not next_is_paragraph):
                    is_h5_h6_eyebrow = True
                    # Convert H5/H6 to paragraph for annotation
                    block = {
                        "type": "paragraph",
                        "text": text
                    }
            
            # Check if paragraph is an eyebrow
            is_eyebrow = is_h5_h6_eyebrow or self._is_eyebrow_paragraph(block, next_block, i, blocks)
            
            if is_eyebrow:
                if eyebrow_mode == "drop":
                    # Skip this block entirely
                    continue
                elif eyebrow_mode == "annotate":
                    # Add meta annotation
                    block = block.copy()
                    block["meta"] = {"role": "eyebrow"}
                    result.append(block)
                else:
                    # "keep" mode - already handled above
                    result.append(block)
            else:
                result.append(block)
        
        return result
    
    def _normalize_h5_h6_eyebrows(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Post-processing: Convert any remaining H5/H6 headings that match eyebrow pattern."""
        eyebrow_mode = self.config.get("eyebrow_mode", "annotate")
        
        if eyebrow_mode == "keep":
            return blocks
        
        result = []
        for i, block in enumerate(blocks):
            # Check if this is an H5/H6 heading that should be an eyebrow
            if (block.get('type') == 'heading' and 
                block.get('level', 0) >= 5):
                text = block.get('text', '').strip()
                next_block = blocks[i + 1] if i + 1 < len(blocks) else None
                
                # Apply eyebrow heuristic
                has_internal_punctuation = bool(re.search(r'[.!?].+', text))  # Punctuation not at end
                is_eyebrow = (
                    len(text) < 40 and 
                    not has_internal_punctuation and
                    re.search(r'[a-zA-Z]', text) and
                    next_block and next_block.get('type') == 'heading' and
                    2 <= next_block.get('level', 0) <= 3
                )
                
                if is_eyebrow:
                    if eyebrow_mode == "drop":
                        # Skip this block entirely
                        continue
                    elif eyebrow_mode == "annotate":
                        # Convert to paragraph with eyebrow annotation
                        result.append({
                            "type": "paragraph",
                            "text": text,
                            "meta": {"role": "eyebrow"}
                        })
                        continue
            
            # Not an eyebrow, keep the block
            result.append(block)
        
        return result
    
    def _remove_blog_feed_sections(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove blog feed sections from blocks on non-blog pages."""
        # Only remove if this is NOT a blog post page
        if self._is_blog_post_page():
            return blocks
        
        # Get URL to verify it's not a blog post page
        url = self._extract_source_metadata().get('url', '').lower()
        blog_url_patterns = [
            r'/\d{4}/\d{2}/\d{2}/',  # YYYY/MM/DD
            r'/blog/',
            r'/posts/',
        ]
        is_blog_post = any(re.search(pattern, url) for pattern in blog_url_patterns)
        
        if is_blog_post:
            return blocks
        
        result = []
        i = 0
        
        while i < len(blocks):
            block = blocks[i]
            
            # Check if this is a blog feed heading (H2 with "blog" or "posts" in text)
            if (block.get('type') == 'heading' and 
                block.get('level') == 2):
                heading_text = block.get('text', '').lower()
                if 'blog' in heading_text or 'posts' in heading_text:
                    # Found blog feed section start - skip this heading and all subsequent blocks
                    # until we find the next H2 that is NOT part of the blog feed
                    i += 1  # Skip the blog feed heading
                    
                    # Skip all blocks until next H2 that doesn't contain blog keywords
                    while i < len(blocks):
                        next_block = blocks[i]
                        # If we hit another H2, check if it's blog-related
                        if (next_block.get('type') == 'heading' and 
                            next_block.get('level') == 2):
                            next_heading_text = next_block.get('text', '').lower()
                            # If it's not blog-related, we've reached the end of the feed
                            if 'blog' not in next_heading_text and 'posts' not in next_heading_text:
                                # Include this H2 and continue processing normally
                                break
                        # Otherwise, skip this block (it's part of the blog feed)
                        i += 1
                    
                    # Continue from the next H2 (or end of blocks)
                    continue
            
            # Not a blog feed section, keep the block
            result.append(block)
            i += 1
        
        return result
    
    def _extract_heading(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract heading block."""
        text = self._get_visible_text_simple(elem).strip()
        if not text:
            return None
        
        level = int(elem.name[1])
        
        return {
            "type": "heading",
            "level": level,
            "text": text
        }
    
    def _extract_role_heading(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract heading from role='heading' with aria-level."""
        text = self._get_visible_text_simple(elem).strip()
        if not text:
            return None
        
        level = int(elem.get('aria-level', 2))
        level = max(1, min(6, level))
        
        return {
            "type": "heading",
            "level": level,
            "text": text
        }
    
    def _extract_paragraph(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract paragraph block."""
        text = self._get_visible_text_simple(elem).strip()
        if not text:
            return None
        
        return self._create_paragraph(text)
    
    def _create_paragraph(self, text: str, meta: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Create paragraph block from text."""
        text = text.strip()
        if not text or len(text) < 3:
            return None
        
        text = re.sub(r'\s+', ' ', text)
        
        # Filter out text that looks like alt text or accessibility helper text
        text_lower = text.lower()
        # Common alt text patterns
        alt_text_patterns = [
            r'^image of',
            r'^picture of',
            r'^photo of',
            r'^illustration of',
            r'^graphic showing',
            r'^icon for',
            r'^logo for',
            r'^trusted.*in.*area$',  # "trusted pest control in the dallas forth worth area"
            r'^click to',
            r'^link to',
        ]
        for pattern in alt_text_patterns:
            if re.match(pattern, text_lower):
                return None
        
        # Filter very short text that's likely labels or accessibility text
        if len(text) < 15 and not re.search(r'[.!?]', text):
            if not re.search(r'\d', text):
                return None
        
        para = {
            "type": "paragraph",
            "text": text
        }
        
        if meta:
            para["meta"] = meta
        
        return para
    
    def _extract_list(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract list block."""
        items = []
        
        # Check for Elementor icon list structure first (fallback for hero bullets)
        # Pattern: .elementor-icon-list-items li .elementor-icon-list-text
        # This handles cases where the ul has elementor-icon-list-items class
        if elem.name == 'ul':
            classes = elem.get('class', [])
            class_str = ' '.join(str(c) for c in classes).lower()
            if 'elementor-icon-list-items' in class_str:
                for li in elem.find_all('li', recursive=False):
                    # Look for .elementor-icon-list-text span
                    text_elem = li.find(class_=re.compile(r'elementor-icon-list-text', re.I))
                    if text_elem:
                        text = self._get_visible_text_simple(text_elem).strip()
                        if text:
                            items.append(text)
                    else:
                        # Fallback: get text from li directly
                        text = self._get_visible_text_simple(li).strip()
                        if text:
                            items.append(text)
        
        # Standard list extraction
        if not items:
            for li in elem.find_all('li', recursive=False):
                text = self._get_visible_text_simple(li).strip()
                if text:
                    items.append(text)
        
        # Require at least 2 items for a valid list
        if len(items) < 2:
            return None
        
        return {
            "type": "list",
            "ordered": elem.name == 'ol',
            "items": items
        }
    
    def _is_icon_list_container(self, elem: Tag) -> bool:
        """Check if a div container is an icon list structure (strict detection)."""
        if not isinstance(elem, Tag) or elem.name != 'div':
            return False
        
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        
        # Explicit exclusion: carousel/slider/marquee containers
        exclude_classes = ['swiper', 'carousel', 'marquee', 'ticker', 'loop', 'slider']
        if any(exc in class_str for exc in exclude_classes):
            return False
        
        # Acceptance criteria (any one is enough):
        # 1. Contains real ul/ol list
        if elem.find(['ul', 'ol'], recursive=False):
            return True
        
        # 2. Has ARIA list semantics
        if elem.get('role') == 'list':
            return True
        # Check if children have role="listitem"
        for child in elem.children:
            if isinstance(child, Tag) and child.get('role') == 'listitem':
                return True
        
        # 3. Strong class signals (Elementor/Webflow icon list patterns)
        icon_list_classes = ['elementor-widget-icon-list', 'icon-list']
        if any(iclass in class_str for iclass in icon_list_classes):
            return True
        
        # If none of the above criteria match, it's not an icon list
        return False
    
    def _extract_icon_list(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract icon list as a list block (after icons have been surgically removed)."""
        if not isinstance(elem, Tag):
            return None
        
        # First check for nested ul/ol structures - prefer those
        nested_lists = elem.find_all(['ul', 'ol'], recursive=False)
        if nested_lists:
            # If there's a nested list, extract that instead
            for nested_list in nested_lists:
                nested_items = []
                for li in nested_list.find_all('li', recursive=False):
                    text = self._get_visible_text_simple(li).strip()
                    if 3 <= len(text) <= 80:
                        nested_items.append(text)
                if len(nested_items) >= 2:
                    return {
                        "type": "list",
                        "ordered": nested_list.name == 'ol',
                        "items": nested_items
                    }
        
        # Look for direct children that might be list items (icon list pattern)
        items = []
        for child in elem.children:
            if isinstance(child, Tag):
                # Skip if child has nested block elements (it's a container, not a list item)
                nested_blocks = child.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol'], recursive=False)
                if nested_blocks:
                    continue  # This is a container, not a simple list item
                
                text = self._get_visible_text_simple(child).strip()
                # Only include items with short visible text (3-80 chars) - typical list item length
                if 3 <= len(text) <= 80:
                    items.append(text)
        
        # Require at least 2 items for a valid list
        if len(items) < 2:
            return None
        
        # Check for repetition (prevent junk lists)
        # Normalize first 5 items and check for duplicates
        if len(items) >= 2:
            first_five = [item.lower().strip() for item in items[:5]]
            if len(first_five) != len(set(first_five)):
                # Has duplicates - likely junk, not a real list
                return None
        
        return {
            "type": "list",
            "ordered": False,  # Icon lists are typically unordered
            "items": items
        }
    
    def _extract_table(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract table block."""
        rows = []
        for tr in elem.find_all('tr'):
            row = []
            for cell in tr.find_all(['td', 'th']):
                text = self._get_visible_text_simple(cell).strip()
                row.append(text)
            if row:
                rows.append(row)
        
        if not rows:
            return None
        
        return {
            "type": "table",
            "rows": rows
        }
    
    
    def _extract_cta(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract CTA block (only called for button-like elements)."""
        text = self._get_visible_text_simple(elem).strip()
        if not text:
            return None
        
        cta = {
            "type": "cta",
            "text": text
        }
        
        # Add href if it's a link
        if elem.name == 'a' and elem.get('href'):
            href = elem['href']
            if href.startswith('javascript:') or href == '#':
                return None
            
            # Check if it's an internal anchor (router)
            if href.startswith('#'):
                cta["href"] = href
                cta["meta"] = {"role": "router"}
                return cta
            
            if href.startswith('/') or not href.startswith('http'):
                canonical = self.soup.find('link', rel='canonical')
                if canonical and canonical.get('href'):
                    base_url = canonical['href']
                    href = urljoin(base_url, href)
            cta["href"] = href
        
        return cta
    
    def _extract_accordion_or_faq(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract accordion or FAQ from <details> element."""
        summary = elem.find('summary')
        if not summary:
            return None
        
        title = self._get_visible_text_simple(summary).strip()
        if not title:
            return None
        
        content_blocks = []
        
        # Use full recursive extraction for answer content
        for child in elem.children:
            if isinstance(child, Tag) and child.name != 'summary':
                before_len = len(content_blocks)
                self._extract_blocks_recursive(child, content_blocks)
                if len(content_blocks) == before_len:
                    text = self._get_visible_text_simple(child).strip()
                    if text:
                        para = self._create_paragraph(text)
                        if para:
                            content_blocks.append(para)
            elif isinstance(child, NavigableString):
                text = str(child).strip()
                if text and len(text) > 10:
                    para = self._create_paragraph(text)
                    if para:
                        content_blocks.append(para)
        
        is_faq = title.strip().endswith('?') or self._looks_like_faq_question(title)
        
        # If no answer content found, add fallback message
        if not content_blocks:
            content_blocks.append({
                "type": "paragraph",
                "text": "Insufficient evidence: answer container not found in DOM"
            })
        
        if is_faq:
            return {
                "type": "faq",
                "question": title,
                "answer_blocks": content_blocks
            }
        else:
            return {
                "type": "accordion",
                "title": title,
                "content_blocks": content_blocks
            }
    
    def _extract_disclosure_accordion(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract accordion from disclosure pattern (constrained to main_content)."""
        title = self._get_visible_text_simple(elem).strip()
        if not title:
            return None
        
        content_blocks = []
        controls_id = elem.get('aria-controls')
        
        # Search only within main_content subtree
        # Try aria-controls target first
        if controls_id:
            controlled = self.main_content_id_index.get(controls_id)
            if controlled:
                # Use full recursive extraction
                self._extract_blocks_recursive(controlled, content_blocks)
        
        # Elementor accordion pattern (parent container)
        if not content_blocks:
            parent = elem.parent
            if isinstance(parent, Tag):
                content = parent.find(class_=re.compile(r'elementor-accordion-content', re.I))
                if content:
                    self._extract_blocks_recursive(content, content_blocks)
        
        # If no content found, try nearest sibling panel element (common accordion DOM patterns)
        if not content_blocks:
            for sibling in elem.next_siblings:
                if isinstance(sibling, Tag):
                    # Check if it looks like a panel/answer container
                    # Common patterns: role="region", class contains "panel"/"content"/"answer"
                    classes = sibling.get('class', [])
                    class_str = ' '.join(str(c) for c in classes).lower()
                    is_panel = (
                        sibling.get('role') == 'region' or
                        'panel' in class_str or
                        'content' in class_str or
                        'answer' in class_str or
                        sibling.name in ['div', 'section', 'article']
                    )
                    if is_panel:
                        # Use full recursive extraction
                        self._extract_blocks_recursive(sibling, content_blocks)
                        break
        
        is_faq = title.strip().endswith('?') or self._looks_like_faq_question(title)
        
        # If no answer content found, add fallback message
        if not content_blocks:
            content_blocks.append({
                "type": "paragraph",
                "text": "Insufficient evidence: answer container not found in DOM"
            })
        
        if is_faq:
            return {
                "type": "faq",
                "question": title,
                "answer_blocks": content_blocks
            }
        else:
            return {
                "type": "accordion",
                "title": title,
                "content_blocks": content_blocks
            }
    
    def _extract_tabset(self, elem: Tag) -> Optional[Dict[str, Any]]:
        """Extract tabset structure (constrained to main_content)."""
        tabs = []
        
        tab_elements = elem.find_all(attrs={'role': 'tab'})
        
        if not tab_elements:
            for child in elem.children:
                if isinstance(child, Tag):
                    classes = child.get('class', [])
                    if any('tab' in str(c).lower() for c in classes):
                        tab_elements.append(child)
        
        if not tab_elements:
            return None
        
        # Find panels only within main_content
        all_panels = self.main_content.find_all(attrs={'role': 'tabpanel'}) if self.main_content else []
        
        for tab_elem in tab_elements:
            title = self._get_visible_text_simple(tab_elem).strip()
            if not title:
                continue
            
            content_blocks = []
            
            # Find corresponding panel (only in main_content)
            panel_id = tab_elem.get('aria-controls') or tab_elem.get('data-target') or tab_elem.get('data-tab')
            
            if panel_id:
                panel_id = panel_id.lstrip('#')
                panel = self.main_content_id_index.get(panel_id)
                if panel:
                    # Use panel-scoped extraction for tab panel content
                    content_blocks = self._extract_panel_blocks(panel)
            
            tab_id = tab_elem.get('id')
            if tab_id and not content_blocks:
                for panel in all_panels:
                    if panel.get('aria-labelledby') == tab_id:
                        # Use panel-scoped extraction for tab panel content
                        content_blocks = self._extract_panel_blocks(panel)
                        break
            
            if not content_blocks:
                for sibling in tab_elem.find_next_siblings():
                    if isinstance(sibling, Tag) and sibling.get('role') == 'tabpanel':
                        # Verify sibling is in main_content
                        if sibling in self.main_content.descendants if self.main_content else False:
                            # Use panel-scoped extraction for tab panel content
                            content_blocks = self._extract_panel_blocks(sibling)
                            break
            
            if title:
                tabs.append({
                    "title": title,
                    "content_blocks": content_blocks
                })
        
        if tabs:
            return {
                "type": "tabset",
                "tabs": tabs
            }
        
        return None
    
    def _mark_panel_consumed(self, panel: Tag):
        """Mark panel and all descendants as consumed.
        
        Only marks the panel element itself and its descendants.
        Does NOT mark parent containers or siblings.
        """
        if not isinstance(panel, Tag):
            return
        # Only mark the panel element itself - descendants are checked via panel.descendants
        self.consumed_panel_nodes.add(panel)
        # Note: We don't add all descendants to the set to avoid memory bloat.
        # Instead, we check if elem in panel.descendants in _extract_blocks_recursive.
    
    def _detect_pseudo_tabset(self, elem: Tag) -> Optional[tuple]:
        """Detect anchor-based pseudo-tabset (fragment links pointing to panel containers).
        
        Returns:
            Tuple of (container_elem, anchor_list) or None
            anchor_list format: [(anchor_text, target_id), ...] in DOM order
            
        Note: This method finds the container that holds the anchor cluster.
        The caller should only emit the tabset when elem == container to maintain reading order.
        """
        if not isinstance(elem, Tag):
            return None
        
        # Only check containers that might hold anchor clusters
        if elem.name not in ['div', 'section', 'article', 'nav', 'ul', 'ol', 'p']:
            return None
        
        # Find all anchor links with fragment hrefs within this container
        # Prefer direct children first, then descendants
        anchors = []
        # First check direct children
        for child in elem.children:
            if isinstance(child, Tag) and child.name == 'a':
                href = child.get('href', '')
                if href.startswith('#'):
                    target_id = href.lstrip('#')
                    if target_id in self.main_content_id_index:
                        anchor_text = self._get_visible_text_simple(child).strip()
                        if anchor_text:
                            anchors.append((child, anchor_text, target_id))
        
        # If not enough direct children, check all descendants
        if len(anchors) < 2:
            for anchor in elem.find_all('a', href=True, recursive=True):
                href = anchor.get('href', '')
                if href.startswith('#'):
                    target_id = href.lstrip('#')
                    if target_id in self.main_content_id_index:
                        anchor_text = self._get_visible_text_simple(anchor).strip()
                        if anchor_text:
                            # Avoid duplicates
                            if not any(a == anchor for a, _, _ in anchors):
                                anchors.append((anchor, anchor_text, target_id))
        
        # Need at least 2 anchors with valid targets
        if len(anchors) < 2:
            return None
        
        # Limit to 2-8 anchors (reasonable tabset size)
        if len(anchors) > 8:
            return None
        
        # Verify at least 2 unique target panels exist
        unique_targets = set(target_id for _, _, target_id in anchors)
        if len(unique_targets) < 2:
            return None
        
        # Check if anchors are close together (same parent or siblings)
        # Group anchors by their immediate parent
        parent_groups = {}
        for anchor, anchor_text, target_id in anchors:
            parent = anchor.parent
            if isinstance(parent, Tag):
                parent_key = id(parent)
                if parent_key not in parent_groups:
                    parent_groups[parent_key] = []
                parent_groups[parent_key].append((anchor, anchor_text, target_id))
        
        # Find the largest group (most anchors sharing the same parent)
        if not parent_groups:
            return None
        
        largest_group = max(parent_groups.values(), key=len)
        
        # Need at least 2 anchors sharing the same parent
        if len(largest_group) < 2:
            # If anchors don't share immediate parent, check if they're siblings or close
            # Try grouping by grandparent
            grandparent_groups = {}
            for anchor, anchor_text, target_id in anchors:
                parent = anchor.parent
                if isinstance(parent, Tag):
                    grandparent = parent.parent
                    if isinstance(grandparent, Tag):
                        gp_key = id(grandparent)
                        if gp_key not in grandparent_groups:
                            grandparent_groups[gp_key] = []
                        grandparent_groups[gp_key].append((anchor, anchor_text, target_id))
            
            if grandparent_groups:
                largest_group = max(grandparent_groups.values(), key=len)
                if len(largest_group) < 2:
                    return None
            else:
                return None
        
        # Find the lowest common ancestor of all anchors in the group
        anchor_elems = [anchor for anchor, _, _ in largest_group]
        if not anchor_elems:
            return None
        
        # Start with the first anchor's parent and walk up to find common container
        container = anchor_elems[0].parent
        max_levels = 5  # Don't go too far up
        level = 0
        
        while container and isinstance(container, Tag) and level < max_levels:
            # Check if all anchors in the group are descendants of this container
            all_contained = True
            for anchor in anchor_elems:
                # Check if anchor is a descendant or direct child
                is_descendant = any(ancestor == container for ancestor in anchor.parents if isinstance(ancestor, Tag))
                is_direct_child = anchor.parent == container
                if not (is_descendant or is_direct_child):
                    all_contained = False
                    break
            
            if all_contained:
                # Found a container that holds all anchors
                break
            
            container = container.parent if hasattr(container, 'parent') else None
            level += 1
        
        if not container or not isinstance(container, Tag):
            # Fallback: use elem as container if it contains all anchors
            container = elem
        
        # Build anchor list in DOM order
        anchor_list = []
        for anchor, anchor_text, target_id in largest_group:
            anchor_list.append((anchor_text, target_id))
        
        # Sort by DOM position to maintain reading order
        def get_dom_position(item):
            anchor_elem = next((a for a, text, tid in largest_group if text == item[0] and tid == item[1]), None)
            if anchor_elem:
                # Count previous siblings to get position
                pos = 0
                for sibling in anchor_elem.previous_siblings:
                    if isinstance(sibling, Tag):
                        pos += 1
                return pos
            return 0
        
        anchor_list.sort(key=get_dom_position)
        
        return (container, anchor_list)
    
    def _extract_panel_blocks(self, panel: Tag) -> List[Dict[str, Any]]:
        """Extract blocks from a panel without consumed-node skipping."""
        blocks: List[Dict[str, Any]] = []
        saved_consumed = self.consumed_panel_nodes
        self.consumed_panel_nodes = set()
        try:
            self._extract_blocks_recursive(panel, blocks, {"in_tab_panel": True})
        finally:
            self.consumed_panel_nodes = saved_consumed
        return blocks
    
    def _extract_pseudo_tabset(self, container: Tag, anchor_list: List[tuple]) -> Optional[Dict[str, Any]]:
        """Extract pseudo-tabset from anchor-based tabs.
        
        Args:
            container: Container element that holds the anchor nav
            anchor_list: List of (anchor_text, target_id) tuples in DOM order
        
        Returns:
            Tabset block dict or None
        """
        tabs = []
        
        for anchor_text, target_id in anchor_list:
            # Locate panel
            panel = self.main_content_id_index.get(target_id)
            if not panel:
                # Panel not found, but still include tab with empty content
                tabs.append({
                    "title": anchor_text,
                    "content_blocks": []
                })
                continue
            
            # Extract content blocks from panel using full recursive extraction
            # This ensures we get paragraphs, lists, tables, CTAs, and all nested content
            content_blocks = []
            
            # Use panel-scoped extraction before marking as consumed
            content_blocks = self._extract_panel_blocks(panel)
            
            # Filter out blocks that are just the anchor nav text (duplicate headings)
            # This helps avoid duplicate panel titles that match the anchor text
            filtered_blocks = []
            for block in content_blocks:
                block_text = block.get('text', '').strip()
                # Skip if this block's text exactly matches an anchor text (likely duplicate panel title)
                if block_text and block_text == anchor_text:
                    continue
                filtered_blocks.append(block)
            content_blocks = filtered_blocks
            
            # Mark panel and all descendants as consumed (prevents duplicate extraction)
            # Only mark the panel root and its descendants, NOT parents or siblings
            self._mark_panel_consumed(panel)
            
            tabs.append({
                "title": anchor_text,
                "content_blocks": content_blocks
            })
        
        # Need at least 2 tabs for a valid tabset
        if len(tabs) < 2:
            return None
        
        return {
            "type": "tabset",
            "tabs": tabs
        }
    
    def _looks_like_faq_question(self, text: str) -> bool:
        """Check if text looks like an FAQ question."""
        text_lower = text.lower()
        faq_patterns = [
            r'^(what|who|where|when|why|how|can|do|does|is|are|will|would)\s+',
            r'\?$',
            r'^faq',
        ]
        for pattern in faq_patterns:
            if re.search(pattern, text_lower):
                return True
        return False
    
    def _detect_counters_in_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect counter patterns in extracted blocks and convert to tables."""
        # Known counter label patterns
        known_counter_labels = [
            'Homes & Businesses Protected',
            'Inspections Completed', 
            'Treatments Administered',
            'Five-Star Reviews'
        ]
        
        result = []
        i = 0
        while i < len(blocks):
            # Look for sequence of short label paragraphs that might be counter labels
            window_start = i
            labels = []
            
            # Collect consecutive short paragraphs
            while i < len(blocks) and blocks[i].get('type') == 'paragraph':
                text = blocks[i].get('text', '').strip()
                # Check if it looks like a counter label (short, no numbers, no sentence ending)
                # OR if it matches known counter labels
                is_known_label = any(known in text or text in known for known in known_counter_labels)
                looks_like_label = (len(text) < 40 and 
                    not re.search(r'[.!?]$', text) and 
                    not re.match(r'^[\d,\.]+\s*\+?', text) and
                    text[0].isupper())
                
                if is_known_label or looks_like_label:
                    labels.append((i, text))
                    i += 1
                else:
                    break
            
            # If we found 3+ labels, try to find numbers in original HTML
            if len(labels) >= 3:
                # Search original HTML for numbers associated with these labels
                rows = []
                for label_idx, label_text in labels:
                    # Find the label in original HTML and look for nearby numbers
                    value = self._find_counter_number_for_label(label_text)
                    if value:
                        rows.append([value, label_text])
                    else:
                        # No number found, but still include as row with empty value
                        # (better than losing the label entirely)
                        rows.append(["", label_text])
                
                # Only create table if we found at least some numbers, or if all labels match known patterns
                if len(rows) >= 3:
                    # Check if at least one has a number, or if they're all known labels
                    has_numbers = any(row[0] for row in rows)
                    all_known = all(any(known in row[1] or row[1] in known for known in known_counter_labels) for row in rows)
                    
                    if has_numbers or all_known:
                        result.append({
                            "type": "table",
                            "rows": rows
                        })
                        # Skip the label paragraphs we converted
                        i = window_start + len(labels)
                        continue
            
            # Not a counter pattern, add the block normally
            if i < len(blocks):
                result.append(blocks[i])
                i += 1
        
        return result
    
    def _find_counter_number_for_label(self, label_text: str) -> Optional[str]:
        """Find the counter number associated with a label in the original HTML."""
        # Search in the original soup (before pruning) for the label
        # Then look for numbers nearby
        label_elem = self.soup.find(string=re.compile(re.escape(label_text), re.I))
        if not label_elem:
            return None
        
        # Get parent container
        parent = label_elem.find_parent()
        if not parent:
            return None
        
        # Look for number in the same container or nearby siblings
        # Check same element's text
        container = parent
        for _ in range(3):  # Go up 3 levels to find container
            container_text = container.get_text(separator=' ', strip=True) if isinstance(container, Tag) else ""
            # Look for number pattern in container text
            match = re.search(r'([\d,\.]+\s*\+?)', container_text)
            if match:
                # Check if number appears before the label in the text
                label_pos = container_text.find(label_text)
                num_pos = container_text.find(match.group(1))
                if num_pos < label_pos and num_pos >= label_pos - 50:  # Number within 50 chars before label
                    return match.group(1).strip()
            
            # Check siblings for numbers
            if isinstance(container, Tag):
                for sibling in list(container.find_previous_siblings(limit=2)) + list(container.find_next_siblings(limit=2)):
                    if isinstance(sibling, Tag):
                        sib_text = sibling.get_text(strip=True)
                        if re.match(r'^[\d,\.]+\s*\+?$', sib_text):
                            return sib_text
                
                # Check children for number elements
                for child in container.find_all(['span', 'div'], limit=10):
                    if isinstance(child, Tag):
                        child_text = child.get_text(strip=True)
                        if re.match(r'^[\d,\.]+\s*\+?$', child_text):
                            return child_text
            
            container = container.find_parent() if hasattr(container, 'find_parent') else None
            if not container:
                break
        
        return None
    
    def _detect_counter_pattern(self, blocks: List[Dict[str, Any]], start_idx: int) -> Optional[Dict[str, Any]]:
        """Detect if blocks starting at start_idx form a counter pattern."""
        # Look for repeated "number + label" patterns
        # Common pattern: elementor-counter-number + elementor-counter-title
        # Or similar value + label pairs
        
        # Check next 2-6 blocks for counter pattern
        window = blocks[start_idx:start_idx + 6]
        
        # Look for pairs of short paragraphs that look like "value" + "label"
        pairs = []
        i = 0
        while i < len(window) - 1:
            if (window[i].get('type') == 'paragraph' and 
                window[i+1].get('type') == 'paragraph'):
                value_text = window[i].get('text', '')
                label_text = window[i+1].get('text', '')
                
                # Check if value looks like a number/stat
                if re.match(r'^[\d,+\-]+', value_text.strip()) and len(value_text) < 20:
                    pairs.append((value_text.strip(), label_text.strip()))
                    i += 2
                    continue
            i += 1
        
        # Need at least 2 pairs to form a table
        if len(pairs) >= 2:
            rows = [list(pair) for pair in pairs]
            return {
                "type": "table",
                "rows": rows
            }
        
        return None
    
    def _convert_counters_to_tables(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert counter patterns to table blocks."""
        result = []
        i = 0
        while i < len(blocks):
            counter_table = self._detect_counter_pattern(blocks, i)
            if counter_table:
                result.append(counter_table)
                # Skip the blocks that were converted
                # Count how many pairs we found
                window = blocks[i:i+6]
                pairs = 0
                j = 0
                while j < len(window) - 1:
                    if (window[j].get('type') == 'paragraph' and 
                        window[j+1].get('type') == 'paragraph'):
                        value_text = window[j].get('text', '')
                        if re.match(r'^[\d,+\-]+', value_text.strip()) and len(value_text) < 20:
                            pairs += 1
                            j += 2
                            continue
                    j += 1
                i += pairs * 2
            else:
                result.append(blocks[i])
                i += 1
        
        return result

    def _section_scoped_grid_fallback(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect H2-scoped H4 grids and emit a list fallback."""
        if not blocks:
            return []
        
        result = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            
            if block.get('type') == 'heading' and block.get('level') == 2:
                section_blocks = []
                j = i + 1
                while j < len(blocks):
                    next_block = blocks[j]
                    if next_block.get('type') == 'heading' and next_block.get('level') == 2:
                        break
                    section_blocks.append(next_block)
                    j += 1
                
                # Collect unique H4 headings in this section (ignore nested tabsets/accordions)
                h4_indices = []
                h4_titles = []
                seen_titles = set()
                for idx, sb in enumerate(section_blocks):
                    if sb.get('type') in ['tabset', 'accordion', 'faq']:
                        continue
                    if sb.get('type') == 'heading' and sb.get('level') == 4:
                        text = sb.get('text', '').strip()
                        key = text.lower()
                        if text and key not in seen_titles:
                            seen_titles.add(key)
                            h4_indices.append(idx)
                            h4_titles.append(text)
                
                if len(h4_titles) >= 6:
                    grid_blocks = [{
                        "type": "list",
                        "ordered": False,
                        "items": h4_titles
                    }]
                    
                    # Remove original H4s (and their nearby description paragraphs)
                    skip_indices = set()
                    for idx in h4_indices:
                        skip_indices.add(idx)
                        for k in range(idx + 1, min(idx + 4, len(section_blocks))):
                            if section_blocks[k].get('type') == 'paragraph':
                                skip_indices.add(k)
                                break
                    
                    result.append(block)
                    inserted = False
                    first_h4_idx = h4_indices[0] if h4_indices else None
                    for idx, sb in enumerate(section_blocks):
                        if first_h4_idx is not None and idx == first_h4_idx and not inserted:
                            result.extend(grid_blocks)
                            inserted = True
                        if idx in skip_indices:
                            continue
                        result.append(sb)
                    if not inserted:
                        result.extend(grid_blocks)
                    
                    i = j
                    continue
            
            result.append(block)
            i += 1
        
        return result
    
    def _deduplicate_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate blocks with improved keys and nearby duplicate logic."""
        if not blocks:
            return []
        
        # Dedupe within tabset content blocks to prevent duplicates per tab
        preprocessed_blocks = []
        for block in blocks:
            if block.get('type') == 'tabset':
                tabs = []
                for tab in block.get('tabs', []):
                    content_blocks = tab.get('content_blocks', [])
                    tabs.append({
                        **tab,
                        "content_blocks": self._deduplicate_blocks(content_blocks)
                    })
                preprocessed_blocks.append({**block, "tabs": tabs})
            else:
                preprocessed_blocks.append(block)
        blocks = preprocessed_blocks
        
        # Use sliding window for nearby duplicates (last 30 blocks)
        WINDOW_SIZE = 30
        seen_in_window = []
        deduplicated = []
        
        for block in blocks:
            block_key = self._normalize_block_text(block)
            
            # Check if duplicate in recent window
            is_duplicate = False
            if block_key:
                for seen_key, seen_block in seen_in_window:
                    if seen_key == block_key:
                        is_duplicate = True
                        break
            
            if not is_duplicate:
                deduplicated.append(block)
                if block_key:
                    seen_in_window.append((block_key, block))
                    # Keep window size limited
                    if len(seen_in_window) > WINDOW_SIZE:
                        seen_in_window.pop(0)
            elif not block_key:
                # Keep blocks without text
                deduplicated.append(block)
        
        return deduplicated
    
    def _normalize_block_text(self, block: Dict[str, Any]) -> str:
        """Normalize block text for deduplication (improved keys)."""
        block_type = block.get('type')
        
        if block_type == 'heading':
            return f"heading:{block.get('level')}:{block.get('text', '').lower().strip()}"
        elif block_type == 'paragraph':
            return f"paragraph:{block.get('text', '').lower().strip()}"
        elif block_type == 'list':
            items = '|'.join(item.lower().strip() for item in block.get('items', []))
            return f"list:{block.get('ordered')}:{items}"
        elif block_type == 'cta':
            # Include href in dedupe key
            text = block.get('text', '').lower().strip()
            href = block.get('href', '').lower().strip()
            return f"cta:{text}:{href}"
        elif block_type == 'table':
            rows = '|'.join('|'.join(cell.lower().strip() for cell in row) for row in block.get('rows', []))
            return f"table:{rows}"
        elif block_type == 'faq':
            # Include answer content in dedupe key
            question = block.get('question', '').lower().strip()
            answer_text = self._extract_blocks_text(block.get('answer_blocks', []))
            answer_hash = hashlib.md5(answer_text.encode()).hexdigest()[:8]
            return f"faq:{question}:{answer_hash}"
        elif block_type == 'accordion':
            # Include content in dedupe key
            title = block.get('title', '').lower().strip()
            content_text = self._extract_blocks_text(block.get('content_blocks', []))
            content_hash = hashlib.md5(content_text.encode()).hexdigest()[:8]
            return f"accordion:{title}:{content_hash}"
        elif block_type == 'tabset':
            titles = '|'.join(tab.get('title', '').lower().strip() for tab in block.get('tabs', []))
            return f"tabset:{titles}"
        
        return ""
    
    def _extract_blocks_text(self, blocks: List[Dict[str, Any]]) -> str:
        """Extract all text from nested blocks for hashing."""
        text_parts = []
        for block in blocks:
            if block.get('type') == 'paragraph':
                text_parts.append(block.get('text', ''))
            elif block.get('type') == 'heading':
                text_parts.append(block.get('text', ''))
            elif block.get('type') == 'list':
                text_parts.extend(block.get('items', []))
            elif block.get('type') == 'table':
                for row in block.get('rows', []):
                    text_parts.extend(row)
        return '|'.join(text_parts).lower()
    
    def _is_likely_grid_container(self, elem: Tag) -> bool:
        """Check if element is likely a card grid container."""
        if not isinstance(elem, Tag):
            return False
        
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        
        # Check for carousel/grid classes
        grid_indicators = [
            'carousel', 'swiper', 'grid', 'cards', 
            'elementor-carousel', 'elementor-widget-n-carousel'
        ]
        if any(indicator in class_str for indicator in grid_indicators):
            return True
        
        # Check for many repeated card-like descendants (6+ unique H4 titles)
        h4s = elem.find_all('h4')
        if h4s:
            titles = {
                h4.get_text(strip=True)
                for h4 in h4s
                if h4.get_text(strip=True)
            }
            if len(titles) >= 6:
                return True
        
        return False
    
    def _detect_card_grid(self, elem: Tag, context: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Detect and extract generic card grid pattern."""
        if not isinstance(elem, Tag):
            return None
        if context.get("in_tab_panel") or context.get("in_nav"):
            return None
        if elem.find('form'):
            return None
        
        classes = elem.get('class', [])
        class_str = ' '.join(str(c) for c in classes).lower()
        slider_classes = ['swiper', 'carousel', 'marquee', 'ticker', 'loop', 'slider']
        if any(exc in class_str for exc in slider_classes):
            return None
        
        # Skip if this looks like a tab nav cluster
        if self._detect_pseudo_tabset(elem):
            return None
        
        if not self._is_likely_grid_container(elem):
            return None
        
        def find_title_element(card: Tag) -> Optional[Tag]:
            heading = card.find(['h2', 'h3', 'h4'], recursive=True)
            if heading:
                return heading
            role_heading = card.find(attrs={'role': 'heading'})
            if role_heading:
                return role_heading
            return card.find(class_=re.compile(r'title|card-title|heading', re.I))
        
        card_candidates = []
        for child in elem.children:
            if isinstance(child, Tag):
                if self._is_visually_hidden(child):
                    continue
                title_elem = find_title_element(child)
                if title_elem and title_elem.get_text(strip=True):
                    card_candidates.append(child)
        
        if len(card_candidates) < 6:
            return None
        
        # Require consistent structure
        structure_counts = {}
        for card in card_candidates:
            key = (card.name, ' '.join(card.get('class', [])[:2]).lower())
            structure_counts[key] = structure_counts.get(key, 0) + 1
        if max(structure_counts.values(), default=0) < 6:
            return None
        
        # Titles must be mostly unique
        titles = []
        for card in card_candidates[:8]:
            title_elem = find_title_element(card)
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                if title_text:
                    titles.append(title_text.lower())
        if len(titles) != len(set(titles)):
            return None
        
        extracted_cards = []
        cards_with_desc = 0
        
        for card in card_candidates:
            title_elem = find_title_element(card)
            if not title_elem:
                continue
            heading_text = title_elem.get_text(strip=True)
            if not heading_text or len(heading_text) < 3:
                continue
            
            heading_level = 4
            if isinstance(title_elem, Tag):
                if title_elem.name in ['h2', 'h3', 'h4']:
                    heading_level = int(title_elem.name[1])
                elif title_elem.get('aria-level'):
                    heading_level = int(title_elem.get('aria-level', 4))
            
            extracted_cards.append({
                "type": "heading",
                "level": heading_level,
                "text": heading_text
            })
            
            para = card.find('p', recursive=True)
            if not para:
                for div in card.find_all('div', recursive=True):
                    div_text = self._get_visible_text_simple(div).strip()
                    if len(div_text) > 30 and not div.find(['h2', 'h3', 'h4', 'ul', 'ol'], recursive=False):
                        para = div
                        break
            
            if para:
                para_text = self._get_visible_text_simple(para).strip()
                if len(para_text) >= 20:
                    cards_with_desc += 1
                    para_block = self._create_paragraph(para_text)
                    if para_block:
                        extracted_cards.append(para_block)
        
        if cards_with_desc < len(card_candidates) * 0.6:
            unique_titles = []
            for card in card_candidates:
                title_elem = find_title_element(card)
                if title_elem:
                    title_text = title_elem.get_text(strip=True)
                    if title_text and title_text not in unique_titles:
                        unique_titles.append(title_text)
            if len(unique_titles) >= 6:
                return [{
                    "type": "list",
                    "ordered": False,
                    "items": unique_titles
                }]
            return None
        
        return extracted_cards


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Extract semantic JSON from HTML')
    parser.add_argument('html_file', help='Input HTML file')
    parser.add_argument('output_file', nargs='?', help='Output JSON file (optional, defaults to stdout)')
    parser.add_argument('-c', '--config', help='JSON config file path')
    args = parser.parse_args()
    
    html_file = args.html_file
    output_file = args.output_file
    
    # Load config if provided
    config = None
    if args.config:
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error reading config file: {e}", file=sys.stderr)
            sys.exit(1)
    
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)
    
    extractor = HTMLToSemanticJSON(html_content, config=config)
    result = extractor.extract()
    
    json_output = json.dumps(result, indent=2, ensure_ascii=False)
    
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(json_output)
            print(f"Output saved to: {output_file}", file=sys.stderr)
        except Exception as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(json_output)


if __name__ == '__main__':
    main()
