# Third-Party Notices

This file records third-party components included in the project's dependency set. Each component remains governed by its own license; the project license does not replace or relicense third-party software.

## Production dependencies

### tqdm 4.70.1

- Dependency path: transitive dependency of `openai`
- License expression reported by Trivy: `MPL-2.0 AND MIT`
- Mozilla Public License 2.0: https://www.mozilla.org/MPL/2.0/
- MIT License: https://opensource.org/license/mit/
- Package source: https://pypi.org/project/tqdm/4.70.1/

Redistribution obligations:

- Preserve the applicable upstream copyright, license, and attribution notices.
- Provide recipients with the applicable MPL-2.0 and MIT license texts or authoritative license URLs when redistributing this component.
- If MPL-covered files are modified and distributed, make the corresponding MPL-covered source available under MPL-2.0 and comply with its notice and source-disclosure requirements.
- Do not interpret the project's PolyForm license as changing the license of this dependency.

The dependency-license policy exception is narrowly scoped to `tqdm==4.70.1` with the exact expression `MPL-2.0 AND MIT`, approved on 2026-11-15 and subject to review by 2027-02-13. It does not authorize other versions, packages, license expressions, or reciprocal-license findings.

## Container image runtime dependencies

### socat 1.8.1.3-r0 (Alpine Linux v3.23 package)

- Purpose: fixed-argv Docker exec transport helper for the HAProxy Unix Runtime API socket.
- Package: socat=1.8.1.3-r0 from Alpine Linux v3.23 main repository.
- License expression reported by Alpine package metadata: GPL-2.0-only WITH OpenSSL-Exception.
- Package index: https://pkgs.alpinelinux.org/packages?branch=v3.23&name=socat
- The image also inherits HAProxy and Alpine base-image content; preserve and review upstream notices when redistributing the built image.
