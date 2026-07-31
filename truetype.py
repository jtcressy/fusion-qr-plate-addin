"""Minimal TrueType font reader — glyph outlines and advance widths.

Only what this add-in needs: the `cmap`, `glyf`, `loca`, `head`, `hhea`,
`hmtx` and `maxp` tables of a TrueType (quadratic outline) font, including
composite glyphs and TrueType Collections. Written so the add-in stays
dependency-free instead of vendoring a full font toolkit.

Not supported: PostScript/CFF outlines (`.otf`) — `TrueTypeFont` raises
ValueError so callers can fall back to another font file.
"""

import struct

# Simple-glyph point flags
_ON_CURVE = 0x01
_X_SHORT = 0x02
_Y_SHORT = 0x04
_REPEAT = 0x08
_X_SAME_OR_POS = 0x10
_Y_SAME_OR_POS = 0x20

# Composite-glyph component flags
_ARG_1_AND_2_ARE_WORDS = 0x0001
_ARGS_ARE_XY_VALUES = 0x0002
_WE_HAVE_A_SCALE = 0x0008
_MORE_COMPONENTS = 0x0020
_WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
_WE_HAVE_A_TWO_BY_TWO = 0x0080

_MAX_COMPONENT_DEPTH = 8


class TrueTypeFont(object):
    def __init__(self, path):
        with open(path, "rb") as handle:
            self._data = handle.read()
        self.path = path
        self._tables = {}
        self._glyph_cache = {}
        self._read_table_directory()
        self._read_headers()
        self._read_cmap()

    # --- table directory -------------------------------------------------

    def _read_table_directory(self):
        data = self._data
        tag = data[:4]
        offset = 0
        if tag == b"ttcf":  # TrueType Collection: use the first font
            (offset,) = struct.unpack_from(">I", data, 12)
            tag = data[offset : offset + 4]
        if tag == b"OTTO":
            raise ValueError("CFF/PostScript outlines are not supported: " + self.path)
        if tag not in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
            raise ValueError("Not a TrueType font: " + self.path)

        (num_tables,) = struct.unpack_from(">H", data, offset + 4)
        for i in range(num_tables):
            entry = offset + 12 + i * 16
            name, _checksum, table_offset, length = struct.unpack_from(">4sIII", data, entry)
            self._tables[name.decode("latin-1").strip()] = (table_offset, length)

        for required in ("head", "maxp", "cmap", "glyf", "loca"):
            if required not in self._tables:
                raise ValueError(
                    "Font is missing the '{}' table: {}".format(required, self.path)
                )

    def _table(self, name):
        offset, length = self._tables[name]
        return self._data[offset : offset + length]

    # --- headers ---------------------------------------------------------

    def _read_headers(self):
        head = self._table("head")
        (self.units_per_em,) = struct.unpack_from(">H", head, 18)
        (index_to_loc_format,) = struct.unpack_from(">h", head, 50)
        (num_glyphs,) = struct.unpack_from(">H", self._table("maxp"), 4)
        self.num_glyphs = num_glyphs

        loca = self._table("loca")
        if index_to_loc_format == 0:
            raw = struct.unpack_from(">%dH" % (num_glyphs + 1), loca, 0)
            self._loca = [value * 2 for value in raw]
        else:
            self._loca = list(struct.unpack_from(">%dI" % (num_glyphs + 1), loca, 0))

        self._advances = []
        if "hhea" in self._tables and "hmtx" in self._tables:
            (num_h_metrics,) = struct.unpack_from(">H", self._table("hhea"), 34)
            hmtx = self._table("hmtx")
            for i in range(min(num_h_metrics, num_glyphs)):
                (advance,) = struct.unpack_from(">H", hmtx, i * 4)
                self._advances.append(advance)
        if not self._advances:
            self._advances = [self.units_per_em // 2]

    # --- character map ---------------------------------------------------

    def _read_cmap(self):
        cmap = self._table("cmap")
        (num_subtables,) = struct.unpack_from(">H", cmap, 2)
        best = None
        best_score = -1
        for i in range(num_subtables):
            platform, encoding, offset = struct.unpack_from(">HHI", cmap, 4 + i * 8)
            # Prefer Unicode full-repertoire, then Unicode BMP, then Mac Roman
            score = {
                (3, 10): 5,
                (0, 4): 5,
                (0, 6): 5,
                (3, 1): 4,
                (0, 3): 4,
                (0, 2): 3,
                (0, 1): 3,
                (0, 0): 3,
                (1, 0): 1,
            }.get((platform, encoding), 0)
            if score > best_score:
                best_score, best = score, offset
        if best is None:
            raise ValueError("Font has no usable cmap subtable: " + self.path)

        (fmt,) = struct.unpack_from(">H", cmap, best)
        if fmt == 4:
            self._cmap = self._parse_cmap4(cmap, best)
        elif fmt == 12:
            self._cmap = self._parse_cmap12(cmap, best)
        elif fmt == 6:
            self._cmap = self._parse_cmap6(cmap, best)
        elif fmt == 0:
            table = struct.unpack_from(">256B", cmap, best + 6)
            self._cmap = {code: gid for code, gid in enumerate(table) if gid}
        else:
            raise ValueError("Unsupported cmap format {}: {}".format(fmt, self.path))

    @staticmethod
    def _parse_cmap4(cmap, base):
        (seg_x2,) = struct.unpack_from(">H", cmap, base + 6)
        segments = seg_x2 // 2
        ends = struct.unpack_from(">%dH" % segments, cmap, base + 14)
        starts_at = base + 16 + seg_x2
        starts = struct.unpack_from(">%dH" % segments, cmap, starts_at)
        deltas = struct.unpack_from(">%dh" % segments, cmap, starts_at + seg_x2)
        range_offsets_at = starts_at + seg_x2 * 2
        range_offsets = struct.unpack_from(">%dH" % segments, cmap, range_offsets_at)

        mapping = {}
        for i in range(segments):
            start, end = starts[i], ends[i]
            if start > end or start == 0xFFFF:
                continue
            for code in range(start, end + 1):
                if range_offsets[i] == 0:
                    gid = (code + deltas[i]) & 0xFFFF
                else:
                    glyph_at = (
                        range_offsets_at + i * 2 + range_offsets[i] + (code - start) * 2
                    )
                    (gid,) = struct.unpack_from(">H", cmap, glyph_at)
                    if gid:
                        gid = (gid + deltas[i]) & 0xFFFF
                if gid:
                    mapping[code] = gid
        return mapping

    @staticmethod
    def _parse_cmap12(cmap, base):
        (num_groups,) = struct.unpack_from(">I", cmap, base + 12)
        mapping = {}
        for i in range(num_groups):
            start, end, start_gid = struct.unpack_from(">III", cmap, base + 16 + i * 12)
            if end - start > 0x10000:  # guard against absurd ranges
                end = start + 0x10000
            for offset in range(end - start + 1):
                mapping[start + offset] = start_gid + offset
        return mapping

    @staticmethod
    def _parse_cmap6(cmap, base):
        first, count = struct.unpack_from(">HH", cmap, base + 6)
        gids = struct.unpack_from(">%dH" % count, cmap, base + 10)
        return {first + i: gid for i, gid in enumerate(gids) if gid}

    # --- glyph access ----------------------------------------------------

    def glyph_id(self, char):
        return self._cmap.get(ord(char))

    def advance(self, glyph_id):
        if glyph_id < len(self._advances):
            return self._advances[glyph_id]
        return self._advances[-1]

    def glyph_contours(self, glyph_id, _depth=0):
        """Contours for a glyph, in font units.

        Returns a list of contours; each contour is a list of
        (x, y, on_curve) tuples in TrueType's quadratic representation.
        """
        if _depth == 0 and glyph_id in self._glyph_cache:
            return self._glyph_cache[glyph_id]
        if glyph_id + 1 >= len(self._loca):
            return []
        start, end = self._loca[glyph_id], self._loca[glyph_id + 1]
        if end <= start:
            return []  # empty glyph (e.g. space)

        glyf_offset = self._tables["glyf"][0]
        data = self._data
        base = glyf_offset + start
        (num_contours,) = struct.unpack_from(">h", data, base)

        if num_contours >= 0:
            contours = self._parse_simple_glyph(data, base, num_contours)
        elif _depth >= _MAX_COMPONENT_DEPTH:
            contours = []
        else:
            contours = self._parse_composite_glyph(data, base + 10, _depth)

        if _depth == 0:
            self._glyph_cache[glyph_id] = contours
        return contours

    @staticmethod
    def _parse_simple_glyph(data, base, num_contours):
        end_points = struct.unpack_from(">%dH" % num_contours, data, base + 10)
        num_points = end_points[-1] + 1 if end_points else 0
        cursor = base + 10 + num_contours * 2
        (instruction_length,) = struct.unpack_from(">H", data, cursor)
        cursor += 2 + instruction_length

        flags = []
        while len(flags) < num_points:
            flag = data[cursor]
            cursor += 1
            flags.append(flag)
            if flag & _REPEAT:
                repeat = data[cursor]
                cursor += 1
                flags.extend([flag] * repeat)
        flags = flags[:num_points]

        def read_coords(short_bit, same_bit):
            values = []
            value = 0
            local = cursor
            for flag in flags:
                if flag & short_bit:
                    delta = data[local]
                    local += 1
                    value += delta if flag & same_bit else -delta
                elif not flag & same_bit:
                    (delta,) = struct.unpack_from(">h", data, local)
                    local += 2
                    value += delta
                values.append(value)
            return values, local

        xs, cursor = read_coords(_X_SHORT, _X_SAME_OR_POS)
        ys, _ = read_coords(_Y_SHORT, _Y_SAME_OR_POS)

        contours = []
        start_index = 0
        for end_index in end_points:
            points = [
                (xs[i], ys[i], bool(flags[i] & _ON_CURVE))
                for i in range(start_index, end_index + 1)
            ]
            if len(points) >= 2:
                contours.append(points)
            start_index = end_index + 1
        return contours

    def _parse_composite_glyph(self, data, cursor, depth):
        contours = []
        while True:
            flags, component_gid = struct.unpack_from(">HH", data, cursor)
            cursor += 4
            if flags & _ARG_1_AND_2_ARE_WORDS:
                arg1, arg2 = struct.unpack_from(">hh", data, cursor)
                cursor += 4
            else:
                arg1, arg2 = struct.unpack_from(">bb", data, cursor)
                cursor += 2

            a = d = 1.0
            b = c = 0.0
            if flags & _WE_HAVE_A_SCALE:
                a = d = _f2dot14(data, cursor)
                cursor += 2
            elif flags & _WE_HAVE_AN_X_AND_Y_SCALE:
                a = _f2dot14(data, cursor)
                d = _f2dot14(data, cursor + 2)
                cursor += 4
            elif flags & _WE_HAVE_A_TWO_BY_TWO:
                a = _f2dot14(data, cursor)
                b = _f2dot14(data, cursor + 2)
                c = _f2dot14(data, cursor + 4)
                d = _f2dot14(data, cursor + 6)
                cursor += 8

            dx, dy = (arg1, arg2) if flags & _ARGS_ARE_XY_VALUES else (0, 0)
            for contour in self.glyph_contours(component_gid, depth + 1):
                contours.append(
                    [
                        (x * a + y * c + dx, x * b + y * d + dy, on_curve)
                        for x, y, on_curve in contour
                    ]
                )

            if not flags & _MORE_COMPONENTS:
                break
        return contours


def _f2dot14(data, offset):
    (raw,) = struct.unpack_from(">h", data, offset)
    return raw / 16384.0
