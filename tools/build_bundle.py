#!/usr/bin/env python3
"""Package the add-in as an Autodesk App Store `.bundle` (and a ZIP of it).

The App Store installs into `ApplicationPlugins`, which expects
PackageContents.xml at the bundle root and everything else under `Contents/`.
A plain GitHub install (this repo dropped into `AddIns/`) needs no packaging,
so this is only for store submissions.

    python3 tools/build_bundle.py [--version X.Y.Z]

Writes dist/ADSK.QRPlate.bundle/ and dist/ADSK.QRPlate.bundle.zip.
"""

import argparse
import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_NAME = "ADSK.QRPlate.bundle"

# Everything the add-in needs at runtime, relative to the repo root.
PAYLOAD = [
    "QRPlate.py",
    "QRPlate.manifest",
    "payloads.py",
    "qr_plate_core.py",
    "text_outline.py",
    "truetype.py",
    "lib",
    "resources",
    "LICENSE",
    "NOTICE",
    "PRIVACY.md",
]

EXCLUDE_DIRS = {"__pycache__", ".git"}


def manifest_version():
    with open(os.path.join(ROOT, "QRPlate.manifest")) as handle:
        return json.load(handle)["version"]


def copy_payload(contents_dir):
    for name in PAYLOAD:
        source = os.path.join(ROOT, name)
        target = os.path.join(contents_dir, name)
        if os.path.isdir(source):
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc"),
            )
        elif os.path.exists(source):
            shutil.copy2(source, target)
        else:
            sys.exit("missing payload entry: " + name)


def write_help(contents_dir, version):
    """Autodesk ships a generated quick-start page; provide our own too."""
    help_dir = os.path.join(contents_dir, "docs")
    os.makedirs(help_dir, exist_ok=True)
    with open(os.path.join(help_dir, "help.html"), "w") as handle:
        handle.write(
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n<title>QR Plate {version}</title>\n"
            "<style>body{{font:15px/1.6 -apple-system,Segoe UI,sans-serif;"
            "max-width:42em;margin:2em auto;padding:0 1em}}"
            "code{{background:#f2f3f5;padding:.1em .3em;border-radius:3px}}"
            "</style>\n</head>\n<body>\n"
            "<h1>QR Plate {version}</h1>\n"
            "<p>Generate printable, two-material QR code plates.</p>\n"
            "<h2>Getting started</h2>\n<ol>\n"
            "<li>Open or create a design.</li>\n"
            "<li>Choose <b>SOLID &rarr; Create &rarr; QR Code Plate</b>.</li>\n"
            "<li>Pick a <b>Content</b> type and fill in its fields.</li>\n"
            "<li>Optionally add <b>Title</b> text and adjust <b>Plate</b> sizes.</li>\n"
            "<li>Click <b>OK</b>.</li>\n</ol>\n"
            "<p>The result is a <code>QR Plate</code> component containing a "
            "<code>Base</code> body and a raised <code>Code</code> body. Export "
            "each as a mesh and assign a different filament to each in your "
            "slicer; they share one origin, so they stay aligned.</p>\n"
            "<h2>Tips</h2>\n<ul>\n"
            "<li>Keep modules at roughly 0.8 mm or larger; the dialog warns "
            "below that. Long payloads need a wider plate.</li>\n"
            "<li>Rerun the command in the same document to edit what is "
            "encoded &mdash; it rebuilds in place.</li>\n"
            "<li>Contact cards with a photo URL use vCard and grow "
            "noticeably; plan on a 55 mm plate or wider.</li>\n</ul>\n"
            "<h2>Privacy</h2>\n<p>The add-in collects and transmits nothing. "
            "It reads installed fonts locally to draw title text. Values you "
            "enter are stored in your Fusion document so the dialog can "
            "pre-fill them.</p>\n"
            "<h2>Support</h2>\n<p>"
            "<a href=\"https://github.com/jtcressy/fusion-qr-plate-addin/issues\">"
            "github.com/jtcressy/fusion-qr-plate-addin/issues</a></p>\n"
            "</body>\n</html>\n".format(version=version)
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="override the manifest version")
    args = parser.parse_args()

    version = args.version or manifest_version()
    dist = os.path.join(ROOT, "dist")
    bundle = os.path.join(dist, BUNDLE_NAME)
    contents = os.path.join(bundle, "Contents")

    if os.path.exists(bundle):
        shutil.rmtree(bundle)
    os.makedirs(contents)

    shutil.copy2(os.path.join(ROOT, "PackageContents.xml"), bundle)
    copy_payload(contents)
    write_help(contents, version)

    archive = bundle + ".zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for directory, dirnames, filenames in os.walk(bundle):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for filename in filenames:
                path = os.path.join(directory, filename)
                zf.write(path, os.path.relpath(path, dist))

    size_mb = os.path.getsize(archive) / (1024 * 1024)
    print("built {} (version {})".format(archive, version))
    print("archive size: {:.2f} MB (App Store limit: 600 MB)".format(size_mb))


if __name__ == "__main__":
    main()
