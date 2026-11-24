# PyInstaller spec for the Windows release build.
#
# Build with packaging/build_windows.ps1 (it also copies config/ and
# assets/ next to the exe and makes the zip and installer). Running
# PyInstaller by hand from the poe_qol folder works too:
#     pyinstaller --noconfirm packaging/twice_corrupted.spec
#
# Output: dist/TwiceCorrupted/TwiceCorrupted.exe (+ _internal/).
# config/ and assets/ are deliberately NOT bundled into _internal/: the
# app reads and writes them (user.yaml, slot profiles, logs) next to the
# exe, see poe_qol/paths.py.
from pathlib import Path

ROOT = Path(SPECPATH).parent            # the poe_qol project folder
ICON = ROOT / "assets" / "app_icon.ico"

# Macros are discovered at runtime (engine/registry.py imports every
# module in poe_qol.macros) and some features import lazily, so list
# every module of the package rather than relying on import tracing.
_SRC = ROOT / "src"
_OWN_MODULES = sorted(
    ".".join(f.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for f in (_SRC / "poe_qol").rglob("*.py")
    # tools/ are developer scripts (brand renderer), not part of the app
    if "tools" not in f.relative_to(_SRC).parts)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    # Imported lazily / only on Windows, so name them explicitly.
    hiddenimports=_OWN_MODULES + [
        "keyboard",
        "pydirectinput",
        "mss",
        "numpy",
        "PySide6.QtSvg",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Not used by any shipped feature (vision/detect.py is unreachable).
    excludes=["cv2", "tkinter", "matplotlib", "pytest", "PyInstaller"],
    noarchive=False,
)
# ---- trim Qt ----------------------------------------------------------
# QtWebEngine (the Trade Browser) drags in Qt Quick, and with it the
# whole QML plugin tree plus 3D, Charts, Multimedia… none of which the
# app uses. Dropping them saves ~150 MB. Keep Qml/QmlModels/QmlMeta/
# QmlWorkerScript/Quick/QuickWidgets/Positioning/WebChannel: WebEngine
# links against those.
import re

_UNUSED_QT = re.compile(
    r"Qt6?(3D\w*|Charts\w*|DataVisualization\w*|Graphs\w*|Labs\w*|"
    r"Location|Multimedia\w*|PdfQuick|Quick3D\w*|QuickControls2\w*|"
    r"QuickDialogs2\w*|QuickEffects|QuickLayouts|QuickParticles|"
    r"QuickShapes\w*|QuickTemplates2|QuickTest|QuickTimeline\w*|"
    r"QuickVectorImage\w*|RemoteObjects\w*|Scxml\w*|Sensors\w*|"
    r"SerialPort|ShaderTools|SpatialAudio|Sql|StateMachine\w*|Test|"
    r"TextToSpeech|VirtualKeyboard\w*|WaylandCompositor|WebEngineQuick\w*|"
    r"WebView\w*|WebSockets|WebChannelQuick|QmlCore|QmlDesignSupport|"
    r"QmlLocalStorage|QmlNetwork|QmlXmlListModel|PositioningQuick|"
    r"WlShellIntegration)(\.|d\.|$)",
    re.IGNORECASE)


def _keep(dest: str) -> bool:
    parts = Path(dest).parts
    if "PySide6" not in parts:
        return True
    rest = parts[parts.index("PySide6") + 1:]
    if "qml" in rest or "qmltooling" in rest:           # QML plugins
        return False
    # Plugins whose Qt library was dropped above (GPS over serial port,
    # Wayland shell): they could never load.
    if re.search(r"position_?nmea|wl-shell-plugin", parts[-1]):
        return False
    if "translations" in rest:
        # The app is English: keep only WebEngine's en-US pack.
        return rest[-1] == "en-US.pak"
    name = parts[-1]
    if name.lower().startswith("lib"):
        name = name[3:]
    return not _UNUSED_QT.match(name)


a.binaries = [b for b in a.binaries if _keep(b[0])]
a.datas = [d for d in a.datas if _keep(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TwiceCorrupted",
    console=False,                       # windowed app, no console box
    icon=str(ICON) if ICON.exists() else None,
    version=str(ROOT / "build" / "version_info.txt")
    if (ROOT / "build" / "version_info.txt").exists() else None,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TwiceCorrupted",
)
