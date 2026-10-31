import sys
import argparse
from auto_test.runtime import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--verify-hardware", action="store_true")
    parser.add_argument("--log-file")
    args, rest = parser.parse_known_args()
    configure_runtime(args.log_file)
    # 自检模式：python main.py --selftest（程序化验证 GUI 可用性，无需人工操作）
    if args.selftest:
        from gui_test import run_selftest
        return run_selftest()
    if args.verify_hardware:
        from verify_hardware import main as verify
        return verify(rest)

    from PyQt5.QtWidgets import QApplication
    from auto_test.gui.main_window import MainWindow
    app = QApplication([sys.argv[0]] + rest)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
