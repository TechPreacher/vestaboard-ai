from dataclasses import dataclass

# The physical board is always 6x22 and that full grid is what gets delivered to
# the cloud API, regardless of device. A "device" only decides how much of that
# grid the message content uses (and how it's centered within it).
BOARD_ROWS = 6
BOARD_COLS = 22


@dataclass(frozen=True)
class DeviceSpec:
    key: str
    label: str
    lines: int  # content rows the device uses
    cols: int  # content cols per row

    @property
    def content_limit(self) -> int:
        return self.lines * self.cols

    @property
    def row_offset(self) -> int:
        """Top margin that vertically centers the content within the board."""
        return (BOARD_ROWS - self.lines) // 2

    @property
    def col_offset(self) -> int:
        """Left margin that horizontally centers the content within the board."""
        return (BOARD_COLS - self.cols) // 2


DEVICES: dict[str, DeviceSpec] = {
    "vestaboard": DeviceSpec("vestaboard", "Vestaboard", BOARD_ROWS, BOARD_COLS),
    "note": DeviceSpec("note", "Vestaboard Note", 3, 15),
}

DEFAULT_DEVICE = "note"


def get(key: str | None) -> DeviceSpec:
    return DEVICES.get(key or DEFAULT_DEVICE, DEVICES[DEFAULT_DEVICE])
