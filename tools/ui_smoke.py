import os
os.environ['QT_QPA_PLATFORM']='windows'
import time
from PySide6.QtWidgets import QApplication
from sdr_debug.ui.main_window import MainWindow
from sdr_debug.config import load,save
def main():
    original=load()
    app=QApplication([]); window=MainWindow(); window.resize(1500,900)
    window.backend.setCurrentText('Démonstration');window.center.setValue(2425);window.rate.setCurrentText('4');window.toggle()
    end=time.monotonic()+5
    while time.monotonic()<end:
        app.processEvents();time.sleep(.005)
    print('counts',window.engine.counts,'rows',window.table.rowCount())
    if window.table.rowCount():window.table.selectRow(0)
    app.processEvents();window.grab().save('tools/ui-preview.png')
    window.engine.stop()
    while any(t.is_alive() for t in window.engine.threads):app.processEvents();time.sleep(.01)
    window.close();save(original)


if __name__=="__main__":main()
