from python:3.8.1-buster

LABEL name="apichanges" \
      homepage="https://github.com/awslabs/aws-sdk-api-changes" \
      maintainer="Kapil Thangavelu <https://twitter.com/kapilvt>"

RUN adduser --disabled-login apichanges
COPY --chown=apichanges:apichanges . /home/apichanges
RUN echo "deb http://deb.debian.org/debian buster-backports main" >> /etc/apt/sources.list

RUN apt-get -q update  \
    && apt-get -q -y install \
	libxml2-dev libxslt1-dev libcairo2-dev build-essential libffi-dev \
	git curl unzip zstd \
    && apt-get -y -t buster-backports install libgit2-dev \
    && cd /home/apichanges \
    && pip3 install -r requirements.txt \
    && python3 setup.py develop \
    && curl -LSfs https://japaric.github.io/trust/install.sh | \
	sh -s -- --git casey/just --target x86_64-unknown-linux-musl --to /usr/local/bin \
    && apt-get --yes remove build-essential \
    && apt-get purge --yes --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -Rf /var/cache/apt/ \
    && rm -Rf /var/lib/apt/lists/* \
    && rm -Rf /root/.cache/

USER apichanges
WORKDIR /home/apichanges
ENV LC_ALL="C.UTF-8" LANG="C.UTF-8" TZ=":/etc/localtime"
ENTRYPOINT ["/usr/local/bin/just"]

