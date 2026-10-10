ARG BUILD_FROM
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /opt/app

COPY app/requirements.txt /opt/app/requirements.txt

# tzdata hoort erbij omdat de containerklok anders op UTC blijft staan en
# "vandaag" tussen middernacht en 02:00 de vorige dag is. ca-certificates
# is nodig voor de verbinding met MyManus.
RUN \
    apk add --no-cache \
        ca-certificates \
        tzdata \
    && pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app /opt/app
COPY rootfs /

RUN chmod a+x /usr/bin/rooster-app

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL \
    io.hass.name="Rooster" \
    io.hass.description="MyManus-rooster en geschat salaris" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}"

CMD ["/usr/bin/rooster-app"]
