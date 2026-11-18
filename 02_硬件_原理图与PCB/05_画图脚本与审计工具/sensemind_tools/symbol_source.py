#!/usr/bin/env python3
"""Generate EasyEDA Pro symbol document source (the ||-delimited text format)."""
import json
import random
import string
import time


def _client():
    return "".join(random.choice("0123456789abcdef") for _ in range(16))


class SymbolSource:
    def __init__(self, name, uuid, bbox, designator="U?"):
        self.name = name
        self.uuid = uuid
        self.bbox = bbox  # [x1, y1, x2, y2]
        self.designator = designator
        self.client = _client()
        self.ticket = 0
        self.rows = []

    def _row(self, head, body):
        self.ticket += 1
        head = dict(head, ticket=self.ticket, client=self.client)
        return json.dumps(head, separators=(",", ":"), ensure_ascii=False) + "||" + \
            json.dumps(body, separators=(",", ":"), ensure_ascii=False) + "|"

    def add_part(self, part_id):
        self.part_id = part_id
        self.rows.append(self._row({"type": "PART", "id": part_id},
                                   {"BBOX": self.bbox, "title": part_id}))

    def add_attr(self, rid, key, value, zindex, parent="", visible=False, x=None, y=None,
                 align="LEFT_BOTTOM"):
        self.rows.append(self._row({"type": "ATTR", "id": rid},
                                   {"partId": self.part_id, "groupId": "", "locked": False,
                                    "zIndex": zindex, "parentId": parent, "key": key,
                                    "value": value, "keyVisible": False,
                                    "valueVisible": visible, "x": x, "y": y, "rotation": 0,
                                    "color": None, "fillColor": None, "fontFamily": None,
                                    "fontSize": None, "strikeout": False, "underline": False,
                                    "italic": False, "fontWeight": False, "align": align,
                                    "version": "2.0"}))

    def add_rect(self, rid, x1, y1, x2, y2, zindex):
        self.rows.append(self._row({"type": "RECT", "id": rid},
                                   {"partId": self.part_id, "groupId": "", "locked": False,
                                    "zIndex": zindex, "dotX1": x1, "dotY1": y1,
                                    "dotX2": x2, "dotY2": y2, "radiusX": 0, "radiusY": 0,
                                    "rotation": 0, "strokeColor": None, "strokeStyle": None,
                                    "fillColor": None, "strokeWidth": None, "fillStyle": None}))

    def add_pin(self, pid, x, y, length, rotation, number, name, ptype, zindex):
        self.rows.append(self._row({"type": "PIN", "id": pid},
                                   {"partId": self.part_id, "groupId": "", "locked": False,
                                    "zIndex": zindex, "display": True, "x": x, "y": y,
                                    "length": length, "rotation": rotation,
                                    "color": None, "pinShape": "NONE"}))
        # name inside the body, number just outside the body edge
        if rotation == 0:      # pin on left side, extends right into body
            name_x, name_y, name_align = x + length + 4, y - 2.5, "LEFT_BOTTOM"
            num_x, num_y, num_align = x + 6, y + 3, "RIGHT_BOTTOM"
        elif rotation == 180:  # pin on right side, extends left into body
            name_x, name_y, name_align = x - length - 4, y - 2.5, "RIGHT_BOTTOM"
            num_x, num_y, num_align = x - 6, y + 3, "LEFT_BOTTOM"
        else:                  # vertical pins
            name_x, name_y, name_align = x + 2, y - 4, "LEFT_BOTTOM"
            num_x, num_y, num_align = x + 2, y + 4, "LEFT_BOTTOM"

        self.add_attr(pid + "n", "Pin Name", name, zindex + 1, parent=pid, visible=True,
                      x=name_x, y=name_y, align=name_align)
        self.add_attr(pid + "u", "Pin Number", number, zindex + 2, parent=pid, visible=True,
                      x=num_x, y=num_y, align=num_align)
        self.add_attr(pid + "t", "Pin Type", ptype, zindex + 3, parent=pid, visible=False,
                      x=x, y=y)

    def build(self):
        now = str(int(time.time() * 1000))
        head = json.dumps({"type": "DOCHEAD"}, separators=(",", ":")) + "||" + json.dumps(
            {"docType": "SYMBOL", "client": self.client, "uuid": self.uuid,
             "updateTime": int(now), "version": now, "editVersion": "4.1.78", "user": {}},
            separators=(",", ":")) + "|"
        canvas = json.dumps({"type": "CANVAS", "ticket": 0, "id": "CANVAS", "client": self.client},
                            separators=(",", ":")) + "||" + json.dumps(
            {"originX": 0, "originY": 0}, separators=(",", ":")) + "|"
        return "\n".join([head, canvas] + self.rows)
