from collections import deque
from PySide6 import QtWidgets
from sdr_debug import config
from sdr_debug.version import __version__
from sdr_debug.ui.main_window import MainWindow
from sdr_debug.protocols.base import Frame


def test_three_tabs_restore_controls_frames_and_persist(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow();w.timer.stop()
    assert __version__ in w.windowTitle() and w.tabs.count()==3
    w.gain.setValue(44);w.channel.setCurrentIndex(w.channel.findData(11));w.settings.fft_size=4096
    w.key_options={'network_key':bytes(range(16))}
    frame=Frame(100,11,2405e6,b'abc',True,-40)
    w.packets.append(frame);w.refresh_table();w.search.setText('abc')
    w.tabs.setCurrentIndex(1)
    assert w.band=='ism433' and w.rate.currentText()=='1' and len(w.packets)==0
    assert not w.key_options
    w.gain.setValue(22);w.rx_frequency.setValue(434.12);w.channel_width.setValue(150)
    for region in w.channel_regions:assert abs(region.getRegion()[0]-434.045)<1e-6
    w.modulation.setCurrentIndex(w.modulation.findData('ook'))
    w.tabs.setCurrentIndex(2);w.gain.setValue(33);w.rx_frequency.setValue(868.95)
    w.tabs.setCurrentIndex(0)
    assert w.gain.value()==44 and w.channel.currentData()==11 and w.settings.fft_size==4096
    assert w.packets[0] is frame and w.search.text()=='abc' and w.key_options['network_key']==bytes(range(16))
    w.tabs.setCurrentIndex(1)
    assert w.gain.value()==22 and w.rx_frequency.value()==434.12 and w.channel_width.value()==150
    assert w.modulation.currentData()=='ook'
    w.close();app.processEvents()
    again=MainWindow();again.timer.stop();again.tabs.setCurrentIndex(2)
    assert again.gain.value()==33 and again.rx_frequency.value()==868.95
    again.close();app.processEvents()
    assert 'network_key' not in ''.join(p.read_text(encoding='utf8') for p in tmp_path.glob('*.json'))


def test_switch_waits_for_previous_receiver_before_restarting(tmp_path,monkeypatch):
    from sdr_debug.ui import main_window as module
    from sdr_debug.dsp.engine import Engine
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow();w.timer.stop();started=[]
    class Worker:
        alive=True
        def is_alive(self):return self.alive
    worker=Worker();w.engine.threads=[worker];w.active=True
    def factory(**kwargs):
        engine=Engine();engine.start=lambda settings,options:started.append((settings.workspace,options))
        return engine
    monkeypatch.setattr(module,'Engine',factory)
    w.tabs.setCurrentIndex(1);w.tabs.setCurrentIndex(2)
    assert not started and w.band=='zigbee' and w.engine.stop_event.is_set()
    worker.alive=False;w.engine.events.put(('stopped',None));w.poll()
    assert [item[0] for item in started]==['ism868'] and w.band=='ism868'
    assert 'network_key' not in started[0][1]
    w.active=False;w.close();app.processEvents()


def test_selected_ism_frame_shows_all_structured_fields(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow();w.timer.stop();w.tabs.setCurrentIndex(2)
    frame=Frame(100,1,868300000,b'\0'*8,None,float('nan'),
                {'PHY':{'modulation':'OOK/ASK PWM'},'cerberus_pro501':{'event':'ALARM','sensor_key':'abc'}},
                'CERBERUS PRO-501',protocol='cerberus-pro501')
    w.packets.append(frame);w.refresh_table()
    assert w.table.currentRow()==0
    assert [w.details.topLevelItem(i).text(0) for i in range(w.details.topLevelItemCount())]==['Réception','PHY','cerberus_pro501']
    assert w.details.topLevelItem(2).child(0).text(0)=='event'
    w.close();app.processEvents()
