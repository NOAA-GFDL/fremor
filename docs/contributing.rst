.. _contributing:

==============
For Developers
==============

Developers should consult this section for detailed information relevant to development and maintenance
of ``fremor``, after familiarizing themselves with the rest of the user-targeted documentation.


Contributing to ``fremor``
==============================


Get a Copy of the Code
----------------------

Get your own copy of the code:

.. code-block:: bash

   git clone --recursive git@github.com:NOAA-GFDL/fremor.git

Or replace with your fork's link (recommended).


Local/Editable Installation
---------------------------

Developers can test local changes by running ``pip install [-e] .`` inside of the root directory after
activating a virtual environment with ``python>=3.11`` and all requirements. This installs the
``fremor`` package locally with any local changes.

Development work on ``fremor`` should occur within a conda environment housing ``fremor``'s
requirements, and a local copy of the repository installed with ``pip`` using the ``-e/--editable`` flag.

.. code-block:: bash

   # Create the conda environment from environment.yaml
   conda env create -f environment.yaml
   conda activate fremor

   # Install in editable mode
   pip install -e .


Testing Your Local Changes
--------------------------

There are several ways to test your efforts locally during your development cycle. A few examples and
``fremor``-specific recommendations are described here, but contributors are welcome to be creative
so long as they provide documentation of what they have contributed.

All contributed code should come with a corresponding unit test.


Running CLI Calls
~~~~~~~~~~~~~~~~~

Most development cycles will involve focused efforts isolated to a specific ``fremor COMMAND *ARGV``,
where ``*ARGV`` stands in for a shell-style argument vector (e.g. ``-d /path/to/input -l varlist.json``).
The code is housed in the ``fremor/`` package directory, with the ``click`` CLI entry-point in
``fremor/fremor.py``.

The developer usually uses ``fremor COMMAND *ARGV`` as a test, focused on seeing the changes they are
introducing, developing the code until the desired result is achieved. The specific ``fremor COMMAND *ARGV``
call can often become a unit test in one of the corresponding files in ``fremor/tests/``. The
sought-after changes should become ``assert`` conditions encoded within the unit test. Both success and
failure conditions should ideally be tested.


Running Without ``click``
~~~~~~~~~~~~~~~~~~~~~~~~~

Every ``fremor COMMAND *ARGV`` approximately maps to a single function call (a ``*_subtool`` function
in the corresponding module). To remove ``click`` and the CLI aspect from testing, assuming the code
being executed is in ``fremor/cmor_mixer.py`` in a function called ``cmor_run_subtool``:

.. code-block:: bash

   python -i -c 'from fremor.cmor_mixer import cmor_run_subtool; cmor_run_subtool(**args)'


Writing ``pytest`` Unit Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the functionality to test is that of a CLI call, tests should use the ``CliRunner`` approach shown in
``fremor/tests/``. ``click``-based CLI calls should **not** be tested with ``subprocess.run`` within
``pytest``. See `click's testing documentation <https://click.palletsprojects.com/en/stable/testing/>`_
for more information.

If the functionality to test is removed from a CLI call, the usual pythonic testing approaches apply.

Run the test suite:

.. code-block:: bash

   pytest fremor/tests/ -v


Running the Linter
~~~~~~~~~~~~~~~~~~

``fremor`` uses ``pylint`` for code quality checks:

.. code-block:: bash

   pylint --rcfile pylintrc fremor/


Adding a New Requirement
------------------------

Currently, all required packages are ``conda`` packages listed in ``environment.yaml`` and also
equivalently in ``meta.yaml``. ``conda`` packages that have a corresponding ``pip`` package should
also be listed in ``pyproject.toml``.

New dependencies for ``fremor`` must have a ``conda`` package available through a non-proprietary
``conda`` channel, preferably the open-source ``conda-forge`` channel. Only ``conda-forge`` and
``noaa-gfdl`` channels are used.

Before adding a new requirement, the developer is responsible for verifying that the desired package
is safe, well-documented, and actively maintained. Consider the cost-benefit of introducing new
functionality via standard-library approaches first, and be prepared to defend the proposition of
adding a new third-party package.


How ``fremor`` is Updated
-----------------------------

``fremor`` is published and hosted as a Conda package on the
`NOAA-GFDL conda channel <https://anaconda.org/NOAA-GFDL>`_. On pushes to the ``main`` branch, the
package is automatically updated using the workflow defined in ``.github/workflows/publish_conda.yml``,
which is equivalent to ``.github/workflows/build_conda.yml`` with an extra ``conda publish`` step.


``logging`` Best Practices
--------------------------

Get Desired Verbosity
~~~~~~~~~~~~~~~~~~~~~

The ``logging`` module's configuration initially occurs in ``fremor/__init__.py``, and gets inherited
everywhere else ``logging`` creates a ``logger`` object under the ``fremor`` namespace. If your
development is being tested with a ``fremor COMMAND *ARGV`` style CLI call, add verbosity flags:

.. code-block:: bash

   fremor -vv run ...

If your development does not fit that category, the next easiest thing is to adjust the base ``logger``
object in ``fremor/__init__.py``. Adjust it back to the default verbosity level before requesting
a merge.


``logging`` Practice to Avoid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Avoid calling ``logging.basicConfig`` to re-configure logging behavior **outside** of
``fremor/__init__.py``. This creates another ``logging.handler`` without resolving the ambiguity
to previously defined loggers about which handler to use. If left in a PR at merge-time, this can cause
oddly silent logging behavior that is very tricky to debug.


Avoid ``os.chdir`` if You Can
-----------------------------

Directory changing in Python is not transient by default — if the interpreter changes directories, then
the result of ``os.getcwd()`` later in the program may change to an unexpected value, leading to
difficult bugs.

If you must use directory changing instead of managing directory targets explicitly as ``pathlib.Path``
instances, use the following pattern to safely ``chdir`` and ``chdir`` back:

.. code-block:: python

   go_back_here = os.getcwd()
   try:
       os.chdir(target_dir)
       # DO STUFF AFTER CHDIR HERE
   except Exception as exc:
       raise RuntimeError('some error explaining what went wrong') from exc
   finally:
       os.chdir(go_back_here)


``MANIFEST.in``
---------------

In the case where non-Python files like templates, examples, and outputs are to be included in the
``fremor`` package, ``MANIFEST.in`` can provide the solution. Ensure the file exists within the
correct folder and add a line such as ``include fremor/fileName.fileExtension``.

For more efficiency, if there are multiple files of the same type needed, use something like
``recursive-include fremor *.fileExtension`` which recursively includes every file matching that
extension within the specified directory and its subdirectories.


Contributing to Documentation
=============================

.. include:: contributing_to_docs.rst
