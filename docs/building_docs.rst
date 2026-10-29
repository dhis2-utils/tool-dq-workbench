
Building the documentation
==========================

The latest documentation is published at https://dhis2-utils.github.io/tool-dq-workbench/
and is automatically updated on every push to ``main``.

The documentation is built using Sphinx.
This section explains how to set up your environment and generate the HTML
and PDF outputs locally.

Prerequisites
-------------

- On Ubuntu/Debian, LaTeX packages are required for PDF builds

Setup instructions
------------------

1. Create and activate a virtual environment:

   .. code-block:: bash

      python3 -m venv .venv
      source .venv/bin/activate

2. Install Sphinx and dependencies:

   .. code-block:: bash

      pip install sphinx latexmk

3. (Ubuntu only) Install LaTeX packages:

   .. code-block:: bash

      sudo apt-get update
      sudo apt-get install texlive-latex-recommended \
                           texlive-latex-extra \
                           texlive-fonts-recommended \
                           latexmk

Building HTML
-------------

To build the HTML documentation:

.. code-block:: bash

   cd docs
   make html

The output will be available in ``docs/_build/html/index.html``.

Building Slides
---------------

Slides are kept in a separate Sphinx project under ``docs/slides`` using the ``sphinx-revealjs`` builder.

1. Install the dependency (in your activated virtual environment):

   .. code-block:: bash

      pip install sphinx-revealjs

2. Build the slides:

   .. code-block:: bash

      cd docs/slides
      make revealjs

3. Open the generated slides at ``docs/slides/_build/revealjs/index.html``.

4. Screenshots (shared between docs and slides): place PNGs/JPGs under ``docs/_static/screenshots/``.
   - In the main docs, reference them as ``_static/screenshots/<file>.png``.
   - In the slides, reference them relative to the slides source as ``../_static/screenshots/<file>.png``.

Building PDF
------------

To build the PDF version:

.. code-block:: bash

   cd docs
   make latexpdf

The generated PDF will be located in ``docs/_build/latex/``.

Cleaning
--------

To remove all build artifacts:

.. code-block:: bash

   cd docs
   make clean
