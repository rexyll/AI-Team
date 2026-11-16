# AI-Team Router image recipe

This is a local build recipe, not a published image. It intentionally does not
select a mutable tag or publish a registry artifact.

## Pinned inputs

- HAProxy base: haproxytech/haproxy-alpine 3.4.7, pinned by the immutable
  multi-platform index digest sha256:c9d745967c0651adbfdf0150a739a833a790f3b4eced1758374a6b0f3820c8d9.
- Runtime API transport helper: Alpine v3.23 socat package 1.8.1.3-r0.
- Image contract labels record the exact HAProxy version, socat package version,
  contract version, and base-image reference.

The base index digest identifies an immutable multi-platform image index;
Docker resolves the platform-specific child image for the builder architecture.
The Dockerfile pins the base by digest and installs socat by exact package
version. This does not by itself produce a reproducible final image digest:
the locally built image ID must be captured from Docker and treated as the
artifact identity by the Host provider.

## Build and verify

    docker build --pull -f docker/router/Dockerfile -t ai-team-router:local .
    docker image inspect --format "{{.Id}}" ai-team-router:local
    docker run --rm --entrypoint /bin/sh ai-team-router:local -ec 'command -v haproxy; command -v socat; haproxy -vv; socat -V; apk info -v | grep -Fx 'socat-1.8.1.3-r0''

The CI router-image-smoke job performs the same build and verifies the exact
HAProxy/socat versions and image contract labels on linux/amd64. It does not
start a Router container, validate generated HAProxy configuration, publish
the image, or claim daemon-backed routing E2E.

The image inherits upstream HAProxy image content and licenses. The socat
package is separately listed in THIRD_PARTY_NOTICES.md.
