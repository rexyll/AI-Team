FROM haproxytech/haproxy-alpine@sha256:c9d745967c0651adbfdf0150a739a833a790f3b4eced1758374a6b0f3820c8d9

LABEL org.opencontainers.image.title="AI-Team Local Docker TCP Router"
LABEL org.opencontainers.image.description="HAProxy TCP Router with a pinned socat Runtime API transport helper."
LABEL com.ai-team.router.image-contract="1"
LABEL com.ai-team.router.haproxy-version="3.4.7"
LABEL com.ai-team.router.socat-package-version="1.8.1.3-r0"
LABEL com.ai-team.router.base-image="haproxytech/haproxy-alpine@sha256:c9d745967c0651adbfdf0150a739a833a790f3b4eced1758374a6b0f3820c8d9"

RUN apk add --no-cache socat=1.8.1.3-r0 && \
    test -x /usr/local/sbin/haproxy && \
    test -x /usr/bin/socat && \
    haproxy -vv | grep -F "HAProxy version 3.4.7" && \
    socat -V

# Keep the upstream HAProxy entrypoint and command. Host-owned configuration,
# the persistent map directory, and the Unix admin socket are mounted later
# by the Router bootstrap; this image recipe does not start a container.
