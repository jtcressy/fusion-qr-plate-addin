"""QR payload builders for each content mode.

Pure Python (no Fusion imports) so it can be unit-tested outside Fusion.
Each builder validates its inputs and raises ValueError with a
dialog-friendly message when something required is missing.
"""

MODE_WIFI = "Wi-Fi network"
MODE_CONTACT = "Contact card"
MODE_PHONE = "Phone call"
MODE_SMS = "Text message"
MODE_EMAIL = "Email"
MODE_GEO = "Map location"
MODE_EVENT = "Calendar event"
MODE_PAY = "Payment / crypto URI"
MODE_TEXT = "Plain text"

MODES = [
    MODE_WIFI,
    MODE_CONTACT,
    MODE_PHONE,
    MODE_SMS,
    MODE_EMAIL,
    MODE_GEO,
    MODE_EVENT,
    MODE_PAY,
    MODE_TEXT,
]

SECURITY_MAP = {"WPA/WPA2": "WPA", "WEP": "WEP", "Open (no password)": "nopass"}

FIELD_DEFAULTS = {
    "mode": MODE_WIFI,
    # Wi-Fi
    "ssid": "",
    "password": "",
    "security": "WPA/WPA2",
    "hidden": False,
    # Contact card (MECARD)
    "contact_name": "",
    "contact_phone": "",
    "contact_email": "",
    "contact_org": "",
    "contact_url": "",
    "contact_photo": "",
    # Phone / SMS
    "tel_number": "",
    "sms_number": "",
    "sms_message": "",
    # Email (MATMSG)
    "email_to": "",
    "email_subject": "",
    "email_body": "",
    # Map location
    "geo_lat": "",
    "geo_lon": "",
    # Calendar event
    "event_title": "",
    "event_start": "",
    "event_end": "",
    "event_location": "",
    # Payment URI / plain text
    "pay_uri": "",
    "text_content": "",
}


def _esc(value):
    """Escaping for WIFI:/MECARD:/MATMSG: fields."""
    for ch in "\\;,:\"":
        value = value.replace(ch, "\\" + ch)
    return value


def _esc_ical(value):
    """Escaping for iCalendar text values."""
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return value.replace("\n", "\\n")


def _require(value, message):
    value = value.strip()
    if not value:
        raise ValueError(message)
    return value


def _wifi(p):
    ssid = _require(p["ssid"], "SSID must not be empty")
    sec = SECURITY_MAP.get(p["security"], "WPA")
    payload = "WIFI:T:{};S:{};".format(sec, _esc(ssid))
    if sec != "nopass":
        password = _require(p["password"], "Password is required for a secured network")
        payload += "P:{};".format(_esc(password))
    if p["hidden"]:
        payload += "H:true;"
    return payload + ";"


def _contact(p):
    name = _require(p["contact_name"], "Contact needs at least a name")
    photo = p["contact_photo"].strip()
    if not photo:
        # Compact MECARD when there is no photo
        payload = "MECARD:N:{};".format(_esc(name))
        for key, tag in (
            ("contact_phone", "TEL"),
            ("contact_email", "EMAIL"),
            ("contact_org", "ORG"),
            ("contact_url", "URL"),
        ):
            value = p[key].strip()
            if value:
                payload += "{}:{};".format(tag, _esc(value))
        return payload + ";"

    # vCard 3.0 when a photo URL is present (MECARD has no photo field).
    # The photo is referenced by URL, not embedded: QR capacity cannot hold
    # base64 image data at printable module sizes.
    if not photo.startswith(("http://", "https://")):
        raise ValueError("Photo must be an http(s) URL — images cannot be embedded in a scannable plate")
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "N:{};;;;".format(_esc_ical(name)),
        "FN:" + _esc_ical(name),
    ]
    for key, tag in (
        ("contact_phone", "TEL"),
        ("contact_email", "EMAIL"),
        ("contact_org", "ORG"),
        ("contact_url", "URL"),
    ):
        value = p[key].strip()
        if value:
            lines.append("{}:{}".format(tag, _esc_ical(value)))
    lines.append("PHOTO;VALUE=URI:" + photo)
    lines.append("END:VCARD")
    return "\n".join(lines)


def _clean_number(number):
    return "".join(ch for ch in number if ch.isdigit() or ch == "+")


def _phone(p):
    number = _require(p["tel_number"], "Phone number must not be empty")
    return "tel:" + _clean_number(number)


def _sms(p):
    number = _require(p["sms_number"], "Phone number must not be empty")
    return "SMSTO:{}:{}".format(_clean_number(number), p["sms_message"].strip())


def _email(p):
    to = _require(p["email_to"], "Recipient address must not be empty")
    payload = "MATMSG:TO:{};".format(_esc(to))
    if p["email_subject"].strip():
        payload += "SUB:{};".format(_esc(p["email_subject"].strip()))
    if p["email_body"].strip():
        payload += "BODY:{};".format(_esc(p["email_body"].strip()))
    return payload + ";"


def _geo(p):
    try:
        lat = float(p["geo_lat"].strip())
        lon = float(p["geo_lon"].strip())
    except ValueError:
        raise ValueError("Latitude and longitude must be decimal numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be within ±90 and longitude within ±180")
    return "geo:{:.6f},{:.6f}".format(lat, lon).replace("-0.000000", "0.000000")


def _clean_stamp(value):
    stamp = value.strip().replace("-", "").replace(":", "").replace(" ", "T")
    if not (8 <= len(stamp) <= 16):
        raise ValueError(
            "Dates must look like 20260815T170000 (or 2026-08-15 17:00:00)"
        )
    return stamp


def _event(p):
    title = _require(p["event_title"], "Event needs a title")
    start = _clean_stamp(_require(p["event_start"], "Event needs a start time"))
    lines = [
        "BEGIN:VEVENT",
        "SUMMARY:" + _esc_ical(title),
        "DTSTART:" + start,
    ]
    if p["event_end"].strip():
        lines.append("DTEND:" + _clean_stamp(p["event_end"]))
    if p["event_location"].strip():
        lines.append("LOCATION:" + _esc_ical(p["event_location"].strip()))
    lines.append("END:VEVENT")
    return "\n".join(lines)


def _pay(p):
    uri = _require(p["pay_uri"], "Payment URI must not be empty")
    if ":" not in uri:
        raise ValueError("Payment URI should include a scheme, e.g. bitcoin:...")
    return uri


def _text(p):
    return _require(p["text_content"], "Text must not be empty")


_BUILDERS = {
    MODE_WIFI: _wifi,
    MODE_CONTACT: _contact,
    MODE_PHONE: _phone,
    MODE_SMS: _sms,
    MODE_EMAIL: _email,
    MODE_GEO: _geo,
    MODE_EVENT: _event,
    MODE_PAY: _pay,
    MODE_TEXT: _text,
}


def build_payload(params):
    mode = params.get("mode", MODE_WIFI)
    builder = _BUILDERS.get(mode)
    if builder is None:
        raise ValueError("Unknown content mode: {}".format(mode))
    return builder(params)
