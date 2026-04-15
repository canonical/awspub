import datetime
import os
import sys

# Make the awspub package importable for autodoc
sys.path.insert(0, os.path.abspath(".."))

############################################################
### Project information
############################################################

project = "awspub"
author = "Canonical Ltd."

copyright = "%s CC-BY-SA, %s" % (datetime.date.today().year, author)

html_title = project + " documentation"

ogp_site_url = "https://canonical-awspub.readthedocs-hosted.com/"
ogp_site_name = project
ogp_image = "https://assets.ubuntu.com/v1/253da317-image-document-ubuntudocs.svg"

html_favicon = "_static/favicon.png"

html_context = {
    "product_page": "github.com/canonical/awspub",
    "product_tag": "_static/tag.png",
    "discourse": "",
    "mattermost": "",
    "matrix": "",
    "github_url": "https://github.com/canonical/awspub",
    "repo_default_branch": "main",
    "repo_folder": "/docs/",
    "sequential_nav": "none",
    "display_contributors": True,
    "display_contributors_since": "",
    "github_issues": "enabled",
    "author": author,
    "license": {
        "name": "GPL-3.0-or-later",
        "url": "https://github.com/canonical/awspub/blob/main/LICENSE",
    },
}

############################################################
### Template and asset locations
############################################################

html_static_path = ["_static"]
templates_path = ["_templates"]

############################################################
### Extensions
############################################################

extensions = [
    "canonical_sphinx",
    "notfound.extension",
    "sphinx_design",
    "sphinx_tabs.tabs",
    "sphinxcontrib.jquery",
    "sphinxext.opengraph",
    "sphinx_contributor_listing",
    "sphinx_related_links",
    "sphinx_roles",
    "sphinx_terminal",
    "sphinx_youtube_links",
    "sphinx_last_updated_by_git",
    "sphinx.ext.autodoc",
    "sphinxcontrib.autodoc_pydantic",
]

exclude_patterns = [
    "doc-cheat-sheet*",
    ".venv*",
]

############################################################
### Link checker exceptions
############################################################

linkcheck_ignore = [
    "http://127.0.0.1:8000",
]

linkcheck_anchors_ignore_for_url = [r"https://github\.com/.*"]

############################################################
### RST prolog / epilog
############################################################

rst_epilog = """
.. include:: /reuse/links.txt
"""

rst_prolog = """
.. role:: center
   :class: align-center
.. role:: h2
    :class: hclass2
.. role:: woke-ignore
    :class: woke-ignore
.. role:: vale-ignore
    :class: vale-ignore
"""

############################################################
### Additional configuration
############################################################

disable_feedback_button = False

# Workaround for https://github.com/canonical/canonical-sphinx/issues/34
if "discourse_prefix" not in html_context and "discourse" in html_context:
    html_context["discourse_prefix"] = f"{html_context['discourse']}/t/"
