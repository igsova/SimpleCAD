"""MkDocs hooks: publish the root README, CHANGELOG and CONTRIBUTING with docs/.

The files stay where GitHub shows them. Links are written for the repository
on GitHub, so each page's relative links are rewritten for the site: pages
in the site link to each other, and anything else (LICENSE, scripts,
examples) links to the file on GitHub. Tool icons are published from
Resources/icons, so pages link to them where GitHub has them.
"""
import posixpath
import re
from pathlib import Path

from mkdocs.structure.files import File

ROOT = Path(__file__).resolve().parent.parent
REPO = 'https://github.com/igsova/SimpleCAD/blob/main/'
PAGES = {'README.md': 'index.md', 'CHANGELOG.md': 'changelog.md', 'CONTRIBUTING.md': 'contributing.md'}
ASSETS = {'Resources/icons/workbench.svg': 'images/logo.svg'}
ICONS = ('Resources/icons/', 'images/icons/')
# Markdown links and images, ](target#anchor), resolved by MkDocs from the page's file.
MARKDOWN = re.compile(r'(\]\()([^)\s#]+)([^)]*\))')
# HTML src, href and poster attributes, which the browser resolves from the page's URL.
HTML = re.compile(r'''((?:src|href|poster)=")([^"#]+)(["#])''')


def on_files(files, config):
    for source, site in PAGES.items():
        files.append(File.generated(config, site, content=(ROOT / source).read_text(encoding='utf-8')))
    for source, site in ASSETS.items():
        files.append(File.generated(config, site, abs_src_path=str(ROOT / source)))
    for icon in sorted((ROOT / ICONS[0]).glob('*.svg')):
        files.append(File.generated(config, ICONS[1] + icon.name, abs_src_path=str(icon)))
    return files


def on_page_markdown(markdown, page, config, files):
    page_uri = page.file.src_uri
    origin = next((source for source, site in PAGES.items() if site == page_uri), 'docs/' + page_uri)

    def rewrite(match, base):
        target = match.group(2)
        if ':' in target:
            return match.group(0)
        path = posixpath.normpath(posixpath.join(posixpath.dirname(origin), target))
        if path in PAGES:
            site = PAGES[path]
        elif path in ASSETS:
            site = ASSETS[path]
        elif path.startswith(ICONS[0]):
            site = ICONS[1] + path[len(ICONS[0]):]
        elif path.startswith('docs/'):
            site = path[len('docs/'):]
        else:
            return match.group(1) + REPO + path + match.group(3)
        return match.group(1) + posixpath.relpath(site, base or '.') + match.group(3)

    markdown = MARKDOWN.sub(lambda m: rewrite(m, posixpath.dirname(page_uri)), markdown)
    # Page URLs end in a slash ('tools/draw/') unless the page is the site's index ('').
    return HTML.sub(lambda m: rewrite(m, page.url.rstrip('/')), markdown)
