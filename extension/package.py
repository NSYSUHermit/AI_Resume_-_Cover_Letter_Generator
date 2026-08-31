"""Build the zip that gets uploaded to the Chrome Web Store.

An allowlist, not an ignore list. A store package is published to strangers, so
the failure mode of forgetting an ignore rule is leaking a file, while the
failure mode of forgetting an allowlist entry is a build error you notice
immediately. Only the files Chrome actually loads go in - the developer-facing
ones (README, PRIVACY, STORE_LISTING, this script, make_icons.py) stay in the
repo where they are useful and out of the package where they are dead weight.

Run from this directory:  python3 package.py
"""
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"

# Everything Chrome loads at runtime, and nothing else. Paths are relative to
# this directory and are written into the zip with the same layout.
PAYLOAD = [
    "manifest.json",
    "background.js",
    "sidepanel.html",
    "sidepanel.css",
    "sidepanel.js",
    "filler.js",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
]

# Only for the hand-install zip. The store rejects stray files, but someone
# unzipping this to load it unpacked has no idea what to do next, and no store
# listing to read it from.
SIDELOAD_EXTRAS = ["INSTALL.md", "PRIVACY.md"]


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    version = manifest["version"]

    missing = [name for name in PAYLOAD if not (HERE / name).exists()]
    if missing:
        raise SystemExit(
            "missing files: " + ", ".join(missing)
            + "\n(icons are generated - run `python3 icons/make_icons.py` first)"
        )

    # Cross-check the manifest against the payload rather than trusting the list
    # above to stay in sync by hand: a script added to the extension but not to
    # PAYLOAD would produce a zip that installs and then breaks at runtime.
    declared = set()
    declared.update(manifest["icons"].values())
    declared.add(manifest["background"]["service_worker"])
    declared.add(manifest["side_panel"]["default_path"])
    for entry in manifest.get("content_scripts", []):
        declared.update(entry.get("js", []))
    undeclared = sorted(declared - set(PAYLOAD))
    if undeclared:
        raise SystemExit(
            "manifest references files PAYLOAD does not ship: " + ", ".join(undeclared)
        )

    DIST.mkdir(exist_ok=True)

    def build(path, names):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name in names:
                bundle.write(HERE / name, name)
        return path.stat().st_size / 1024

    store = DIST / f"ai-resume-sidepanel-{version}.zip"
    kb = build(store, PAYLOAD)
    print(f"store upload : {store.relative_to(HERE.parent)}  ({kb:.0f} KB, {len(PAYLOAD)} files)")
    print("               https://chrome.google.com/webstore/devconsole")

    # The hand-install zip unzips to a folder the recipient points
    # chrome://extensions at, so it carries its own instructions.
    names = PAYLOAD + [n for n in SIDELOAD_EXTRAS if (HERE / n).exists()]
    sideload = DIST / f"ai-resume-sidepanel-{version}-install.zip"
    kb = build(sideload, names)
    print(f"hand install : {sideload.relative_to(HERE.parent)}  ({kb:.0f} KB, {len(names)} files)")


if __name__ == "__main__":
    main()
