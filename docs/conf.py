import os
import sys

sys.path.insert(0, os.path.abspath("../"))

project = 'awspub'
copyright = '2023, Thomas Bechtold'
author = 'Thomas Bechtold'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinxcontrib.autodoc_pydantic',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']


autodoc_typehints = 'both'

autodoc_pydantic_model_show_json = True

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'alabaster'
html_static_path = ['_static']
