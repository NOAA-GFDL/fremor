To publish new release, cease merging new PRs to `main`, and carefully follow the below procedure:



## first, create a new tag for release

- [ ] create a new branch off `main`, *give it a name different than the exact tag you are creating*
- [ ] edit the version number in `fremor/_version.py` to the desired version tag of format `X.Y.Z`
- [ ] open a PR to `main` in this repository after making the version change
- [ ] if checks pass, create the tag from the branch locally in your terminal, with `git tag X.Y.Z;`



## second, publish release to PyPI, then github, in that order

- [ ] push your locally created tag with `git checkout X.Y.Z; git push origin HEAD:refs/tags/X.Y.Z`
- [ ] pushing the new tag `X.Y.Z` triggers the `pip` build and publish pipeline, wait for it to finish and find it on PyPI.
- [ ] on PyPI, download the built package `tar.gz` file for version `X.Y.Z`

WARNING: *any problems or mistakes after the next step are irreversible due to package immutability so make sure things are working before continuing*

- [ ] on github, create a new release *including the tarball you downloaded in the previous step*, generate contribution notes, and save the release
- [ ] check that the release looks right: it needs the PyPI `tar.gz` file with the `X.Y.Z` tag, and contribution notes.
- [ ] check that the generated zenodo [DOI](https://zenodo.org/records/20186257) and associated citation looks right on 



## third, publish release to `conda-forge` via `fremor-feedstock` fork

- [ ] use (create if needed) a `fremor-feedstock` [fork](https://github.com/ilaflott/fremor-feedstock) to create a new branch called `fremorX.Y.Z`
- [ ] adjust the version to `X.Y.Z` and update the `sha256` to what it says on PyPI in `recipe.yaml`
- [ ] open a [PR](https://github.com/conda-forge/fremor-feedstock/pull/3) to `conda-forge/fremor-feedstock`
- [ ] once checks pass, a reviewer with access to `conda-forge/fremor-feedstock` can approve and merge, kicking off the rest of the publishing pipeline to `conda-forge`



## wrap-up

- [ ] back to the `fremor` PR we opened intially.
- [ ] edit the version number in `fremor/_version.py` to `X.Y.Z.post`, let the checks pass
- [ ] merge the PR branch you used for creating the release to `main`


### for reference

what a published release on PyPI looks like: https://pypi.org/project/fremor/0.9.3/#fremor-0.9.3.tar.gz

what a published PyPI package on github looks like: https://github.com/NOAA-GFDL/fremor/releases/tag/0.9.3

what a published PyPI package on `conda-forge` looks like: https://anaconda.org/channels/conda-forge/packages/fremor/files
