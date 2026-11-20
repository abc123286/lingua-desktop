# PyInstaller build recipe:  pyinstaller lingua.spec
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in ("ctranslate2", "faster_whisper", "onnxruntime", "av", "tokenizers", "soundcard",
            "edge_tts", "certifi", "miniaudio", "deep_translator"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print("collect_all skipped", pkg, e)
hiddenimports += collect_submodules("pynput") + collect_submodules("lingua")

a = Analysis(
    ["run_lingua.py"],
    pathex=["."],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "pytest", "IPython", "pandas", "scipy"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LINGUA", console=False,
          icon="assets/lingua.ico" if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="LINGUA")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LINGUA.app",
        icon="assets/lingua.icns",
        bundle_identifier="com.lingua.desktop",
        info_plist={
            "CFBundleName": "LINGUA",
            "CFBundleDisplayName": "LINGUA",
            "CFBundleShortVersionString": "1.1.0",
            "NSMicrophoneUsageDescription": "LINGUA listens to your microphone and meeting audio to translate speech.",
            "NSHighResolutionCapable": True,
        },
    )
