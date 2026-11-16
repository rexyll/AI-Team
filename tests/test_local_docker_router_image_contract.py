from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker" / "router" / "Dockerfile"


def test_router_image_base_uses_full_immutable_multi_platform_digest():
    content = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"(?m)^FROM ([^\s]+)$", content)
    assert match is not None
    reference = match.group(1)
    assert reference.startswith("haproxytech/haproxy-alpine@sha256:")
    assert re.fullmatch(r"haproxytech/haproxy-alpine@sha256:[0-9a-f]{64}", reference)
    assert ":latest" not in content
    assert "FROM haproxytech/haproxy-alpine:3.4.7" not in content


def test_router_image_pins_haproxy_base_version_and_socat_package():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert 'LABEL com.ai-team.router.haproxy-version="3.4.7"' in content
    assert 'LABEL com.ai-team.router.socat-package-version="1.8.1.3-r0"' in content
    assert "apk add --no-cache socat=1.8.1.3-r0" in content


def test_router_image_records_contract_and_base_identity_labels():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert 'LABEL com.ai-team.router.image-contract="1"' in content
    assert 'LABEL com.ai-team.router.base-image="haproxytech/haproxy-alpine@sha256:' in content
    assert "test -x /usr/local/sbin/haproxy" in content
    assert "test -x /usr/bin/socat" in content
