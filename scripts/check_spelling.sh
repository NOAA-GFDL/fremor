#!/bin/bash

# source me
# requires cspell, which can be conda-installed as desired.
# it's not a formal testing req, it's usually handled by a github action
cspell lint "**" --dot --gitignore --exclude "fremor/tests/test_files/*-cmor-tables/" --exclude ".gitignore" --exclude ".readthedocs.yaml" --exclude ".github" --exclude ".git"
