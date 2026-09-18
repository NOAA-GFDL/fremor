ARG BASE_IMAGE=slurm-cluster:25.05.3
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-lc"]

RUN set -euo pipefail \
    && (yum -y install Lmod tcsh || yum -y install lmod tcsh) \
    && yum clean all \
    && rm -rf /var/cache/yum

RUN set -euo pipefail \
    && wget -qO /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
    && bash /tmp/miniforge.sh -b -p /opt/conda \
    && rm -f /tmp/miniforge.sh

ENV PATH=/opt/conda/bin:$PATH

COPY . /opt/fremor

RUN source /opt/conda/etc/profile.d/conda.sh \
    && conda config --remove channels defaults || true \
    && conda config --set channel_priority strict \
    && conda env create -p /opt/conda/envs/fremor -f /opt/fremor/environment.yaml \
    && conda activate /opt/conda/envs/fremor \
    && pip install -e /opt/fremor \
    && conda clean -afy

WORKDIR /opt/fremor
