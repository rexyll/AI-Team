from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)"
)


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _read_lock(path: Path) -> dict[str, str]:
    components: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = line.split(";", 1)[0].strip()
        match = _REQUIREMENT.match(requirement)
        if match is None:
            raise ValueError(f"unsupported lock requirement at line {line_number}")
        name = _normalize_name(match.group("name"))
        version = match.group("version")
        if name in components:
            raise ValueError(f"duplicate locked package: {name}")
        components[name] = version
    if not components:
        raise ValueError("production lock contains no exact package pins")
    return components


def evaluate_license_report(
    report: dict[str, Any],
    lock_components: dict[str, str],
    policy: dict[str, Any],
) -> dict[str, Any]:
    problems: list[str] = []
    allowed = {str(item).upper() for item in policy.get("allowed_classifications", [])}
    blocked = {str(item).upper() for item in policy.get("blocked_classifications", [])}
    overrides = policy.get("license_classification_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
        problems.append("license classification overrides must be an object")
    for license_name, override in overrides.items():
        if (
            not isinstance(override, dict)
            or str(override.get("classification", "")).upper() not in allowed
            or not isinstance(override.get("source"), str)
            or not override.get("source").startswith("https://")
            or not isinstance(override.get("rationale"), str)
            or not override.get("rationale").strip()
        ):
            problems.append(f"invalid or ungrounded license classification override: {license_name}")
    if not allowed or not blocked or allowed & blocked:
        problems.append("license policy classifications are missing or overlap")
    if policy.get("unknown_license_policy") != "deny":
        problems.append("unknown license policy must be deny")
    if policy.get("exceptions") != []:
        problems.append("license exceptions require a separately reviewed implementation")

    results = report.get("Results")
    if not isinstance(results, list):
        results = []
    package_results = [
        item for item in results
        if isinstance(item, dict) and item.get("Class") == "lang-pkgs"
    ]
    if len(package_results) != 1:
        problems.append("license scan must contain exactly one language package result")
        packages: list[dict[str, Any]] = []
    else:
        packages_value = package_results[0].get("Packages")
        packages = packages_value if isinstance(packages_value, list) else []

    observed: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict):
            problems.append("license scan contains a malformed package record")
            continue
        raw_name = package.get("Name")
        version = package.get("Version")
        if not isinstance(raw_name, str) or not isinstance(version, str):
            problems.append("license scan package is missing name or version")
            continue
        name = _normalize_name(raw_name)
        if name in observed:
            problems.append(f"license scan contains duplicate package: {name}")
            continue
        observed[name] = version
        licenses = package.get("Licenses")
        if not isinstance(licenses, list) or not licenses:
            problems.append(f"{name} has no declared license metadata")
        elif any(not isinstance(item, str) or not item.strip() for item in licenses):
            problems.append(f"{name} has an empty or malformed license expression")

    if observed != lock_components:
        missing = sorted(set(lock_components) - set(observed))
        extra = sorted(set(observed) - set(lock_components))
        mismatched = sorted(
            name for name in set(observed) & set(lock_components)
            if observed[name] != lock_components[name]
        )
        if missing:
            problems.append(f"license scan omitted locked packages: {', '.join(missing)}")
        if extra:
            problems.append(f"license scan contains unlocked packages: {', '.join(extra)}")
        if mismatched:
            problems.append(f"license scan versions differ from lock: {', '.join(mismatched)}")

    findings: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict) or item.get("Class") != "license":
            continue
        licenses_value = item.get("Licenses", [])
        if not isinstance(licenses_value, list):
            problems.append("license findings are malformed")
            continue
        for finding in licenses_value:
            if not isinstance(finding, dict):
                problems.append("license finding is malformed")
                continue
            package_name = finding.get("PkgName")
            license_name = finding.get("Name")
            category = finding.get("Category")
            severity = finding.get("Severity")
            if not all(isinstance(value, str) and value.strip() for value in (
                package_name, license_name, category, severity
            )):
                problems.append("license finding is missing package, name, category, or severity")
                continue
            normalized_category = category.upper()
            override = overrides.get(license_name)
            effective_category = normalized_category
            if isinstance(override, dict):
                effective_category = str(override.get("classification", "")).upper()
            record = {
                "package": package_name,
                "license": license_name,
                "scanner_classification": normalized_category,
                "classification": effective_category,
                "severity": severity.upper(),
                "override_applied": isinstance(override, dict),
            }
            findings.append(record)
            if _normalize_name(package_name) not in lock_components:
                problems.append(f"license finding references unlocked package: {package_name}")
            if effective_category in blocked:
                problems.append(
                    f"{package_name} license {license_name} is blocked ({effective_category})"
                )
            elif effective_category not in allowed:
                problems.append(
                    f"{package_name} license {license_name} has unrecognized category {category}"
                )

    scanner = report.get("Trivy", {})
    scanner_version = scanner.get("Version") if isinstance(scanner, dict) else None
    if not isinstance(scanner_version, str) or not scanner_version.strip():
        problems.append("Trivy report is missing scanner version")

    return {
        "status": "failed" if problems else "passed",
        "scanner": "trivy",
        "scanner_version": scanner_version,
        "packages_expected": len(lock_components),
        "packages_observed": len(observed),
        "license_findings": findings,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--lock-file", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("dependency-license-policy-result.json"))
    args = parser.parse_args(argv)

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(policy, dict):
            raise ValueError("license report and policy must be JSON objects")
        lock_components = _read_lock(args.lock_file)
        result = evaluate_license_report(report, lock_components, policy)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: license policy evidence unavailable: {exc}", file=sys.stderr)
        return 2

    print(
        f"Trivy license policy: {result['status']} "
        f"({result['packages_observed']}/{result['packages_expected']} production packages)"
    )
    for problem in result["problems"]:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
