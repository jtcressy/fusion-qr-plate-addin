"""QR Plate — Fusion add-in.

Adds a "QR Code Plate" command to the SOLID > Create panel. The dialog offers
several content modes (Wi-Fi, contact card, phone, SMS, email, map location,
calendar event, payment URI, plain text), plus plate dimensions and optional
title text, and (re)builds one print-in-place solid: raised code and title in
their own Z band, printed in a second color via a slicer filament change at
the base thickness. Values are remembered per-document, so rerunning the
command pre-fills the last inputs.
"""

import importlib
import os
import sys
import traceback

import adsk.core
import adsk.fusion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fusion loads every add-in serially at startup and budgets ~5 ms per add-in,
# so run() must stay import-free: the QR encoder, font reader and geometry
# core are loaded the first time the command is actually invoked.
payloads = None
core = None


def _load_modules():
    """Import (or reload) the add-in's modules, on first command use.

    Fusion keeps modules in sys.modules across a Stop/Run of the add-in, so
    they are reloaded here in dependency order — qr_plate_core imports
    payloads, so it comes last — which makes restarting the add-in enough to
    pick up source edits.
    """
    global payloads, core
    import payloads as payloads_module
    import truetype as truetype_module
    import text_outline as text_outline_module
    import qr_plate_core as core_module

    payloads = importlib.reload(payloads_module)
    importlib.reload(truetype_module)
    importlib.reload(text_outline_module)
    core = importlib.reload(core_module)

CMD_ID = "jtcressyQRPlate"
# Command id used before the add-in was renamed; removed on start so users
# upgrading from the Wi-Fi-only version do not end up with two buttons.
LEGACY_CMD_IDS = ("jtcressyWiFiQRPlate",)
_app = None
_ui = None
_handlers = []

ERROR_ITEMS = ["L (7%)", "M (15%)", "Q (25%)", "H (30%)"]

# Populated by _load_modules(); both need the payloads module's mode names.
SECURITY_ITEMS = []
MODE_GROUPS = {}


def _build_mode_tables():
    """Field layout per content mode: mode -> (group input id, [field keys])."""
    global SECURITY_ITEMS, MODE_GROUPS
    SECURITY_ITEMS = list(payloads.SECURITY_MAP.keys())
    MODE_GROUPS = {
        payloads.MODE_WIFI: ("g_wifi", ["ssid", "password", "security", "hidden"]),
        payloads.MODE_CONTACT: (
            "g_contact",
            ["contact_name", "contact_phone", "contact_email", "contact_org",
             "contact_url", "contact_photo"],
        ),
        payloads.MODE_PHONE: ("g_phone", ["tel_number"]),
        payloads.MODE_SMS: ("g_sms", ["sms_number", "sms_message"]),
        payloads.MODE_EMAIL: ("g_email", ["email_to", "email_subject", "email_body"]),
        payloads.MODE_GEO: ("g_geo", ["geo_lat", "geo_lon"]),
        payloads.MODE_EVENT: (
            "g_event",
            ["event_title", "event_start", "event_end", "event_location"],
        ),
        payloads.MODE_PAY: ("g_pay", ["pay_uri"]),
        payloads.MODE_TEXT: ("g_text", ["text_content"]),
    }


STRING_LABELS = {
    "ssid": "Network name (SSID)",
    "password": "Password",
    "contact_name": "Name",
    "contact_phone": "Phone",
    "contact_email": "Email",
    "contact_org": "Organization",
    "contact_url": "Website",
    "contact_photo": "Photo URL (uses vCard)",
    "tel_number": "Phone number",
    "sms_number": "Phone number",
    "sms_message": "Message",
    "email_to": "To",
    "email_subject": "Subject",
    "email_body": "Body",
    "geo_lat": "Latitude",
    "geo_lon": "Longitude",
    "event_title": "Event title",
    "event_start": "Start (20260815T170000)",
    "event_end": "End (optional)",
    "event_location": "Location",
    "pay_uri": "URI (e.g. bitcoin:...)",
    "text_content": "Text",
}


def _design():
    return adsk.fusion.Design.cast(_app.activeProduct)


def _collect_params(inputs):
    params = dict(core.DEFAULTS)
    params["mode"] = payloads.MODES[inputs.itemById("mode").selectedItem.index]
    for _, fields in MODE_GROUPS.values():
        for key in fields:
            if key == "security":
                params[key] = SECURITY_ITEMS[inputs.itemById(key).selectedItem.index]
            elif key == "hidden":
                params[key] = inputs.itemById(key).value
            else:
                params[key] = inputs.itemById(key).value
    params["title"] = inputs.itemById("title").value
    for key in ("title_h", "plate_w", "base_h", "code_h", "corner_r", "chamfer"):
        params[key] = inputs.itemById(key).value
    params["quiet"] = inputs.itemById("quiet").value
    params["error"] = ERROR_ITEMS[inputs.itemById("error").selectedItem.index][0]
    return params


def _update_mode_visibility(inputs):
    selected = payloads.MODES[inputs.itemById("mode").selectedItem.index]
    for mode, (group_id, _) in MODE_GROUPS.items():
        inputs.itemById(group_id).isVisible = mode == selected


def _update_info(inputs):
    info = inputs.itemById("qr_info")
    try:
        params = _collect_params(inputs)
        matrix = core.qr_matrix(core.build_payload(params), params["error"])
        n = len(matrix)
        pitch_mm = params["plate_w"] * 10 / (n + 2 * int(params["quiet"]))
        text = "QR {0}x{0} - module {1:.2f} mm".format(n, pitch_mm)
        if pitch_mm < 0.8:
            text += "  (small: consider a wider plate or lower error correction)"
    except Exception as err:
        text = str(err)
    if info.text != text:
        info.text = text


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            _load_modules()
            _build_mode_tables()
            cmd = args.command
            cmd.setDialogInitialSize(400, 560)
            inputs = cmd.commandInputs
            saved = core.load_params(_design())

            mode_input = inputs.addDropDownCommandInput(
                "mode", "Content", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for mode in payloads.MODES:
                mode_input.listItems.add(mode, mode == saved["mode"])

            for mode, (group_id, fields) in MODE_GROUPS.items():
                group = inputs.addGroupCommandInput(group_id, mode)
                gi = group.children
                for key in fields:
                    if key == "security":
                        dropdown = gi.addDropDownCommandInput(
                            "security",
                            "Security",
                            adsk.core.DropDownStyles.TextListDropDownStyle,
                        )
                        for item in SECURITY_ITEMS:
                            dropdown.listItems.add(item, item == saved["security"])
                    elif key == "hidden":
                        gi.addBoolValueInput("hidden", "Hidden network", True, "", saved["hidden"])
                    else:
                        gi.addStringValueInput(key, STRING_LABELS[key], saved.get(key, ""))

            value = adsk.core.ValueInput.createByReal
            text = inputs.addGroupCommandInput("titleGroup", "Title (optional)")
            gi = text.children
            gi.addStringValueInput("title", "Title text", saved["title"])
            gi.addValueInput("title_h", "Text height", "mm", value(saved["title_h"]))

            plate = inputs.addGroupCommandInput("plateGroup", "Plate")
            gi = plate.children
            gi.addValueInput("plate_w", "Width", "mm", value(saved["plate_w"]))
            gi.addValueInput("base_h", "Base thickness", "mm", value(saved["base_h"]))
            gi.addValueInput("code_h", "Raised layer", "mm", value(saved["code_h"]))
            gi.addValueInput("corner_r", "Corner radius", "mm", value(saved["corner_r"]))
            gi.addValueInput("chamfer", "Rim chamfer", "mm", value(saved["chamfer"]))
            gi.addIntegerSpinnerCommandInput("quiet", "Quiet zone (modules)", 2, 10, 1, int(saved["quiet"]))
            error = gi.addDropDownCommandInput(
                "error", "Error correction", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for item in ERROR_ITEMS:
                error.listItems.add(item, item.startswith(saved["error"]))

            inputs.addTextBoxCommandInput("qr_info", "", "", 2, True)

            _update_mode_visibility(inputs)
            _update_info(inputs)

            for cls, event in (
                (ExecuteHandler, cmd.execute),
                (ValidateInputsHandler, cmd.validateInputs),
                (InputChangedHandler, cmd.inputChanged),
            ):
                handler = cls()
                event.add(handler)
                _handlers.append(handler)
        except Exception:
            _ui.messageBox("QR Code Plate failed:\n{}".format(traceback.format_exc()))


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs.command.commandInputs
            if args.input.id == "mode":
                _update_mode_visibility(inputs)
            if args.input.id == "security":
                open_network = inputs.itemById("security").selectedItem.index == 2
                inputs.itemById("password").isEnabled = not open_network
            if args.input.id != "qr_info":
                _update_info(inputs)
        except Exception:
            pass


class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            payloads.build_payload(_collect_params(args.inputs))
            args.areInputsValid = True
        except Exception:
            args.areInputsValid = False


# No executePreview handler on purpose: Fusion fires preview on every input
# change, and a full plate rebuild (booleans, extrudes, timeline edits) per
# keystroke froze the UI. The dialog previews nothing; OK builds once.
class ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            core.generate(_design(), _collect_params(args.command.commandInputs))
        except Exception:
            _ui.messageBox("QR Code Plate failed:\n{}".format(traceback.format_exc()))


def run(_context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        panel = _ui.allToolbarPanels.itemById("SolidCreatePanel")
        for stale_id in (CMD_ID,) + LEGACY_CMD_IDS:
            stale_control = panel.controls.itemById(stale_id)
            if stale_control:
                stale_control.deleteMe()
            stale_def = _ui.commandDefinitions.itemById(stale_id)
            if stale_def:
                stale_def.deleteMe()
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID,
            "QR Code Plate",
            "Generate a two-material QR code plate.\n\n"
            "Content modes: Wi-Fi network, contact card, phone, SMS, email, "
            "map location, calendar event, payment URI, or plain text. "
            "Builds one print-in-place solid; set a filament change at the "
            "base thickness to print the raised code in a second color. "
            "Rerun to edit the stored content or dimensions.",
            "resources/command",
        )
        created = CommandCreatedHandler()
        cmd_def.commandCreated.add(created)
        _handlers.append(created)

        control = panel.controls.addCommand(cmd_def)
        control.isPromoted = True
    except Exception:
        if _ui:
            _ui.messageBox("QR Code Plate failed to start:\n{}".format(traceback.format_exc()))


def stop(_context):
    try:
        panel = _ui.allToolbarPanels.itemById("SolidCreatePanel")
        for command_id in (CMD_ID,) + LEGACY_CMD_IDS:
            control = panel.controls.itemById(command_id)
            if control:
                control.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(command_id)
            if cmd_def:
                cmd_def.deleteMe()
    except Exception:
        pass
