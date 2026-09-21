"""Static and behavioural checks for the HACS integration.

The integration is the *delivery* of the EMS package: it ships the same YAML
inside `custom_components/opendtu_ems/bundle/` and installs it into the config
folder. That means three things can silently go wrong, and all of them are
checked here:

1. the bundled copy drifts away from `packages/opendtu_ems.yaml`
2. the manifest / `hacs.json` stop meeting the HACS integration requirements
   (structure, required keys, key order, brand assets, translations)
3. the install rules damage a user's file (overwrite a newer or hand-edited
   file, forget the backup)

Run: `python tests/validate_integration.py`
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "opendtu_ems"
DOMAIN = "opendtu_ems"

MANIFEST_REQUIRED = ("domain", "name", "codeowners", "documentation", "issue_tracker", "version")
HACS_JSON_KEYS = {
    "name", "content_in_root", "zip_release", "filename", "hide_default_branch",
    "country", "homeassistant", "hacs", "persistent_directory", "render_readme",
}

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    """Record a failure (and print it) when the condition is false."""
    if not condition:
        failures.append(message)
        print(f"  !! {message}")
    else:
        print(f"  OK {message}")


def load_module(path: Path, name: str) -> Any:
    """Import a module straight from a file - the integration cannot be imported
    normally because it needs Home Assistant."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def png_size(path: Path) -> tuple[int, int] | None:
    """Width/height from the PNG header - no Pillow needed."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def manifest_checks() -> None:
    print("\n== manifest ==")
    path = INTEGRATION / "manifest.json"
    check(path.is_file(), "custom_components/opendtu_ems/manifest.json exists")
    if not path.is_file():
        return

    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in MANIFEST_REQUIRED:
        check(key in manifest, f"manifest has '{key}'")

    check(manifest.get("domain") == DOMAIN, f"domain is '{DOMAIN}'")
    check(manifest.get("config_flow") is True, "config_flow is true (the user adds it in the UI)")
    check(str(manifest.get("documentation", "")).startswith("https://"),
          "documentation is an https URL")
    check(manifest.get("issue_tracker", "").endswith("/issues"), "issue_tracker points at issues")
    check(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))),
          f"version is x.y.z (got {manifest.get('version')!r})")

    # hassfest requires: domain, name, then everything else alphabetically
    keys = list(manifest)
    rest = keys[2:]
    check(keys[:2] == ["domain", "name"], "key order starts with domain, name")
    check(rest == sorted(rest), f"remaining keys are alphabetical ({', '.join(rest)})")


def hacs_json_checks() -> None:
    print("\n== hacs.json ==")
    path = ROOT / "hacs.json"
    check(path.is_file(), "hacs.json exists")
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    check("name" in data, "hacs.json has a 'name' (the only required key)")
    unknown = sorted(set(data) - HACS_JSON_KEYS)
    check(not unknown, f"only allowed keys are used (unknown: {unknown or 'none'})")


def structure_checks() -> None:
    print("\n== HACS integration structure ==")
    check((INTEGRATION / "__init__.py").is_file(), "integration has __init__.py")
    check((INTEGRATION / "config_flow.py").is_file(), "integration has config_flow.py")
    check((INTEGRATION / "services.yaml").is_file(), "integration has services.yaml")
    check((INTEGRATION / "strings.json").is_file(), "integration has strings.json")
    check(len(list((ROOT / "custom_components").iterdir())) == 1,
          "exactly one integration in custom_components/ (HACS manages only the first)")

    # services.yaml and the registered service have to agree
    services = load_module(INTEGRATION / "const.py", "ems_const")
    declared = re.findall(r"^([a-z0-9_]+):", (INTEGRATION / "services.yaml").read_text("utf-8"), re.M)
    check(declared == [services.SERVICE_INSTALL],
          f"services.yaml declares {declared} == the registered {services.SERVICE_INSTALL!r}")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    check("hass.services.async_register(DOMAIN, SERVICE_INSTALL" in init,
          "the service is registered in async_setup (not per config entry)")


def brand_checks() -> None:
    print("\n== brand assets (HACS requirement) ==")
    icon = png_size(INTEGRATION / "brand" / "icon.png")
    icon2 = png_size(INTEGRATION / "brand" / "icon@2x.png")
    logo = png_size(INTEGRATION / "brand" / "logo.png")
    logo2 = png_size(INTEGRATION / "brand" / "logo@2x.png")

    check(icon == (256, 256), f"icon.png is 256x256 (got {icon})")
    check(icon2 == (512, 512), f"icon@2x.png is 512x512 (got {icon2})")
    check(logo is not None and 128 <= min(logo) <= 256,
          f"logo.png shortest side 128-256 (got {logo})")
    check(logo2 is not None and 256 <= min(logo2) <= 512,
          f"logo@2x.png shortest side 256-512 (got {logo2})")


def translation_checks() -> None:
    print("\n== translations ==")
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    check(en == strings, "translations/en.json matches strings.json")

    def keys(node: Any, prefix: str = "") -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                found |= keys(value, f"{prefix}.{key}" if prefix else key)
        else:
            found.add(prefix)
        return found

    expected = keys(strings)
    for lang in sorted((INTEGRATION / "translations").glob("*.json")):
        data = json.loads(lang.read_text(encoding="utf-8"))
        missing = sorted(expected - keys(data))
        check(not missing, f"{lang.name} has every key (missing: {missing or 'none'})")


def python_checks() -> None:
    print("\n== integration python ==")
    for path in sorted(INTEGRATION.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover
            check(False, f"{path.name} parses ({exc})")
        else:
            check(True, f"{path.name} parses")
        if path.name != "bundle.py":
            # everything except the pure logic needs Home Assistant
            source = path.read_text(encoding="utf-8")
            check("from homeassistant" in source or "import homeassistant" in source
                  or path.name == "const.py",
                  f"{path.name} imports Home Assistant (or is pure constants)")


def bundle_checks() -> None:
    print("\n== bundled files are identical to the sources ==")
    for source, bundled in (
        (ROOT / "packages" / "opendtu_ems.yaml", INTEGRATION / "bundle" / "opendtu_ems.yaml"),
        (ROOT / "dashboards" / "ems-overview.yaml", INTEGRATION / "bundle" / "ems-overview.yaml"),
    ):
        same = source.read_bytes() == bundled.read_bytes()
        check(same, f"{bundled.name} matches {source.relative_to(ROOT)}")
        if not same:
            print("     re-copy it: Copy-Item "
                  f"{source.relative_to(ROOT)} {bundled.relative_to(ROOT)} -Force")


def behaviour_checks() -> None:
    print("\n== install rules (bundle.py) ==")
    import tempfile

    bundle = load_module(INTEGRATION / "bundle.py", "ems_bundle")

    old = "#  version 1.5.0  ·  old\n# body old\n"
    new = "#  version 1.5.1  ·  new\n# body new\n"
    newer = "#  version 1.6.0  ·  future\n# body future\n"

    check(bundle.read_version(new) == "1.5.1", "version is read from the header comment")
    check(bundle.read_version("# no version here\n") is None, "a file without a header has no version")
    check(bundle.parse_version("1.5.10") > bundle.parse_version("1.5.9"),
          "versions compare numerically (1.5.10 > 1.5.9)")
    check(bundle.packages_configured("homeassistant:\n  packages: !include_dir_named packages\n"),
          "packages: is detected under homeassistant:")
    check(bundle.packages_configured("packages: !include_dir_named packages\n"),
          "packages: is detected at the top level")
    check(not bundle.packages_configured("default_config:\n"), "a config without packages is detected")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source = work / "opendtu_ems.yaml"
        target = work / "packages" / "opendtu_ems.yaml"
        source.write_text(new, encoding="utf-8")

        result = bundle.install_file(source, target)
        check(result.action == bundle.INSTALLED and target.read_text("utf-8") == new,
              "missing target -> installed")
        check(result.changed, "an install counts as a change (restart needed)")

        result = bundle.install_file(source, target)
        check(result.action == bundle.CURRENT and not result.changed,
              "identical target -> nothing to do")

        target.write_text(old, encoding="utf-8")
        result = bundle.install_file(source, target)
        backup = target.with_name(target.name + ".bak")
        check(result.action == bundle.UPDATED and target.read_text("utf-8") == new,
              "older target -> updated")
        check(backup.is_file() and backup.read_text("utf-8") == old,
              "the previous file is kept as .bak")
        backup.unlink()

        target.write_text(newer, encoding="utf-8")
        result = bundle.install_file(source, target)
        check(result.action == bundle.CURRENT and target.read_text("utf-8") == newer,
              "a newer local file is never overwritten")
        check(not backup.exists(), "no backup is made when nothing is written")

        target.write_text(new.replace("body new", "locally edited"), encoding="utf-8")
        result = bundle.install_file(source, target)
        check(result.action == bundle.CURRENT and "locally edited" in target.read_text("utf-8"),
              "a locally edited file at the same version is left alone")

        result = bundle.install_file(source, target, force=True)
        check(result.action == bundle.UPDATED and target.read_text("utf-8") == new,
              "force overwrites (the service does that)")
        check(backup.is_file(), "force keeps a backup too")
        backup.unlink()

        result = bundle.install_file(work / "missing.yaml", target)
        check(result.action == bundle.FAILED and result.error,
              "a missing bundle file is reported, not raised")

    # the module has to stay importable without Home Assistant
    source = (INTEGRATION / "bundle.py").read_text(encoding="utf-8")
    check(not re.search(r"^\s*(?:from|import)\s+homeassistant", source, re.M),
          "bundle.py has no Home Assistant imports")


def main() -> int:
    print(f"integration: {INTEGRATION.relative_to(ROOT)}")
    manifest_checks()
    hacs_json_checks()
    structure_checks()
    brand_checks()
    translation_checks()
    python_checks()
    bundle_checks()
    behaviour_checks()

    print("\n== result ==")
    if failures:
        print(f"  {len(failures)} FAILURES")
        return 1
    print("  integration checks passed (manifest, hacs.json, structure, brand, "
          "translations, install rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
