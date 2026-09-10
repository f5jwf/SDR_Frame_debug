import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,json
from pathlib import Path
from PySide6 import QtWidgets,QtGui
from sdr_debug import config
from sdr_debug.ui.main_window import MainWindow


def main():
    with tempfile.TemporaryDirectory() as folder:
        config.PROFILE=Path(folder)
        app=QtWidgets.QApplication([]);QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf');app.setFont(QtGui.QFont('Segoe UI',9))
        w=MainWindow();w.resize(1600,1050)
        for index in range(3):w.tabs.setCurrentIndex(index);w.backend.setCurrentText('Démonstration')
        w.tabs.setCurrentIndex(0);w.show();w.toggle();results={}
        for index,band in enumerate(config.BANDS):
            w.tabs.setCurrentIndex(index);deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
                if w.band==band and w.active and w.engine.counts['total']>0 and w.table.rowCount():break
            if w.band!=band or not w.table.rowCount():raise RuntimeError(f'{band}: {w.decode_label.text()}')
            w.table.selectRow(0);app.processEvents();w.grab().save(f'tools/preview_{band}_v020.png')
            results[band]={'counts':w.engine.counts,'status':w.decode_label.text(),'rows':w.table.rowCount()}
        w.engine.stop()
        deadline=time.monotonic()+15
        while any(t.is_alive() for t in w.engine.threads) and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        assert not any(t.is_alive() for t in w.engine.threads)
        w.close();app.processEvents();print(json.dumps(results,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
