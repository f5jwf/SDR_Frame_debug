from collections import deque
import pytest
from PySide6 import QtCore,QtWidgets,QtTest
from sdr_debug import config
from sdr_debug.ui.main_window import MainWindow
from sdr_debug.protocols.base import Frame


@pytest.fixture
def window(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow();w.timer.stop()
    yield w
    w.close();app.processEvents()


def packet(stamp):return Frame(stamp,11,2405e6,b'abc',True,-40,{},f'stamp={stamp}')
def timestamps(w):return [w.table.item(i,0).data(QtCore.Qt.ItemDataRole.UserRole).timestamp for i in range(w.table.rowCount())]
def arrival(w,stamp):w.engine.frames.put(packet(stamp));w.poll()


def click_date(w):
    header=w.table.horizontalHeader()
    x=header.sectionViewportPosition(1)+header.sectionSize(1)//2
    QtTest.QTest.mouseClick(header.viewport(),QtCore.Qt.MouseButton.LeftButton,pos=QtCore.QPoint(x,header.height()//2))


def test_header_click_and_new_packets(window):
    w=window
    for stamp in [3.0002,1,3.0001]:arrival(w,stamp)
    assert timestamps(w)==[1,3.0001,3.0002]
    w.table.selectRow(1);selected=w.table.item(1,0).data(QtCore.Qt.ItemDataRole.UserRole)
    click_date(w)
    assert timestamps(w)==[3.0002,3.0001,1]
    assert w.table.item(w.table.currentRow(),0).data(QtCore.Qt.ItemDataRole.UserRole) is selected
    arrival(w,4);assert timestamps(w)==[4,3.0002,3.0001,1]
    click_date(w);assert timestamps(w)==[1,3.0001,3.0002,4]


def test_pause_filters_and_preference(window):
    w=window;arrival(w,1);click_date(w)
    w.pause.setChecked(True);arrival(w,3);arrival(w,2)
    assert timestamps(w)==[1]
    w.pause.setChecked(False);assert timestamps(w)==[3,2,1]
    w.search.setText('stamp=2');assert timestamps(w)==[2]
    w.search.clear();assert timestamps(w)==[3,2,1]
    assert config.load().newest_first is True


def test_eviction_tracks_arrival_not_sort_order(window):
    w=window;w.packets=deque(maxlen=3);click_date(w)
    for stamp in [100,1,50,60]:arrival(w,stamp)
    assert timestamps(w)==[60,50,1]
    assert len(w.row_items)==3
    w.clear_packets();assert not w.row_items and not timestamps(w)
