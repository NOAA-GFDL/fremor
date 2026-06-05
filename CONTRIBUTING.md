# Contributing to `fremor`

Thank you for considering contributing to `fremor`!

## Code of Conduct
By participating in this project, you are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Issues and Feature Requests
* **Create an Issue:** Before opening a pull request, it helps maintainers greatly to create a GitHub issue to reflect your contribution's background.
* **Use Templates if You Like:** If desired for extra structure, use one of the templates present in this repository.
* **Prioritize Clarity and Specifics:** Understandability is key, and achievable specifics keep developers sane.

## Local Development Setup
Developers should use virtual environments for their development, as `fremor` is primarily intended for use within them (`conda` or otherwise). 
While using the tool outside of a virtual environment is possible, it is not tested in our CI pipelines.

To set up your local development environment:

1. *Clone the repository:*
    ```bash
    # omit --recursive if you don't want tables as submodules
    git clone --recursive [https://github.com/NOAA-GFDL/fremor.git](https://github.com/NOAA-GFDL/fremor.git)
    cd fremor
    ```

2. *Create the `conda` environment, activate, install:*
    ```bash
    conda env create -f environment.yaml
    conda activate fremor
    pip install -e .
    ```

3. *Run tests with `pytest` and lint with `pylint` after hacking:*
    ```bash
    pytest fremor/tests/
    pylint --rcfile pylintrc fremor
    ```



## Opening a Pull Request
Forks and branches are welcome, but branches are only useable by a privileged, trusted few who work with 
this repository. First time contributors must always make their first contribution from a fork.

**Workflow:** Branch off of `main` for your feature or bug fix, and (generally) treat `main` as the trunk

**Committing:** Commit your changes and be sure to reference the original GitHub issue in your commit message. The more atomic, the better!

**CI Checks:** Ensure all GitHub Actions (such as `create_test_conda_env`, `pylint`) pass successfully.

> **Note:** For maintainers pushing a new published release, please see the specific Release Procedure outlined in the [README.md](README.md).
