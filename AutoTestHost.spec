# Single-file Windows GUI; reports and cache remain outside the extracted bundle.
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas, binaries, hiddenimports = [], [], ["gui_test", "verify_hardware"]
for package in ("pyvisa", "pyvisa_py", "libusb_package"):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += [module for module in imports if ".testsuite" not in module and ".tests" not in module]
hiddenimports += collect_submodules("auto_test", filter=lambda module: not module.startswith("auto_test.test_engine"))
datas += copy_metadata("pyvisa-py")

a = Analysis(["main.py"], pathex=[SPECPATH], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports,
             excludes=["scipy", "pandas", "tkinter", "PySide6", "PyQt6", "IPython"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="AutoTestHost",
          debug=False, strip=False, upx=False, console=False)
