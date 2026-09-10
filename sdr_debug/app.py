import argparse
import sys
from PySide6.QtWidgets import QApplication
from .config import setup_logs
from .ui.main_window import MainWindow


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(); parser.add_argument('--demo',action='store_true'); args=parser.parse_args()
    setup_logs(); app=QApplication(sys.argv); app.setStyle('Fusion')
    window=MainWindow(); window.show()
    if args.demo:
        window.backend.setCurrentText('Démonstration'); window.channel.setCurrentIndex(window.channel.findData(15)); window.center.setValue(2425); window.rate.setCurrentText('4'); window.toggle()
    sys.exit(app.exec())
