
################################################################################################
# RUN命令:          运行docker build时需要执行的shell命令
# CMD命令:          指定容器创建时的默认命令（可以被docker run覆盖）
# ENTRYPOINT命令:   指定容器创建时的主要命令（不可被docker run覆盖）
# COPY命令:         从本地复制文件到镜像中
# WORKDIR命令:      指定镜像中的默认路径
# SHELL命令：       覆盖Docker中默认的shell，用于RUN、CMD和ENTRYPOINT指令
# ARG命令：         定义在构建image过程中传递给构建器的变量，可使用 "docker build" 命令设置
# LABEL命令：       添加镜像的元数据，使用键值对的形式
# ENV命令：         在容器内部设置环境变量
################################################################################################

# Set the base image
FROM continuumio/miniconda3:latest AS builder

# Install system dependencies
# 安装C++编译器
RUN apt-get update && \
    apt-get install -y sudo libusb-1.0 gcc g++ python3-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/hummingbot

# Create conda environment
# 创建Conda虚拟环境并安装依赖包
COPY setup/environment.yml /tmp/environment.yml
RUN conda env create -f /tmp/environment.yml && \
    conda clean -afy && \
    rm /tmp/environment.yml

# Copy remaining files
# 注：只复制编译时必要的文件
COPY bin/ bin/
COPY hummingbot/ hummingbot/
COPY scripts/ scripts/
COPY controllers/ controllers/
COPY scripts/ scripts-copy/
COPY setup.py .
COPY LICENSE .
COPY README.md .

# activate hummingbot env when entering the CT
SHELL [ "/bin/bash", "-lc" ]
RUN echo "conda activate hummingbot" >> ~/.bashrc

COPY setup/pip_packages.txt /tmp/pip_packages.txt
RUN python3 -m pip install --no-deps -r /tmp/pip_packages.txt && \
    rm /tmp/pip_packages.txt


RUN python3 setup.py build_ext --inplace -j 8 && \
    rm -rf build/ && \
    find . -type f -name "*.cpp" -delete


# Build final image using artifacts from builder
FROM continuumio/miniconda3:latest AS release

# Dockerfile author / maintainer
LABEL maintainer="Fede Cardoso @dardonacci <federico@hummingbot.org>"

# Build arguments
ARG BRANCH=""
ARG COMMIT=""
ARG BUILD_DATE=""
LABEL branch=${BRANCH}
LABEL commit=${COMMIT}
LABEL date=${BUILD_DATE}

# Set ENV variables
ENV COMMIT_SHA=${COMMIT}
ENV COMMIT_BRANCH=${BRANCH}
ENV BUILD_DATE=${BUILD_DATE}

ENV INSTALLATION_TYPE=docker

# Install system dependencies
RUN apt-get update && \
    apt-get install -y sudo libusb-1.0 && \
    rm -rf /var/lib/apt/lists/*

# Create mount points
# 注：这些都是可变文件，conf/log/data/certs由程序生成，scripts/controllers可人为更新; 
# 镜像运行时由volume命令挂载对应本地目录，因此本地目录的更新可被程序使用.
RUN mkdir -p /home/hummingbot/conf /home/hummingbot/conf/connectors /home/hummingbot/conf/strategies /home/hummingbot/conf/controllers /home/hummingbot/conf/scripts /home/hummingbot/logs /home/hummingbot/data /home/hummingbot/certs /home/hummingbot/scripts /home/hummingbot/controllers

WORKDIR /home/hummingbot

# Copy all build artifacts from builder image
COPY --from=builder /opt/conda/ /opt/conda/
COPY --from=builder /home/ /home/

# Setting bash as default shell because we have .bashrc with customized PATH (setting SHELL affects RUN, CMD and ENTRYPOINT, but not manual commands e.g. `docker run image COMMAND`!)
SHELL [ "/bin/bash", "-lc" ]

# Set the default command to run when starting the container

CMD conda activate hummingbot && ./bin/hummingbot_quickstart.py 2>> ./logs/errors.log
