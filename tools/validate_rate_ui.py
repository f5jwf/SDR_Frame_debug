from PySide6.QtWidgets import QApplication
from sdr_debug.ui.main_window import MainWindow
from sdr_debug.config import load,save
original=load();app=QApplication([]);w=MainWindow()
w.backend.setCurrentText('PlutoSDR');w.rate.setCurrentText('61.44');w.span.setValue(20)
assert w.current().sample_rate==61440000
assert w.current().span==20000000
assert w.current().rf_bandwidth==20000000
assert w.span.maximum()==20
w.rate.setCurrentText('12');assert w.span.maximum()==12
w.close();save(original)
print('High-rate UI: selection, RF bandwidth and SPAN validated')
