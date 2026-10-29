"""Build 1649370 event IDs and parameter widths from the verified runtime EXE.

Source image SHA-256: 141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380
The event-name pointer array starts at VA 0xE5FD38 (EV_NONE, ID 0) and has
185 consecutive EV_* entries. The width table is VA 0xDA93F0, indexed by the
same event ID; the native -94 reader at 0x66FB60 uses it for player events.
Keep this Build-specific data separate from the C1 event map.
"""

EVENT_PARAMETER_WIDTHS164: tuple[int, ...] = (
    11, 0, 6, 14, 14, 32, 32, 32, 32, 0, 14, 6,  # 0..11
    2, 2, 2, 2, 3, 11, 11, 0, 0, 0, 0, 0,  # 12..23
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 11,  # 24..35
    11, 11, 11, 11, 11, 5, 5, 8, 8, 0, 0, 5,  # 36..47
    5, 0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,  # 48..59
    0, 0, 0, 5, 1, 2, 2, 2, 2, 2, 2, 0,  # 60..71
    11, 11, 11, 2, 2, 0, 11, 0, 5, 5, 12, 8,  # 72..83
    8, 8, 0, 0, 0, 8, 0, 0, 8, 0, 8, 8,  # 84..95
    8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,  # 96..107
    8, 8, 8, 9, 8, 18, 18, 18, 18, 9, 10, 9,  # 108..119
    10, 16, 16, 16, 16, 0, 19, 17, 18, 16, 8, 0,  # 120..131
    0, 0, 0, 0, 0, 11, 0, 0, 0, 11, 19, 12,  # 132..143
    0, 0, 0, 0, 0, 8, 0, 0, 6, 6, 6, 6,  # 144..155
    6, 10, 13, 0, 0, 5, 5, 11, 11, 11, 0, 0,  # 156..167
    0, 0, 1, 4, 12, 0, 6, 0, 0, 0, 0, 0,  # 168..179
    0, 8, 2, 0, 0,  # 180..184
)

EV_FIRE_WEAPON164 = 41
EV_FIRE_WEAPON_LASTSHOT164 = 42
EV_SV_FIRE_WEAPON164 = 54
EV_SV_FIRE_WEAPON_LASTSHOT164 = 55
