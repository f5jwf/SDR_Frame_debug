from dataclasses import replace
import pytest
from PySide6 import QtCore,QtWidgets,QtTest
from sdr_debug import config
from sdr_debug.ui.main_window import MainWindow


@pytest.fixture
def window(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow();w.timer.stop()
    yield w
    w.active=False;w.close();app.processEvents()


def test_dc_click_text_apply_and_persist_during_reception(window,monkeypatch):
    w=window;calls=[];w.active=True
    monkeypatch.setattr(w.engine,'reconfigure',lambda s,options:calls.append(s))
    def toggle_dialog():
        dialog=QtWidgets.QApplication.activeModalWidget()
        checkbox=dialog.findChild(QtWidgets.QCheckBox,'dc_suppression')
        # The label, not just a tiny unlabelled indicator, must toggle the control.
        QtTest.QTest.mouseClick(checkbox,QtCore.Qt.MouseButton.LeftButton,pos=QtCore.QPoint(70,checkbox.height()//2))
        w.settings=replace(w.settings)  # Simulate a backend readback while open.
        dialog.accept()
    QtCore.QTimer.singleShot(50,toggle_dialog);w.preferences()
    assert w.settings.dc and config.load().dc and calls[-1].dc
    QtCore.QTimer.singleShot(50,toggle_dialog);w.preferences()
    assert not w.settings.dc and not config.load().dc and not calls[-1].dc


def test_channel_rectangles_follow_channel_and_marker(window):
    w=window
    w.channel.setCurrentIndex(w.channel.findData(11))
    for region in w.channel_regions:assert region.getRegion()==pytest.approx((2404,2406))
    w.markers[0].setValue(2415.2);w.marker_moved(w.markers[0])
    for region in w.channel_regions:assert region.getRegion()==pytest.approx((2414,2416))
    for marker in w.markers:assert marker.value()==pytest.approx(2415)
    assert w.channel.currentData()==13
