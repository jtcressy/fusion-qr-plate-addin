# Privacy policy

**QR Plate collects no data.**

The add-in runs entirely inside Autodesk Fusion on your computer. It has no
network code: it does not phone home, check for updates, send telemetry or
analytics, or contact any server.

## What the add-in reads

- **What you type into its dialog** — network names, passwords, contact
  details, text. These are encoded into the QR geometry it builds and saved
  in the Fusion document you generate, as document attributes, so that
  reopening the command can pre-fill your previous entry. They are stored
  only in that document, which lives wherever you save it (typically your own
  Autodesk cloud storage or local disk).
- **Font files already installed on your computer**, read-only, to draw
  title text. The add-in reads glyph outlines from a system font such as
  Arial Bold. No font data leaves your machine and no fonts are redistributed
  with the add-in.

## What the add-in transmits

Nothing.

## What this means for your credentials

A Wi-Fi password encoded into a plate is readable by anyone who scans the
printed object or opens the Fusion document — that is the entire point of the
plate. Treat a generated plate, and any document containing one, the way you
would treat the password written on paper. If you share a design file, the
stored dialog values travel with it.

If you added a **photo URL** to a contact card, that URL is embedded in the
QR code and whoever scans it will request that image from wherever it is
hosted; that request is between the scanner and your host, not this add-in.

## Third-party components

The add-in bundles [segno](https://github.com/heuer/segno) (BSD 3-Clause) to
encode QR symbols. It performs no network access either.

## Contact

Questions: open an issue at
<https://github.com/jtcressy/fusion-qr-plate-addin/issues>.

*Last updated: 2026-07-31.*
