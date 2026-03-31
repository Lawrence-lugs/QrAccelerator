FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies and verilator
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    verilator \
    && rm -rf /var/lib/apt/lists/*

# Install miniforge3
RUN curl -L -o /tmp/miniforge.sh \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh" \
    && bash /tmp/miniforge.sh -b -p /opt/miniforge3 \
    && rm /tmp/miniforge.sh

ENV PATH="/opt/miniforge3/bin:${PATH}"

# Create conda environment
COPY env.yml /tmp/env.yml
RUN conda env create -f /tmp/env.yml \
    && conda clean -afy \
    && rm /tmp/env.yml

# Activate environment by default in interactive shells
RUN conda init bash \
    && echo "conda activate ic_dec" >> /root/.bashrc

# Default shell for RUN uses conda env
SHELL ["conda", "run", "-n", "ic_dec", "/bin/bash", "-c"]
