``fremor``'s documentation is built with ``sphinx`` and written in reStructuredText.
A decent cheat-sheet for reStructuredText can be found
`at this gist <https://gist.github.com/SMotaal/24006b13b354e6edad0c486749171a70#sections>`__.


With a PR to NOAA-GFDL/fremor (recommended)
----------------------------------------------

This approach is the easiest and most automated option for open-source contributors. It is completely
appropriate for casual editing of the docs and previewing the changes.

* Make a branch, either with ``NOAA-GFDL/fremor`` as the remote, or your own fork.
* Edit a file any non-zero amount, commit that change to your branch, and push. If the branch is
  identical to ``main``, you cannot open a PR.
* Once the PR is opened, a ``readthedocs`` workflow will be run, even if that PR is in draft mode.
  To confirm it is running (or did run), open your PR in a web browser, scroll to the bottom to find
  the latest workflow runs under "checks", and click the ``readthedocs`` workflow.
* If the doc build is successful, you should see the ``fremor`` documentation page. If unsuccessful,
  you should see a ``404`` error.
* To review documentation differences, use the "Show diff" checkbox, which gives an explicit visual
  difference highlight right on the built webpage.


Local Sphinx Build
------------------

This approach is good for deep debugging of the documentation build.


Lightweight Approach (recommended for docs-only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you only need to build documentation and don't need the full ``fremor`` environment,
you can use a minimal setup. This approach uses ``autodoc_mock_imports`` in ``docs/conf.py``
to mock heavy dependencies like ``netCDF4``, ``cmor``, ``xarray``, etc.

From the root directory of your local repository copy:

.. code-block:: bash

   # Create a lightweight docs-only environment
   conda create -n fremor-docs python=3.11 -y
   conda activate fremor-docs

   # Install minimal dependencies
   pip install sphinx renku-sphinx-theme sphinx-rtd-theme click pyyaml jsonschema

   # Generate API docs and build
   sphinx-apidoc --ext-autodoc --output-dir docs fremor/ --separate
   sphinx-build docs docs/build

This will produce warnings about missing imports from test modules, but the build will succeed.
To view the result, open ``docs/build/index.html`` in your browser.


Full Environment Approach
~~~~~~~~~~~~~~~~~~~~~~~~~

If you are also developing and testing ``fremor`` functionality, set up a full conda environment:

.. code-block:: bash

   # Create the full environment
   conda env create -f environment.yaml
   conda activate fremor

   # Install in editable mode
   pip install -e .

   # Install documentation dependencies
   pip install sphinx renku-sphinx-theme sphinx-rtd-theme rstcheck

   # Generate API docs and build
   sphinx-apidoc --ext-autodoc --output-dir docs fremor/ --separate
   sphinx-build docs docs/build

Then open ``docs/build/index.html`` with your favorite web browser. You should be able to click around
the locally built HTML and links should work as expected.

.. note::

   ``sphinx-build`` is quite permissive, though loud. It makes accurate and numerous complaints, but
   is often able to successfully finish anyway. After the first successful build, many warnings will not
   be displayed a second time unless the file throwing the warning was changed. To get all build output
   like the first run, add ``-E`` or ``--fresh-env`` to the call to avoid using Sphinx's build cache.


RST Linting
~~~~~~~~~~~

Before submitting documentation changes, run ``rstcheck`` to catch syntax issues:

.. code-block:: bash

   rstcheck --recursive docs/

This is also run as a pre-build step in the Read the Docs configuration.
