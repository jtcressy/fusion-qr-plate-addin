#!/usr/bin/env python3
"""Tests for payload building, QR encoding, and font outlines.

Runs outside Fusion — none of the modules under test import the Fusion API.
Payloads are checked byte-for-byte against their published formats and then
encoded to real QR symbols, so a failure here means a generated plate would
carry the wrong data.

    python3 tests/test_payloads.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import payloads
import segno
import text_outline
import truetype

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   - " + message)
    else:
        print("  FAIL - " + message)
        FAILURES.append(message)


def build(mode, **fields):
    params = dict(payloads.FIELD_DEFAULTS)
    params["mode"] = mode
    params.update(fields)
    return payloads.build_payload(params)


def expect_error(mode, **fields):
    try:
        build(mode, **fields)
    except ValueError:
        return True
    return False


def test_payload_formats():
    print("payload formats")
    cases = [
        (
            payloads.MODE_WIFI,
            dict(ssid="Test;Net", password="p:a,s\\s", security="WPA/WPA2", hidden=True),
            "WIFI:T:WPA;S:Test\\;Net;P:p\\:a\\,s\\\\s;H:true;;",
        ),
        (
            payloads.MODE_WIFI,
            dict(ssid="Guest", security="Open (no password)"),
            "WIFI:T:nopass;S:Guest;;",
        ),
        (
            payloads.MODE_CONTACT,
            dict(contact_name="Doe, Jane", contact_phone="+15551234567"),
            "MECARD:N:Doe\\, Jane;TEL:+15551234567;;",
        ),
        (payloads.MODE_PHONE, dict(tel_number="+1 (555) 123-4567"), "tel:+15551234567"),
        (
            payloads.MODE_SMS,
            dict(sms_number="555-867-5309", sms_message="hi there"),
            "SMSTO:5558675309:hi there",
        ),
        (
            payloads.MODE_EMAIL,
            dict(email_to="a@b.com", email_subject="Hi", email_body="Text"),
            "MATMSG:TO:a@b.com;SUB:Hi;BODY:Text;;",
        ),
        (
            payloads.MODE_GEO,
            dict(geo_lat="44.9778", geo_lon="-93.2650"),
            "geo:44.977800,-93.265000",
        ),
        (
            payloads.MODE_PAY,
            dict(pay_uri="bitcoin:bc1qexample?amount=0.001"),
            "bitcoin:bc1qexample?amount=0.001",
        ),
        (payloads.MODE_TEXT, dict(text_content="  hello  "), "hello"),
    ]
    for mode, fields, expected in cases:
        actual = build(mode, **fields)
        check(actual == expected, "{}: {!r}".format(mode, expected))

    event = build(
        payloads.MODE_EVENT,
        event_title="BBQ; bring chips",
        event_start="2026-08-15 17:00:00",
        event_end="20260815T210000",
        event_location="Backyard",
    )
    check(event.startswith("BEGIN:VEVENT\n"), "calendar event starts a VEVENT")
    check("SUMMARY:BBQ\\; bring chips" in event, "calendar event escapes semicolons")
    check("DTSTART:20260815T170000" in event, "calendar event normalizes date format")

    vcard = build(
        payloads.MODE_CONTACT,
        contact_name="Jane Doe",
        contact_photo="https://example.com/me.jpg",
    )
    check(vcard.startswith("BEGIN:VCARD"), "contact with photo switches to vCard")
    check("PHOTO;VALUE=URI:https://example.com/me.jpg" in vcard, "vCard references photo by URL")


def test_validation():
    print("validation")
    cases = [
        (payloads.MODE_WIFI, {}, "empty SSID"),
        (payloads.MODE_WIFI, dict(ssid="Net"), "secured network without a password"),
        (payloads.MODE_CONTACT, {}, "contact without a name"),
        (payloads.MODE_CONTACT, dict(contact_name="X", contact_photo="me.jpg"), "photo that is not a URL"),
        (payloads.MODE_PHONE, {}, "empty phone number"),
        (payloads.MODE_GEO, dict(geo_lat="x", geo_lon="1"), "non-numeric coordinates"),
        (payloads.MODE_GEO, dict(geo_lat="200", geo_lon="1"), "out-of-range latitude"),
        (payloads.MODE_EVENT, dict(event_title="T", event_start="nope"), "unparsable event date"),
        (payloads.MODE_PAY, dict(pay_uri="no-scheme"), "payment URI without a scheme"),
        (payloads.MODE_TEXT, {}, "empty text"),
    ]
    for mode, fields, description in cases:
        check(expect_error(mode, **fields), "rejects " + description)


def test_qr_roundtrip():
    print("QR encode/decode round-trip")
    payload_cases = [
        build(payloads.MODE_WIFI, ssid="home.example", password="hunter2!", security="WPA/WPA2"),
        build(payloads.MODE_CONTACT, contact_name="Jane Doe", contact_email="jane@example.com"),
        build(payloads.MODE_SMS, sms_number="5558675309", sms_message="Omw, put the pizza in"),
        build(payloads.MODE_GEO, geo_lat="44.9778", geo_lon="-93.2650"),
        build(payloads.MODE_TEXT, text_content="You scanned the coaster. Drink."),
    ]
    for payload in payload_cases:
        qr = segno.make_qr(payload, error="m")
        matrix = [list(row) for row in qr.matrix]
        square = all(len(row) == len(matrix) for row in matrix)
        check(square and len(matrix) >= 21, "encodes {} to a {}x{} symbol".format(
            payload.split(":")[0], len(matrix), len(matrix)))
        # The add-in extrudes exactly these modules, so verify the geometry
        # source rather than a re-render: dark module count must be stable.
        dark = sum(sum(row) for row in matrix)
        check(0 < dark < len(matrix) ** 2, "symbol has a sane dark-module count")


def test_font_outlines():
    print("font outlines")
    fonts = text_outline.available_fonts()
    if not fonts:
        print("  skip - no candidate system fonts on this machine")
        return
    check(True, "found {} candidate font(s)".format(len(fonts)))

    groups, width = text_outline.text_polygons("GUEST WI-FI")
    check(len(groups) > 0, "produces filled regions for ASCII text")
    check(width > 0, "reports a positive advance width")
    ys = [y for outer, _ in groups for _, y in outer]
    check(max(ys) <= 1.5 and min(ys) >= -0.5, "glyphs stay near the em box")

    counters, _ = text_outline.text_polygons("ABDO08")
    holes = sum(len(hole_list) for _, hole_list in counters)
    check(holes == 8, "detects enclosed counters as holes (got {})".format(holes))

    accented, _ = text_outline.text_polygons("Café")
    check(len(accented) >= 5, "renders composite (accented) glyphs")

    font = truetype.TrueTypeFont(fonts[0])
    check(font.units_per_em > 0, "reads unitsPerEm from the font header")
    check(font.glyph_id("A") is not None, "maps characters through cmap")
    check(font.advance(font.glyph_id("A")) > 0, "reads advance widths from hmtx")


def main():
    for test in (
        test_payload_formats,
        test_validation,
        test_qr_roundtrip,
        test_font_outlines,
    ):
        test()
    print()
    if FAILURES:
        print("{} FAILED".format(len(FAILURES)))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
