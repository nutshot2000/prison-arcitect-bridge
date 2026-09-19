from dataclasses import dataclass

from .errors import BridgeError


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    def point(self, x: int, y: int) -> tuple[int, int]:
        if type(x) is not int or type(y) is not int:
            raise BridgeError("Coordinates must be integer client pixels.")
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise BridgeError(f"Point ({x}, {y}) outside {self.width}x{self.height} client area.")
        return self.left + x, self.top + y

    def crop(self, x: int, y: int, width: int, height: int) -> "Rect":
        self.point(x, y)
        if type(width) is not int or type(height) is not int or width < 1 or height < 1:
            raise BridgeError("Crop dimensions must be positive integers.")
        self.point(x + width - 1, y + height - 1)
        return Rect(self.left + x, self.top + y, width, height)


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    pid: int
    executable: str
    created: float
    title: str
    client: Rect
    focused: bool
    minimized: bool
    dpi: int
