To publish new release, cease merging new PRs to `main`, and carefully follow the below procedure:



## 1. create an issue, branch, and PR and new tag for release

- [ ] create an issue for the new release, "mint X.Y.Z" is a common title in this repository
- [ ] create a new branch off `main`, *give it a name different than the tag you are creating*
- [ ] edit the version number in `fremor/_version.py` to the desired version tag of format `X.Y.Z`
- [ ] open a PR to `main` in this repository after making the version change, and associate it with the issue



## 2. create a new tag for release, publish release to PyPI and github

- [ ] if checks pass after the previous steps, create the tag from the branch locally in your terminal via `git tag X.Y.Z;`
- [ ] push your locally created tag with `git checkout X.Y.Z; git push origin HEAD:refs/tags/X.Y.Z`
- [ ] the new tag `X.Y.Z` being pushed triggers the `pip` build and publish pipeline, wait for it to finish.
- [ ] find the newly built package on PyPI, download the newly built package's `tar.gz` file

WARNING: *any problems or mistakes after the next step are irreversible due to package immutability so make sure things are working before continuing*

- [ ] on github, create a new release *with the tarball you downloaded in the previous step*, generate contribution notes, and save the release
- [ ] check that the release looks right: it needs the PyPI `tar.gz` file with the `X.Y.Z` tag, and contribution notes.
- [ ] check that the generated zenodo [DOI](https://zenodo.org/records/20186257) and associated citation looks right on zenodo



## 3. publish release to `conda-forge` via `fremor-feedstock` fork

- [ ] use (create if needed) a `fremor-feedstock` [fork](https://github.com/ilaflott/fremor-feedstock) to create a new branch called `fremorX.Y.Z`
- [ ] adjust the version to `X.Y.Z` and update the `sha256` to what it says on PyPI in `recipe.yaml`
- [ ] open a [PR](https://github.com/conda-forge/fremor-feedstock/pull/3) to `conda-forge/fremor-feedstock`
- [ ] once checks pass, a reviewer with access to `conda-forge/fremor-feedstock` can approve and merge, kicking off the rest of the publishing pipeline to `conda-forge`



## 4. wrap-up

- [ ] back to the `fremor` PR we opened intially, edit the version number in `fremor/_version.py` to `X.Y.Z.post`, let the checks pass
- [ ] squash-merge the PR branch you used for creating the release to `main`
- [ ] if desired, create a module file and `conda` environment for GFDL resources, after the new version is available via `conda install`


### for reference

what a published release looks like...
- ... on PyPI: https://pypi.org/project/fremor/0.9.8/#fremor-0.9.8.tar.gz
- ... on github: https://github.com/NOAA-GFDL/fremor/releases/tag/0.9.8
- ... on `conda-forge`: https://anaconda.org/channels/conda-forge/packages/fremor/files
