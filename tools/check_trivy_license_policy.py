from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
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


def _parse_iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"license exception {label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"license exception {label} must be an ISO date") from exc


def _validated_exceptions(
    policy: dict[str, Any],
    lock_components: dict[str, str],
    blocked: set[str],
    as_of: date,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    raw_exceptions = policy.get("exceptions")
    if not isinstance(raw_exceptions, list):
        raise ValueError("license exceptions must be a list")
    validated: dict[tuple[str, str, str], dict[str, Any]] = {}
    required_strings = (
        "package", "version", "license", "classification", "approved_by",
        "approved_at", "expires_on", "rationale",
    )
    for exception in raw_exceptions:
        if not isinstance(exception, dict):
            raise ValueError("license exception must be an object")
        for field in required_strings:
            if not isinstance(exception.get(field), str) or not exception[field].strip():
                raise ValueError(f"license exception requires non-empty {field}")
        package = _normalize_name(exception["package"])
        version = exception["version"]
        license_name = exception["license"]
        classification = exception["classification"].upper()
        if package not in lock_components or lock_components[package] != version:
            raise ValueError(f"license exception package/version is not in production lock: {package}=={version}")
        if classification not in blocked:
            raise ValueError("license exception must name an explicitly blocked classification")
        approved_at = _parse_iso_date(exception["approved_at"], "approved_at")
        expires_on = _parse_iso_date(exception["expires_on"], "expires_on")
        if approved_at > as_of:
            raise ValueError("license exception approval date is in the future")
        if expires_on < as_of or expires_on < approved_at:
            raise ValueError(f"license exception is expired or has invalid expiry: {package}=={version}")
        obligations = exception.get("obligations")
        if (
            not isinstance(obligations, list)
            or not obligations
            or any(not isinstance(item, str) or not item.strip() for item in obligations)
        ):
            raise ValueError("license exception requires explicit redistribution obligations")
        key = (package, version, license_name)
        if key in validated:
            raise ValueError(f"duplicate license exception: {package}=={version} {license_name}")
        validated[key] = exception
    return validated


def evaluate_license_report(
    report: dict[str, Any],
    lock_components: dict[str, str],
    policy: dict[str, Any],
    *,
    as_of: date | None = None,
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
    try:
        exceptions = _validated_exceptions(
            policy, lock_components, blocked, as_of or datetime.now(timezone.utc).date()
        )
    except ValueError as exc:
        exceptions = {}
        problems.append(str(exc))

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

    findings: list[dict[str, Any]] = []
    exceptions_applied: list[dict[str, str]] = []
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
            normalized_package = _normalize_name(package_name)
            normalized_category = category.upper()
            package_version = observed.get(normalized_package)
            override = overrides.get(license_name)
            effective_category = str(override.get("classification", "")).upper() if isinstance(override, dict) else normalized_category
            exception = exceptions.get((normalized_package, package_version or "", license_name))
            exception_applied = bool(\n                exception\n                and normalized_category in blocked\n                and str(exception.get("classification", "")).upper() == normalized_category\n            )
            record = {
                "package": package_name,
                "version": package_version or "",
                "license": license_name,
                "scanner_classification": normalized_category,
                "classification": effective_category,
                "severity": severity.upper(),
                "override_applied": isinstance(override, dict),
                "exception_applied": exception_applied,
            }
            findings.append(record)
            if exception_applied and exception is not None:
                exceptions_applied.append({
                    "package": package_name,
                    "version": package_version or "",
                    "license": license_name,
                    "expires_on": exception["expires_on"],
                    "approved_by": exception["approved_by"],
                })
            if normalized_package not in lock_components:
                problems.append(f"license finding references unlocked package: {package_name}")
            if effective_category in blocked and not exception_applied:
                problems.append(
                    f"{package_name} license {license_name} is blocked ({effective_category})"
                )
            elif effective_category not in allowed and effective_category not in blocked:
                problems.append(
                    f"{package_name} license {license_name} has unrecognized category {category}"
                )

    applied_keys = {(item["package"].lower(), item["version"], item["license"]) for item in exceptions_applied}\n    for key in exceptions:\n        if key not in applied_keys:\n            problems.append(f"configured license exception did not match a scanner finding: {key[0]}=={key[1]} {key[2]}")\n\n    scanner = report.get("Trivy", {})
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
        "exceptions_applied": exceptions_applied,
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
