# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS verilator-build

ARG VERILATOR_VERSION=5.020
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git autoconf flex bison g++ make help2man perl python3 libfl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v${VERILATOR_VERSION} https://github.com/verilator/verilator.git /src/verilator \
    && cd /src/verilator \
    && autoconf \
    && ./configure --prefix=/opt/verilator \
    && make -j"$(nproc)" \
    && make install

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget build-essential ca-certificates libfl2 perl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=verilator-build /opt/verilator /opt/verilator
ENV PATH="/opt/verilator/bin:${PATH}"
RUN mkdir -p /usr/share/verilator && ln -sf /opt/verilator/share/verilator/include /usr/share/verilator/include

RUN curl -L -o /tmp/miniforge.sh \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh" \
    && bash /tmp/miniforge.sh -b -p /opt/miniforge3 \
    && rm /tmp/miniforge.sh
ENV PATH="/opt/miniforge3/bin:${PATH}"

COPY env.yml /tmp/env.yml
RUN conda env create -f /tmp/env.yml \
    && conda clean -afy \
    && rm /tmp/env.yml

RUN conda init bash \
    && echo "conda activate ic_dec" >> /root/.bashrc
ENV PATH="/opt/miniforge3/envs/ic_dec/bin:${PATH}"

SHELL ["conda", "run", "-n", "ic_dec", "/bin/bash", "-c"]
