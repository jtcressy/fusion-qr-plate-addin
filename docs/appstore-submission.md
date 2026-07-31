# Autodesk App Store submission notes

Reference for listing QR Plate on the Autodesk App Store (now branded the
**Design and Make Marketplace**; URLs and forms still say "App Store").
Publishing there is optional — the GitHub release ZIP works without it.

Everything below was gathered from Autodesk's publisher documentation. Items
marked **unconfirmed** could not be verified from official sources; ask
`appsubmissions@autodesk.com` rather than guessing.

## What Autodesk does for you

You do **not** build an MSI or PKG. Submit a single `.zip` containing a
`.bundle` folder; Autodesk builds the platform installers and sends the final
package back for your sign-off.

- Upload limit: 600 MB, `.zip` (no self-extracting executables).
- Publishing is free. Free apps owe no commission.
- A PayPal Business/Premier account is only needed for paid apps.
- Tax paperwork for free-app publishers: **unconfirmed**.

## Bundle layout

App Store installs land in `ApplicationPlugins`, not the `AddIns` folder this
repo targets, so the tree is rearranged at packaging time:

```
ADSK.QRPlate.bundle/
├── PackageContents.xml        <- already in this repo
└── Contents/
    ├── QRPlate.py             <- entry module (ModuleName in PackageContents.xml)
    ├── QRPlate.manifest
    ├── payloads.py  qr_plate_core.py  text_outline.py  truetype.py
    ├── resources/             <- icons
    ├── docs/help.html         <- quick-start page (HelpFile)
    └── lib/segno/             <- vendored dependency
```

Install paths for reference:
- Windows `%APPDATA%\Autodesk\ApplicationPlugins\`
- macOS `~/Library/Application Support/Autodesk/ApplicationPlugins/`

Build it with:

```bash
python3 tools/build_bundle.py     # produces dist/ADSK.QRPlate.bundle + .zip
```

## Requirements this add-in already satisfies

| Requirement | Status |
| --- | --- |
| Load time under 0.005 s | `run()` only registers the command; every module and the vendored encoder import lazily on first command use |
| No new toolbar panel | Adds a control to the existing SOLID → Create panel |
| No copyleft dependencies | Only [segno](https://github.com/heuer/segno) (BSD 3-Clause); see `NOTICE` |
| Version incremented per submission | `QRPlate.manifest` and `PackageContents.xml`; CI fails a release if the tag and manifest disagree |
| Works on latest Fusion | Verified on 2704.1.36 |
| No data collection | Fonts are read locally; nothing is transmitted (see `PRIVACY.md`) |

**Copyleft is an automatic rejection** — GPL, LGPL and AGPL are all named,
with no dynamic-linking exception. Keep future dependencies MIT/BSD/Apache-2.0.

## Assets and copy needed for the listing form

| Field | Limit | Prepared |
| --- | --- | --- |
| App Name | 50 chars, must not contain an Autodesk product name | "QR Plate — printable QR code generator" |
| Short description | 200 chars | see README intro |
| Description | 4000 chars, rich text | adapt README "Features" |
| App icon | **120 × 120**, ≤ 2 MB, needs a visible border | `resources/app-icon-120.png` |
| Command icons | 32 × 32 (16 × 16 also used) | `resources/command/` |
| Screenshots | up to 10, ≤ 2000 × 2000, 72/96 DPI; **budget 2 MB each** (docs say 20 MB, the widget says 2 MB) | `docs/example-plate.png` plus dialog captures |
| General usage instructions | 2000 chars | adapt README "Usage" |
| Installation/Uninstallation | 1000 chars | write literally `standard text` when Autodesk builds the installer |
| Support information | 1000 chars | GitHub Issues URL |
| Categories | 1–4 per store | e.g. 3D Printing, Modeling, Utilities |
| Privacy policy | **mandatory, even for free apps** — linked on the listing *and* readable inside the app | `PRIVACY.md`; surface it from the dialog before submitting |
| EULA | Autodesk's standard EULA is fine; a custom one must include Publisher Agreement Exhibit A terms and be shown on first run | use the standard EULA |

Also worth stating in *Additional Information*: the add-in reads locally
installed font files to build title text and transmits nothing. No Autodesk
rule prohibits local font reads, but it pre-empts a reviewer question.

## Review process

1. Submit → a reviewer makes contact within **24–48 hours**
   (email `appsubmissions@autodesk.com` if not).
2. Autodesk builds the installer and returns it for your approval.
3. Official guidance says approval takes **up to 2 weeks**; publisher forum
   reports describe multi-week to two-month turnarounds in practice, with
   updates taking about three weeks per round.

Cross-platform support is optional — you pick the OS at submission. If the
bundle differs per platform, file a separate submission per OS (the Clone
button copies the listing fields).

## Open questions to raise with the reviewer

- `autodeskProduct` in the manifest: current API help says `"Fusion"`, while
  shipped bundles and samples use `"Fusion360"` (this repo uses `"Fusion360"`).
- Who signs/notarizes the macOS package, since Autodesk builds it.
- Whether free-app publishers must file tax information.
