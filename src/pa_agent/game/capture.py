import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import mss
import mss.tools

from ..errors import BridgeError
from ..logging import utc_now
from .window import WindowManager


def capture_game(manager: WindowManager, directory: Path, region: tuple[int, int, int, int] | None = None) -> dict:
    window = manager.find()
    manager.validate(window)
    rect = window.client.crop(*region) if region else window.client
    native = manager.native.user
    left, top, width, height = [native.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
    if rect.left < left or rect.top < top or rect.left + rect.width > left + width or rect.top + rect.height > top + height:
        raise BridgeError("Game capture rectangle extends off-screen; move the whole window onto the desktop.")
    with mss.MSS() as screen:
        frame = screen.grab(asdict(rect))
        manager.validate(window)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("frame-" + uuid4().hex + ".png")
        mss.tools.to_png(frame.rgb, frame.size, output=str(path))
    metadata = {"timestamp": utc_now(), "path": str(path.resolve()), "width": rect.width, "height": rect.height,
                "window": asdict(window), "region": region, "backend": "mss-desktop-crop",
                "occlusion_verified": False, "note": "Foreground client-area pixels. Overlays may appear; inspect the image."}
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata
