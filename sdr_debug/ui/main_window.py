from collections import deque
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import time
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets as W
from .. import config
from ..version import __version__
from ..dsp.engine import Engine
from ..export.packets import export_frames
from ..protocols.registry import available
from ..protocols.base import Frame
from ..protocols.ism.cerberus_pro501 import decode_pro501
from ..sdr.backends import discover
from ..sdr.rates import SAMPLE_RATES,usable_bandwidth


class TimestampItem(W.QTableWidgetItem):
    def __lt__(self, other):
        role=QtCore.Qt.ItemDataRole.UserRole
        return self.data(role).timestamp < other.data(role).timestamp


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(f'SDR Frame Debug v{__version__}'); self.resize(1500,960)
        self.band='zigbee';self.views={};self.switch_target=None;self.resume_after_switch=False
        self.last_plot=None
        self.settings=config.load(); self.newest_first=self.settings.newest_first; self.row_items={}; self.demod_row_items={}; self.engine=Engine(isolated=True); self.packets=deque(maxlen=2000); self.demodulated=deque(maxlen=2000);self.decoded_candidates=deque(maxlen=2000); self.pending=deque(maxlen=2000)
        self.plugins=available(); self.tasks=queue.Queue(); self.active=False; self.closing=False
        self.last_water_render=0.; self.water_palette=None; self.last_frequency_range=None
        self.water=None; self.water_index=0; self.water_count=0; self.water_key=None; self.last_total=0; self.last_stats=time.monotonic()
        self.build(); self.restore(); self.protocol_changed()
        self.search.setText(self.settings.search); self.bad.setChecked(self.settings.show_bad); self.favorite_only.setChecked(self.settings.favorites_only)
        idx=self.filter_field.findData(self.settings.filter_field); self.filter_field.setCurrentIndex(max(0,idx)); self.filter_value.setText(self.settings.filter_value)
        self.gain_timer=QtCore.QTimer(self); self.gain_timer.setSingleShot(True); self.gain_timer.setInterval(250)
        self.gain_timer.timeout.connect(self.send_gain)
        self.gain.valueChanged.connect(self.gain_changed); self.agc.toggled.connect(self.gain_changed)
        self.gain.setEnabled(not self.agc.isChecked())
        self.rate.currentIndexChanged.connect(self.rate_changed); self.backend.currentIndexChanged.connect(self.rate_changed)
        self.timer=QtCore.QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(50)
        self.statusBar().showMessage('Prêt · Pluto par défaut · Démonstration disponible sans matériel')

    def spin(self,lo,hi,step,value,decimals=3,suffix=''):
        widget=W.QDoubleSpinBox(); widget.setRange(lo,hi); widget.setDecimals(decimals)
        widget.setSingleStep(step); widget.setValue(value); widget.setSuffix(suffix); return widget

    def build(self):
        root=W.QWidget(); self.setCentralWidget(root); layout=W.QVBoxLayout(root)
        heading=W.QHBoxLayout(); title=W.QLabel(f'SDR FRAME DEBUG  v{__version__}'); title.setStyleSheet('font-size:22px;font-weight:700;color:#61d4ff')
        heading.addWidget(title); heading.addStretch(); heading.addWidget(W.QLabel('RÉCEPTION UNIQUEMENT  •  I/Q / FFT / ZIGBEE / ISM')); layout.addLayout(heading)
        self.tabs=W.QTabBar();self.tabs.setObjectName('band_tabs');self.tabs.setExpanding(False)
        for name in ('Zigbee 2,4 GHz','ISM 433 MHz','ISM 868 MHz'):self.tabs.addTab(name)
        self.tabs.currentChanged.connect(self.switch_band);layout.addWidget(self.tabs)
        controls=W.QGridLayout(); layout.addLayout(controls)
        self.backend=W.QComboBox(); self.backend.addItems(['PlutoSDR','Démonstration','Rejeu SigMF','RTL-SDR'])
        self.uri=W.QLineEdit(); self.uri.setPlaceholderText('ip:192.168.2.1 / URI IIO')
        self.scan=W.QPushButton('Détecter'); self.scan.clicked.connect(self.scan_devices)
        self.start_button=W.QPushButton('Démarrer'); self.start_button.clicked.connect(self.toggle)
        self.apply_button=W.QPushButton('Appliquer'); self.apply_button.clicked.connect(self.apply)
        self.protocol=W.QComboBox()
        for ident,cls in self.plugins.items():
            if ident=='zigbee':self.protocol.addItem(cls.name,ident)
        self.protocol.setEnabled(False)
        self.protocol.currentIndexChanged.connect(self.protocol_changed)
        for i,(label,widget) in enumerate([('Source',self.backend),('URI',self.uri),('Protocole',self.protocol)]):
            controls.addWidget(W.QLabel(label),0,i*2); controls.addWidget(widget,0,i*2+1)
        controls.addWidget(self.scan,0,6); controls.addWidget(self.start_button,0,7); controls.addWidget(self.apply_button,0,8)
        self.center=self.spin(.5,6000,.001,2425,6,' MHz'); self.center.setMinimumWidth(150)
        self.fc_slider=W.QSlider(QtCore.Qt.Orientation.Horizontal); self.fc_slider.setRange(2400,2485)
        self.fc_slider.valueChanged.connect(lambda value:self.center.setValue(value))
        self.center.valueChanged.connect(self.center_changed)
        self.span=self.spin(.1,61.44,.1,4,3,' MHz')
        self.span_slider=W.QSlider(QtCore.Qt.Orientation.Horizontal); self.span_slider.setRange(1,40)
        self.span_slider.valueChanged.connect(lambda v:self.span.setValue(v/10))
        self.span.valueChanged.connect(self.set_range)
        self.rate=W.QComboBox(); self.rate.addItems([f'{r/1e6:g}' for r in (4_000_000,8_000_000)+tuple(r for r in SAMPLE_RATES if r not in (4_000_000,8_000_000))]); self.rate.setToolTip('Pluto : jusqu’à 61,44 MS/s ; bande RF standard ≤ 20 MHz. Le débit USB peut limiter la réception continue. RTL : 2,4/2,56 MS/s.')
        self.gain=self.spin(-3,73,1,30,1,' dB'); self.gain.setToolTip('Pluto : réglage direct après 250 ms, sans Appliquer. RTL : Appliquer.'); self.agc=W.QCheckBox('AGC')
        self.offset=self.spin(-6000,6000,1,0,3,' MHz'); self.offset.setToolTip('RF affichée = fréquence du tuner + offset')
        for i,(label,widget) in enumerate([('Fc',self.center),('SPAN',self.span),('MS/s',self.rate),('Gain',self.gain)]):
            controls.addWidget(W.QLabel(label),1,i*2); controls.addWidget(widget,1,i*2+1)
        controls.addWidget(self.agc,1,8); controls.addWidget(self.fc_slider,2,0,1,2); controls.addWidget(self.span_slider,2,2,1,2)
        controls.addWidget(W.QLabel('Offset RF'),2,4); controls.addWidget(self.offset,2,5)
        self.channel=W.QComboBox(); self.channel.currentIndexChanged.connect(self.channel_changed)
        controls.addWidget(self.channel,2,6)
        self.recenter=W.QPushButton('Recentrer sur RX'); self.recenter.clicked.connect(self.recenter_rx); controls.addWidget(self.recenter,2,7,1,2)
        self.ism_controls=W.QWidget();ism=W.QGridLayout(self.ism_controls);ism.setContentsMargins(0,0,0,0)
        self.rx_frequency=self.spin(300,1000,.001,433.92,6,' MHz')
        self.rx_frequency.valueChanged.connect(self.channel_changed)
        self.channel_width=self.spin(10,800,10,200,0,' kHz');self.channel_width.valueChanged.connect(self.channel_changed)
        self.modulation=W.QComboBox()
        for label,value in [('Auto OOK/ASK + FSK','auto'),('OOK / ASK','ook'),('FSK','fsk')]:self.modulation.addItem(label,value)
        self.modulation.setToolTip('La détection reste automatique ; ce choix filtre la modulation des trames retournées.')
        self.decoder_ids=W.QLineEdit();self.decoder_ids.setPlaceholderText('Décodeurs rtl_433 : vide = automatiques')
        self.ism_presets=W.QComboBox();self.ism_presets.activated.connect(lambda i:self.rx_frequency.setValue(self.ism_presets.itemData(i)) if self.ism_presets.itemData(i) is not None else None)
        self.fsk_detector=W.QComboBox();self.fsk_detector.addItems(['classic','minmax','auto'])
        self.fsk_detector.setToolTip('Algorithme de détection FSK de rtl_433 ; classic est validé sur la démonstration LaCrosse.')
        self.ism_decoder=W.QComboBox();self.ism_decoder.addItem('Automatique (rtl_433 + CERBERUS)','auto');self.ism_decoder.addItem('CERBERUS PRO-501','pro501');self.ism_decoder.addItem('rtl_433 uniquement','rtl433')
        self.ism_decoder.setToolTip('Choisit le décodeur ISM. CERBERUS PRO-501 utilise le décodeur OOK/PWM adaptatif local.')
        self.decoder_path=W.QPushButton('Moteur rtl_433…');self.decoder_path.clicked.connect(self.choose_decoder)
        for i,(label,widget) in enumerate([('RX',self.rx_frequency),('Largeur',self.channel_width),('Modulation',self.modulation)]):
            ism.addWidget(W.QLabel(label),0,2*i);ism.addWidget(widget,0,2*i+1)
        self.ism_decoder_label=W.QLabel('Décodeur ISM')
        ism.addWidget(self.ism_presets,0,6);ism.addWidget(self.decoder_ids,1,0,1,4);ism.addWidget(W.QLabel('Détecteur FSK'),1,4);ism.addWidget(self.fsk_detector,1,5);ism.addWidget(self.ism_decoder_label,1,6);ism.addWidget(self.ism_decoder,1,7);ism.addWidget(self.decoder_path,1,8)
        layout.addWidget(self.ism_controls);self.ism_controls.hide()
        self.rx_label=W.QLabel(); layout.addWidget(self.rx_label)
        self.level_label=W.QLabel('Niveaux en dBFS, non calibrés en dBm · Gain matériel : —'); layout.addWidget(self.level_label)
        self.actual_gain_text='—'
        self.transfer_label=W.QLabel('Débit I/Q transféré : —'); layout.addWidget(self.transfer_label)
        self.dsp_label=W.QLabel('Traitement DSP : —'); layout.addWidget(self.dsp_label)
        split=W.QSplitter(); layout.addWidget(split,1)
        left=W.QWidget(); ll=W.QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); split.addWidget(left)
        pg.setConfigOptions(antialias=False,background='#101a28',foreground='#cbd5e1',imageAxisOrder='row-major')
        self.spectrum=pg.PlotWidget(); self.spectrum.setLabel('left','Niveau par bin','dBFS'); self.spectrum.setLabel('bottom','Fréquence','MHz')
        self.spectrum.showGrid(x=True,y=True,alpha=.15); self.spectrum.setYRange(-100,0); self.spectrum.setMouseEnabled(x=False,y=True)
        self.curve=self.spectrum.plot(pen=pg.mkPen('#5eead4',width=1)); ll.addWidget(self.spectrum,1)
        self.waterfall=pg.PlotWidget(); self.waterfall.setLabel('left','Âge','s'); self.waterfall.setLabel('bottom','Fréquence','MHz')
        self.waterfall.setXLink(self.spectrum); self.waterfall.setMouseEnabled(x=False,y=False); self.waterfall.invertY(True)
        self.image=pg.ImageItem(); self.waterfall.addItem(self.image); ll.addWidget(self.waterfall,1)
        for plot in (self.spectrum,self.waterfall): plot.getAxis('left').setWidth(65); plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.markers=[]; self.channel_regions=[]
        for plot in (self.spectrum,self.waterfall):
            region=pg.LinearRegionItem(values=(2424,2426),orientation='vertical',movable=False,
                                      brush=pg.mkBrush(251,191,36,32),pen=pg.mkPen(251,191,36,150))
            region.setZValue(1); region.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            plot.addItem(region); self.channel_regions.append(region)
            marker=pg.InfiniteLine(angle=90,movable=True,pen=pg.mkPen('#fbbf24',width=2),label='RX',labelOpts={'position':.9})
            marker.setZValue(3); plot.addItem(marker); marker.sigPositionChangeFinished.connect(self.marker_moved); self.markers.append(marker)
        self.channel_lines=[]
        self.decode_label=W.QLabel('Chaîne DSP à l’arrêt'); ll.addWidget(self.decode_label)
        right=W.QWidget(); rl=W.QVBoxLayout(right); rl.setContentsMargins(6,0,0,0); split.addWidget(right); split.setSizes([980,520])
        filters=W.QHBoxLayout(); self.search=W.QLineEdit(); self.search.setPlaceholderText('Recherche texte ou hexadécimal…'); self.search.textChanged.connect(self.refresh_table)
        self.bad=W.QCheckBox('CRC BAD'); self.bad.toggled.connect(self.refresh_table); filters.addWidget(self.search); filters.addWidget(self.bad); rl.addLayout(filters)
        typed=W.QHBoxLayout(); self.filter_field=W.QComboBox(); self.filter_field.setMinimumWidth(170); self.filter_value=W.QLineEdit(); self.filter_value.setPlaceholderText('Valeur exacte (ex. 0x0006)')
        self.filter_field.currentIndexChanged.connect(self.refresh_table); self.filter_value.textChanged.connect(self.refresh_table)
        typed.addWidget(self.filter_field); typed.addWidget(self.filter_value); rl.addLayout(typed)
        row=W.QHBoxLayout(); self.pause=W.QCheckBox('Pause affichage'); self.pause.toggled.connect(self.unpause)
        self.favorite_only=W.QCheckBox('Favoris'); self.favorite_only.toggled.connect(self.refresh_table)
        clear=W.QPushButton('Effacer'); clear.clicked.connect(self.clear_packets); row.addWidget(self.pause); row.addWidget(self.favorite_only); row.addWidget(clear); rl.addLayout(row)
        self.demod_label=W.QLabel('Données démodulées');rl.addWidget(self.demod_label)
        self.demod_table=W.QTableWidget(0,5);self.demod_table.setHorizontalHeaderLabels(['Date / heure','Durée','Octets','Hexa (début)','Type']);self.demod_table.verticalHeader().hide();self.demod_table.verticalHeader().setDefaultSectionSize(30)
        self.demod_table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows);self.demod_table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection);self.demod_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.demod_table.horizontalHeader().setSectionResizeMode(3,W.QHeaderView.ResizeMode.Interactive)
        for c,width in enumerate([190,65,55,300,180]):self.demod_table.setColumnWidth(c,width)
        self.demod_table.itemSelectionChanged.connect(self.show_demodulated);rl.addWidget(self.demod_table,2)
        self.decode_table_label=W.QLabel('Trames décodées');rl.addWidget(self.decode_table_label)
        self.table=W.QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['★','Date / heure','CH','dBFS','CRC','Résumé','Hexa brut']); self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(5,W.QHeaderView.ResizeMode.Stretch)
        for c,width in enumerate([28,103,38,50,45,0,230]): self.table.setColumnWidth(c,width)
        header=self.table.horizontalHeader(); header.setSectionsClickable(True); header.setSortIndicatorShown(True)
        header.setSortIndicator(1,QtCore.Qt.SortOrder.DescendingOrder if self.newest_first else QtCore.Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self.toggle_time_order)
        header.setToolTip('Cliquer Date / heure pour inverser ancien → récent / récent → ancien')
        self.table.itemSelectionChanged.connect(self.show_packet); self.table.cellDoubleClicked.connect(self.favorite)
        rl.addWidget(self.table,3)
        self.details=W.QTreeWidget(); self.details.setHeaderLabels(['Champ','Valeur']); self.details.setColumnWidth(0,175); rl.addWidget(self.details,2)
        self.raw=W.QPlainTextEdit(); self.raw.setReadOnly(True); self.raw.setLineWrapMode(W.QPlainTextEdit.LineWrapMode.NoWrap); self.raw.setMaximumHeight(135); self.raw.setFont(QtGui.QFont('Consolas',10)); rl.addWidget(self.raw)
        self.stats=W.QLabel('0 trame'); layout.addWidget(self.stats)
        tools=W.QHBoxLayout(); layout.addLayout(tools)
        replay=W.QPushButton('Ouvrir I/Q'); replay.clicked.connect(self.choose_replay)
        self.record=W.QPushButton('Enregistrer I/Q'); self.record.setCheckable(True); self.record.clicked.connect(self.record_iq)
        export=W.QPushButton('Exporter trames'); export.clicked.connect(self.export)
        export_hex=W.QPushButton('Sauver hex'); export_hex.setToolTip('Enregistre la rafale démodulée sélectionnée ; sans sélection, enregistre les trames décodées visibles.'); export_hex.clicked.connect(lambda:self.export(hexadecimal=True))
        session=W.QPushButton('Sauver session'); session.clicked.connect(lambda:self.export(session=True))
        prefs=W.QPushButton('FFT / Waterfall'); prefs.clicked.connect(self.preferences)
        keys=W.QPushButton('Clés Zigbee'); keys.clicked.connect(self.keys_dialog);self.keys_button=keys
        for button in (replay,self.record,export,export_hex,session,prefs,keys): tools.addWidget(button)
        tools.addStretch(); self.key_options={}
        self.setStyleSheet('QMainWindow,QWidget{background:#111b29;color:#dce5f2;} QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit,QTreeWidget,QTableWidget{background:#172438;selection-background-color:#28566b;} QPushButton{background:#243a50;border:1px solid #39536e;padding:7px;border-radius:4px;} QPushButton:hover{background:#31516c;} QPushButton:checked{background:#805820;} QHeaderView::section{background:#24364c;padding:4px;} QCheckBox::indicator{width:18px;height:18px;border:1px solid #8196ae;border-radius:3px;background:#172438;} QCheckBox::indicator:checked{background:#39bda4;border:2px solid #a1ffed;} QTabBar::tab{background:#1a2a3d;padding:9px 18px;border:1px solid #39536e;margin-right:3px;} QTabBar::tab:selected{background:#24536b;color:#ffffff;border-bottom:3px solid #61d4ff;} QTabBar::tab:hover{background:#31516c;} QToolTip{background:#24364c;color:white;}')

    def restore(self):
        s=self.settings; self.backend.setCurrentText(s.backend); self.uri.setText(s.uri); self.center.setValue(s.center/1e6)
        self.fc_slider.blockSignals(True); self.fc_slider.setValue(round(s.center/1e6)); self.fc_slider.blockSignals(False); self.span.setMaximum(usable_bandwidth(s)/1e6); self.span.setValue(s.span/1e6); self.span_slider.setMaximum(int(usable_bandwidth(s)/1e5))
        self.rate.setCurrentText(f'{s.sample_rate/1e6:g}'); self.gain.setValue(s.gain); self.agc.setChecked(s.agc); self.offset.setValue(s.offset/1e6)
        idx=self.protocol.findData(s.protocol)
        if idx>=0:self.protocol.setCurrentIndex(idx)

    def current(self):
        s=replace(self.settings); s.backend=self.backend.currentText(); s.uri=self.uri.text().strip(); s.center=self.center.value()*1e6
        s.sample_rate=int(float(self.rate.currentText())*1e6)
        if s.backend=='PlutoSDR': s.rf_bandwidth=min(s.sample_rate,20_000_000)
        s.gain=self.gain.value(); s.agc=self.agc.isChecked(); s.offset=self.offset.value()*1e6
        s.channel=self.channel.currentData(); s.protocol=self.protocol.currentData(); s.span=min(self.span.value()*1e6,usable_bandwidth(s))
        s.newest_first=self.newest_first; s.search=self.search.text(); s.filter_field=self.filter_field.currentData() or ''; s.filter_value=self.filter_value.text(); s.show_bad=self.bad.isChecked(); s.favorites_only=self.favorite_only.isChecked()
        s.workspace=self.band
        if self.band!='zigbee':
            s.rx_frequency=self.rx_frequency.value()*1e6;s.channel_width=self.channel_width.value()*1e3
            s.modulation=self.modulation.currentData();s.decoder_ids=self.decoder_ids.text().strip();s.fsk_detector=self.fsk_detector.currentText();s.ism_decoder=self.ism_decoder.currentData()
        return s

    def protocol_changed(self,*args):
        if not hasattr(self,'channel'):return
        cls=self.plugins[self.protocol.currentData()]; self.channel.blockSignals(True); self.channel.clear()
        for c,f in cls.channels.items(): self.channel.addItem(f'CH{c} · {f/1e6:g} MHz',c)
        index=self.channel.findData(self.settings.channel); self.channel.setCurrentIndex(max(0,index)); self.channel.blockSignals(False)
        self.filter_field.clear(); self.filter_field.addItem('Tous les champs','');
        for field in cls().get_filters(): self.filter_field.addItem(field,field)
        for plot,line in self.channel_lines: plot.removeItem(line)
        self.channel_lines=[]
        for freq in cls.channels.values():
            for plot in (self.spectrum,self.waterfall):
                line=pg.InfiniteLine(freq/1e6,pen=pg.mkPen('#34455b',style=QtCore.Qt.PenStyle.DotLine)); plot.addItem(line); self.channel_lines.append((plot,line))
        self.channel_changed()

    def center_changed(self,value):
        self.fc_slider.blockSignals(True); self.fc_slider.setValue(round(value)); self.fc_slider.blockSignals(False)
        if hasattr(self,'spectrum'):self.set_range()

    def set_range(self,*args):
        if not hasattr(self,'spectrum'):return
        center=self.settings.center/1e6 if self.active else self.center.value()
        span=min(self.span.value(),usable_bandwidth(self.settings)/1e6 if self.active else float(self.rate.currentText()))
        self.span_slider.blockSignals(True); self.span_slider.setValue(round(span*10)); self.span_slider.blockSignals(False)
        bounds=(center-span/2,center+span/2)
        if bounds!=self.last_frequency_range:
            self.spectrum.setXRange(*bounds,padding=0);self.last_frequency_range=bounds

    def channel_changed(self,*args):
        if self.channel.currentData() is None:return
        cls=self.plugins[self.protocol.currentData()]; freq=self.rx_frequency.value() if self.band!='zigbee' else cls.channels[self.channel.currentData()]/1e6
        if self.band!='zigbee':self.ism_presets.setCurrentIndex(max(0,self.ism_presets.findData(freq)))
        for marker in self.markers:marker.setValue(freq)
        width=self.channel_width.value()*1e3 if self.band!='zigbee' else cls.bandwidth
        half_width=width/2e6
        for region in self.channel_regions:region.setRegion((freq-half_width,freq+half_width))
        outside=abs(freq*1e6-self.settings.center)+width/2>usable_bandwidth(self.settings)/2
        hint='Canal hors bande : cliquer Recentrer sur RX' if outside else 'Appliquer pour modifier la réception'
        self.rx_label.setText(f'Canal RX : {freq:g} MHz · Largeur canal {width/1e6:g} MHz · Taux réel : {self.settings.sample_rate:,} éch/s · Bande RF {usable_bandwidth(self.settings)/1e6:g} MHz · {hint}')

    def marker_moved(self,marker):
        if self.band!='zigbee':
            self.rx_frequency.setValue(marker.value());self.channel_changed()
            if self.active:self.apply()
            return
        cls=self.plugins[self.protocol.currentData()]; c=min(cls.channels,key=lambda c:abs(cls.channels[c]/1e6-marker.value()))
        self.channel.setCurrentIndex(self.channel.findData(c)); self.channel_changed()
        if self.active:self.apply()

    def recenter_rx(self):
        cls=self.plugins[self.protocol.currentData()]; self.center.setValue(self.rx_frequency.value() if self.band!='zigbee' else cls.channels[self.channel.currentData()]/1e6)
        if self.active:self.apply()

    def toggle(self):
        if self.switch_target is not None:return
        if self.active:
            self.engine.stop(); self.start_button.setEnabled(False); self.start_button.setText('Arrêt…'); return
        if any(t.is_alive() for t in self.engine.threads):return
        self.engine=Engine(isolated=True); self.water=None; self.water_count=0; self.last_total=0
        self.settings=self.current(); self.engine.start(self.settings,self.decoder_options()); self.active=True
        self.start_button.setText('Arrêter'); self.backend.setEnabled(False); config.save(self.settings)

    def rate_changed(self,*args):
        rate=float(self.rate.currentText())
        maximum=min(rate,20.) if self.backend.currentText()=='PlutoSDR' else rate
        self.span.setMaximum(maximum); self.span_slider.setMaximum(round(maximum*10))
        if not self.active:self.set_range()
    def gain_changed(self,*args):
        self.gain.setEnabled(not self.agc.isChecked())
        if self.active and self.backend.currentText()=='PlutoSDR':
            self.gain_timer.start()
    def send_gain(self):
        if self.active and self.backend.currentText()=='PlutoSDR':
            self.engine.set_gain(self.gain.value(),self.agc.isChecked())
    def apply(self):
        if self.switch_target is not None:return
        self.gain_timer.stop()
        s=self.current(); self.span.setMaximum(usable_bandwidth(s)/1e6); self.span_slider.setMaximum(int(usable_bandwidth(s)/1e5))
        if self.active:self.engine.reconfigure(s,self.decoder_options())
        else:self.settings=s
        config.save(s); self.set_range()

    def scan_devices(self):
        self.scan.setEnabled(False)
        def job():
            try:self.tasks.put(('devices',discover()))
            except Exception as exc:self.tasks.put(('error',str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def choose_replay(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Capture I/Q SigMF',self.settings.capture_dir,'SigMF (*.sigmf-meta *.sigmf-data)')
        if path:
            self.settings.capture_dir=str(Path(path).parent); self.settings.replay=path
            if self.active:self.statusBar().showMessage('Arrêter la réception puis choisir Rejeu SigMF pour ouvrir ce fichier.')
            else:self.backend.setCurrentText('Rejeu SigMF')

    def record_iq(self,on):
        if not self.active:
            self.record.setChecked(False); self.statusBar().showMessage('Démarrer la réception avant la capture.'); return
        path=None
        if on:path,_=W.QFileDialog.getSaveFileName(self,'Nouvelle capture I/Q',self.settings.capture_dir,'SigMF (*.sigmf-meta)')
        if path:self.settings.capture_dir=str(Path(path).parent)
        self.record.setChecked(bool(path)); self.engine.recording(path or None)

    def matches(self,frame):
        if frame.crc_ok is False and not self.bad.isChecked():return False
        if self.favorite_only.isChecked() and not frame.favorite:return False
        query=self.search.text().strip().lower()
        if query and query not in (frame.summary+' '+json.dumps(frame.fields,ensure_ascii=False)).lower() and query.replace(' ','') not in frame.raw.hex():return False
        field=self.filter_field.currentData(); wanted=self.filter_value.text().strip().lower()
        if field and wanted:
            value=frame.channel if field=='channel' else frame.fields
            if field!='channel':
                for part in field.split('.'):value=value.get(part,'') if isinstance(value,dict) else ''
            if str(value).lower()!=wanted:return False
        return True

    def toggle_time_order(self,column):
        if column!=1:return
        self.newest_first=not self.newest_first
        order=QtCore.Qt.SortOrder.DescendingOrder if self.newest_first else QtCore.Qt.SortOrder.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(1,order)
        self.table.sortItems(1,order)
        config.save(self.current())

    def refresh_table(self,*args):
        if not hasattr(self,'table'):return
        item=self.table.item(self.table.currentRow(),0)
        selected=item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        self.table.blockSignals(True)
        self.row_items.clear(); self.table.setRowCount(0)
        for frame in self.packets:
            if self.matches(frame):self.add_row(frame)
        self.table.blockSignals(False)
        if selected is not None and id(selected) in self.row_items:
            self.table.selectRow(self.row_items[id(selected)].row())
        elif self.table.rowCount():
            # Keep the decoded details useful while live frames arrive: the
            # first visible frame is selected until the user chooses another.
            self.table.selectRow(0)
        self.show_packet()

    def add_row(self,frame):
        # Insert by full-resolution timestamp, including during replay or resume.
        lo,hi=0,self.table.rowCount()
        while lo<hi:
            mid=(lo+hi)//2
            stamp=self.table.item(mid,1).data(QtCore.Qt.ItemDataRole.UserRole).timestamp
            before=frame.timestamp>stamp if self.newest_first else frame.timestamp<stamp
            if before:hi=mid
            else:lo=mid+1
        row=lo; self.table.insertRow(row)
        values=['★' if frame.favorite else '',datetime.fromtimestamp(frame.timestamp).strftime('%Y-%m-%d\n%H:%M:%S.%f')[:-3],str(frame.channel),f'{frame.level:.1f}' if np.isfinite(frame.level) else '—','OK' if frame.crc_ok is True else ('BAD' if frame.crc_ok is False else frame.fields.get('PHY',{}).get('integrity','n/d')),frame.summary,frame.raw.hex().upper() if frame.raw else 'non fourni']
        for col,value in enumerate(values):
            item=(TimestampItem(value) if col==1 else W.QTableWidgetItem(value)); item.setData(QtCore.Qt.ItemDataRole.UserRole,frame)
            item.setToolTip(datetime.fromtimestamp(frame.timestamp).isoformat(timespec='milliseconds')+'\n'+frame.summary)
            if col==4:item.setForeground(QtGui.QColor('#5eead4' if frame.crc_ok else '#fb7185'))
            self.table.setItem(row,col,item)
            if col==0:self.row_items[id(frame)]=item

    def add_demodulated_row(self,frame):
        row=self.demod_table.rowCount();self.demod_table.insertRow(row)
        duration=frame.fields.get('Démodulation',{}).get('durée_ms',frame.fields.get('PHY',{}).get('duration_ms','—'))
        preview=frame.raw.hex().upper();preview=preview[:48]+('…' if len(preview)>48 else '') if preview else 'non fourni'
        values=[datetime.fromtimestamp(frame.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],f'{duration} ms',str(len(frame.raw)),preview,frame.summary]
        for col,value in enumerate(values):
            item=W.QTableWidgetItem(value);item.setData(QtCore.Qt.ItemDataRole.UserRole,frame);item.setToolTip(frame.raw.hex().upper() or 'Octets bruts non fournis')
            self.demod_table.setItem(row,col,item)
            if col==0:self.demod_row_items[id(frame)]=item

    def show_demodulated(self):
        row=self.demod_table.currentRow()
        if row<0:return
        item=self.demod_table.item(row,0)
        if item is None:return
        frame=item.data(QtCore.Qt.ItemDataRole.UserRole);self.details.clear()
        def branch(parent,key,value):
            node=W.QTreeWidgetItem(parent,[str(key),'' if isinstance(value,(dict,list)) else str(value)])
            if isinstance(value,dict):
                for k,v in value.items():branch(node,k,v)
            elif isinstance(value,list):
                for k,v in enumerate(value):branch(node,k,v)
        branch(self.details,'Données démodulées',{'timestamp':datetime.fromtimestamp(frame.timestamp).isoformat(timespec='milliseconds'),'durée_ms':frame.fields.get('Démodulation',{}).get('durée_ms'),'octets_reçus':len(frame.raw),'hexadécimal':frame.raw.hex().upper()})
        branch(self.details,'Décodage',{'statut':'non reconnu à ce stade','note':'Les octets représentent les pulses OOK : niveau logique + durée en microsecondes.'})
        self.details.expandAll()
        self.raw.setPlainText('\n'.join(f'{i:04x}  '+frame.raw[i:i+16].hex(' ').ljust(47)+'  '+''.join(chr(b) if 32<=b<127 else '.' for b in frame.raw[i:i+16]) for i in range(0,len(frame.raw),16)))
        self.decode_demodulated(frame)

    def decode_demodulated(self,frame):
        """Populate decoded results only for the selected OOK burst."""
        self.packets.clear();self.pending.clear();self.row_items.clear();self.table.setRowCount(0)
        duration=float(frame.fields.get('Démodulation',{}).get('durée_ms',0))/1000
        selected=self.ism_decoder.currentData() if self.band=='ism868' else 'rtl433'
        if selected in ('auto','pro501') and len(frame.raw)%3==0:
            edges=[(frame.raw[index],int.from_bytes(frame.raw[index+1:index+3],'big')) for index in range(0,len(frame.raw),3)]
            result=decode_pro501(edges)
            if result is not None and result.valid:
                details={'PHY':{'modulation':'OOK/ASK PWM','raw_bit_length':64,'integrity':'non renseignée'},
                         'cerberus_pro501':{'raw_bits':result.raw_bits,'repeats':result.repeats,'frame_confidence':result.frame_confidence,
                            'symbol_confidence':result.symbol_confidence,'frame_fingerprint':result.sensor_key,'sensor_id':'non déterminé','event':result.event,
                            'battery':result.battery,'timing_us':result.timing_us,'ratio_short':result.ratio_short,'ratio_long':result.ratio_long}}
                decoded=Frame(frame.timestamp,1,frame.frequency,result.raw_u64.to_bytes(8,'big'),None,float('nan'),details,
                              f'CERBERUS PRO-501 · {result.event} · empreinte trame {result.sensor_key} · {result.repeats} répétitions · confiance {result.frame_confidence:.0%}',protocol='cerberus-pro501')
                self.packets.append(decoded);self.add_row(decoded)
        # rtl_433 candidates are associated by their timestamp with the selected
        # raw burst.  They are retained until selection, never mixed with other bursts.
        for candidate in self.decoded_candidates:
            if candidate.protocol.startswith('ism') and frame.timestamp-.010 <= candidate.timestamp <= frame.timestamp+duration+.010:
                self.packets.append(candidate);self.add_row(candidate)

    def unpause(self,on):
        if not on:
            self.packets.extend(self.pending); self.pending.clear(); self.refresh_table()

    def clear_packets(self):
        self.packets.clear();self.demodulated.clear();self.decoded_candidates.clear(); self.pending.clear(); self.row_items.clear();self.demod_row_items.clear(); self.table.setRowCount(0);self.demod_table.setRowCount(0); self.details.clear(); self.raw.clear()

    def favorite(self,row,column):
        frame=self.table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole); frame.favorite=not frame.favorite; self.refresh_table()

    def show_packet(self):
        row=self.table.currentRow()
        if row<0:return
        item=self.table.item(row,0)
        if item is None:return
        frame=item.data(QtCore.Qt.ItemDataRole.UserRole); self.details.clear()
        def branch(parent,key,value):
            item=W.QTreeWidgetItem(parent,[str(key),'' if isinstance(value,(dict,list)) else str(value)])
            if isinstance(value,dict):
                for k,v in value.items():branch(item,k,v)
            elif isinstance(value,list):
                for k,v in enumerate(value):branch(item,k,v)
        branch(self.details,'Réception',{'date':datetime.fromtimestamp(frame.timestamp).isoformat(timespec='milliseconds'),'canal':frame.channel,'fréquence':frame.frequency,'dBFS':frame.level if np.isfinite(frame.level) else 'non fourni','octets bruts':len(frame.raw) if frame.raw else 'non fournis','hexadécimal':frame.raw.hex().upper() if frame.raw else 'non fourni'})
        for key,value in frame.fields.items():branch(self.details,key,value)
        self.details.expandAll()
        if frame.protocol!='zigbee' and not frame.raw:
            self.raw.setPlainText('Octets bruts non fournis par ce décodeur. Résultat reçu :\n'+json.dumps(frame.fields.get('rtl_433',{}),ensure_ascii=False,indent=2));return
        self.raw.setPlainText('\n'.join(f'{i:04x}  '+frame.raw[i:i+16].hex(' ').ljust(47)+'  '+''.join(chr(b) if 32<=b<127 else '.' for b in frame.raw[i:i+16]) for i in range(0,len(frame.raw),16)))

    def export(self,checked=False,session=False,hexadecimal=False):
        title='Sauver les trames visibles au format hexadécimal' if hexadecimal else ('Sauver session' if session else 'Exporter les trames visibles')
        filters='Fichier hexadécimal (*.hex)' if hexadecimal else ('JSON (*.json)' if session else 'JSON (*.json);;CSV (*.csv);;Wireshark PCAP (*.pcap)')
        path,_=W.QFileDialog.getSaveFileName(self,title,self.settings.capture_dir,filters)
        if not path:return
        if hexadecimal and not Path(path).suffix:path+='.hex'
        self.settings.capture_dir=str(Path(path).parent)
        if session:
            frames=list(self.packets)+list(self.pending)
        elif hexadecimal and self.band != 'zigbee' and self.demod_table.currentRow() >= 0:
            # The raw OOK burst is the object the user selected.  It must take
            # precedence over the short, derived decoder result in the table below.
            item=self.demod_table.item(self.demod_table.currentRow(),0)
            frames=[item.data(QtCore.Qt.ItemDataRole.UserRole)] if item is not None else []
        else:
            frames=[f for f in self.packets if self.matches(f)]
        metadata={'settings':self.settings.public(),'counters':dict(self.engine.counts)} if session else {}
        def job():
            try:export_frames(path,frames,metadata); self.tasks.put(('info',f'Export terminé : {path}'))
            except Exception as exc:self.tasks.put(('error',str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def keys_dialog(self):
        dialog=W.QDialog(self); dialog.setWindowTitle('Clés locales — mémoire uniquement'); form=W.QFormLayout(dialog)
        form.addRow(W.QLabel('Clés hexadécimales de 16 octets. Champs vides = désactivation.\nAucune clé n’est enregistrée dans les sessions ou les préférences.'))
        network=W.QLineEdit(); link=W.QLineEdit()
        for widget in (network,link):widget.setEchoMode(W.QLineEdit.EchoMode.Password)
        network.setText(self.key_options.get('network_key',b'').hex()); link.setText(self.key_options.get('link_key',b'').hex())
        form.addRow('Network Key',network); form.addRow('APS Link Key',link)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=W.QDialog.DialogCode.Accepted:return
        try:
            options={k:bytes.fromhex(v.text()) for k,v in [('network_key',network),('link_key',link)] if v.text().strip()}
            if any(len(v)!=16 for v in options.values()):raise ValueError()
        except ValueError:W.QMessageBox.warning(self,'Clé invalide','Chaque clé doit contenir exactement 32 caractères hexadécimaux.'); return
        self.key_options=options
        if self.active:self.apply()
        self.statusBar().showMessage('Clés mises à jour en mémoire.')

    def preferences(self):
        dialog=W.QDialog(self); dialog.setWindowTitle('Spectre et waterfall'); form=W.QFormLayout(dialog); s=replace(self.settings)
        fft=W.QComboBox(); fft.addItems(['1024','2048','4096','8192']); fft.setCurrentText(str(s.fft_size))
        mode=W.QComboBox(); mode.addItem('Crête sur toutes les FFT (rafales)','peak'); mode.addItem('Moyenne temporelle','mean'); mode.setCurrentIndex(max(0,mode.findData(s.spectrum_mode)))
        window=W.QComboBox(); window.addItems(['hann','blackman','boxcar']); window.setCurrentText(s.window)
        average=self.spin(.01,1,.05,s.average,2); interval=self.spin(20,100,10,s.waterfall_ms,0,' ms')
        history=self.spin(30,300,30,s.history,0,' s'); floor=self.spin(-150,0,5,s.floor,0,' dBFS'); ceiling=self.spin(-100,20,5,s.ceiling,0,' dBFS')
        palette=W.QComboBox(); palette.addItems(['viridis','inferno','plasma']); palette.setCurrentText(s.palette)
        dc=W.QCheckBox('Activer la suppression de la porteuse au centre (DC)'); dc.setObjectName('dc_suppression'); dc.setChecked(s.dc)
        dc.setMinimumHeight(32); dc.setToolTip('Retire la moyenne I/Q : atténue aussi un véritable signal situé exactement à Fc.')
        for name,widget in [('FFT',fft),('Détecteur',mode),('Fenêtre',window),('Poids nouvelle FFT',average),('Intervalle waterfall',interval),('Historique',history),('Plancher',floor),('Plafond',ceiling),('Palette',palette)]:form.addRow(name,widget)
        form.addRow(dc)
        form.addRow(W.QLabel('Historique limité à 64 Mio ; résolution fréquentielle adaptée si nécessaire.'))
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=W.QDialog.DialogCode.Accepted:return
        if floor.value()>=ceiling.value():W.QMessageBox.warning(self,'Dynamique','Le plancher doit être inférieur au plafond.'); return
        s=self.settings
        s.spectrum_mode=mode.currentData(); s.fft_size=int(fft.currentText()); s.window=window.currentText(); s.average=average.value(); s.waterfall_ms=int(interval.value()); s.history=int(history.value())
        s.floor=floor.value(); s.ceiling=ceiling.value(); s.palette=palette.currentText(); s.dc=dc.isChecked(); self.water=None; self.apply()

    def plot(self,item):
        self.last_plot=item
        axis,power,ts,rate,center=item; self.curve.setData(axis/1e6,power)
        s=self.settings; rows=int(s.history*1000/s.waterfall_ms); bins=min(len(power),max(64,64*1024*1024//(rows*4)))
        # Ring buffer: allocation bounded independently of session duration.
        key=(rows,bins,rate,center,s.floor,s.ceiling)
        if self.water is None or key!=self.water_key:
            self.water=np.zeros((rows,bins),np.uint8); self.water_key=key; self.water_index=0; self.water_count=0
            self.water_times=np.zeros(rows)
        line=np.interp(np.linspace(0,len(power)-1,bins),np.arange(len(power)),power)
        self.water[self.water_index]=np.clip((line-s.floor)*255/max(1e-6,s.ceiling-s.floor),0,255).astype(np.uint8); self.water_times[self.water_index]=ts
        self.water_index=(self.water_index+1)%rows; self.water_count=min(rows,self.water_count+1)
        now=time.monotonic()
        if now-self.last_water_render<.1:return
        self.last_water_render=now
        # Display at most 600 actual rows, retaining full bounded history.
        indices=(self.water_index-1-np.linspace(0,max(0,self.water_count-1),min(600,self.water_count)).astype(int))%rows
        self.image.setImage(self.water[indices],autoLevels=False,levels=None)
        if self.water_palette!=s.palette:
            self.image.setLookupTable(pg.colormap.get(s.palette).getLookupTable(nPts=256)); self.water_palette=s.palette
        duration=max(s.waterfall_ms/1000,ts-self.water_times[indices[-1]])
        self.image.setRect(QtCore.QRectF((center-rate/2)/1e6,0,rate/1e6,duration)); self.waterfall.setYRange(0,duration,padding=0)
        self.set_range()

    def poll(self):
        for q in (self.tasks,self.engine.events):
            while not q.empty():
                try:kind,value=q.get_nowait()
                except queue.Empty:break
                if kind=='settings':
                    self.settings=value; self.center.setValue(value.center/1e6); self.span.setMaximum(usable_bandwidth(value)/1e6); self.span_slider.setMaximum(int(usable_bandwidth(value)/1e5))
                    self.gain.blockSignals(True); self.gain.setValue(value.gain); self.gain.blockSignals(False)
                    self.rate.setCurrentText(f'{value.sample_rate/1e6:g}'); self.water=None; self.channel_changed(); self.set_range()
                elif kind=='gain':
                    self.actual_gain_text=f"{value['gain']:.1f} dB ({value['mode']})"
                    self.settings.gain=value['gain']; self.settings.agc=value['agc']
                elif kind=='recording':self.record.setChecked(value)
                elif kind=='decode_status':self.decode_label.setText(value)
                elif kind=='stopped':
                    self.active=False; self.start_button.setEnabled(True); self.start_button.setText('Démarrer'); self.backend.setEnabled(True)
                elif kind=='devices':
                    self.scan.setEnabled(True)
                    if value:
                        choices=[f'{b} · {uri} · {label}' for b,uri,label in value]
                        choice,ok=W.QInputDialog.getItem(self,'Périphériques détectés','Source',choices,0,False)
                        if ok:
                            b,uri,_=value[choices.index(choice)]; self.backend.setCurrentText(b); self.uri.setText(uri)
                    else:self.statusBar().showMessage('Aucun SDR détecté. Vérifier pilotes/libiio ; une URI Pluto peut être saisie directement.')
                elif kind=='error':self.statusBar().showMessage('Erreur : '+value); self.decode_label.setText('Erreur : '+value); self.scan.setEnabled(True)
                else:self.statusBar().showMessage(str(value))
        added=False; full=False
        for _ in range(100):
            try:frame=self.engine.frames.get_nowait()
            except queue.Empty:break
            if frame.protocol=='ism-demodulated':
                if len(self.demodulated)==self.demodulated.maxlen and self.demod_table.rowCount():
                    old=self.demod_row_items.pop(id(self.demodulated[0]),None)
                    if old is not None:self.demod_table.removeRow(old.row())
                self.demodulated.append(frame);self.add_demodulated_row(frame)
                continue
            if self.band!='zigbee':
                self.decoded_candidates.append(frame)
                continue
            if self.pause.isChecked():self.pending.append(frame)
            else:
                if len(self.packets)==self.packets.maxlen and self.table.rowCount():
                    old=self.row_items.pop(id(self.packets[0]),None)
                    if old is not None:self.table.removeRow(old.row())
                self.packets.append(frame); added=True
                if self.matches(frame):self.add_row(frame)
        if full:self.refresh_table()
        if added and self.table.currentRow()<0:
            if self.newest_first:self.table.scrollToTop()
            else:self.table.scrollToBottom()
        if self.engine.spectra:
            try:self.plot(self.engine.spectra.pop())
            except IndexError:pass
        if self.engine.throughput:
            actual,requested=self.engine.throughput.pop()
            warning=' · Cadence continue non tenue : risque de lacunes' if actual<requested*.85 else ''
            self.transfer_label.setText(f'Débit transféré {actual/1e6:.2f} MS/s / cadence SDR {requested/1e6:g} MS/s{warning}')
        if self.engine.performance:
            p=self.engine.performance.pop();self.last_performance=p
            load=100*p['dsp_ms_per_block']/max(.001,p['signal_ms_per_block'])
            warning=' · Traitement trop lent : réduire MS/s' if load>=100 else ''
            self.dsp_label.setText(f"DSP {p['dsp_ms_per_block']:.1f} ms / bloc de {p['signal_ms_per_block']:.1f} ms · Charge {load:.0f}% · File {p['queue_blocks']}/{p['queue_capacity']}{warning}")
        if self.engine.metrics:
            m=self.engine.metrics.pop()
            self.level_label.setText(f"I/Q total {m['rms_dbfs']:.1f} dBFS · Crête I/Q {m['peak_dbfs']:.1f} dBFS · Saturation {m['clip_percent']:.3f}% · Gain relu {self.actual_gain_text} · Pas de calibration dBm")
        now=time.monotonic()
        if now-self.last_stats>=1:
            c=self.engine.counts; fps=(c['total']-self.last_total)/(now-self.last_stats); self.last_total=c['total']; self.last_stats=now
            self.stats.setText(f"{fps:.1f} trames/s   ·   Total {c['total']}   ·   CRC OK {c['ok']} / BAD {c['bad']} / n.d. {c['total']-c['ok']-c['bad']}   ·   Blocs perdus (logiciel) {c['dropped_blocks']}   ·   Trames non affichées {c['dropped_frames']}   ·   Mémoire : {len(self.packets)}/2000 trames (+{len(self.pending)} en pause)")
        if self.switch_target is not None and not self.closing and not any(t.is_alive() for t in self.engine.threads):self.complete_switch()
        if self.closing and not any(t.is_alive() for t in self.engine.threads):self.close()

    def closeEvent(self,event):
        if any(t.is_alive() for t in self.engine.threads):
            self.closing=True; self.engine.stop(); event.ignore(); self.statusBar().showMessage('Fermeture des workers…'); return
        config.save(self.current()); self.key_options.clear()
        for state in self.views.values():state.get('key_options',{}).clear()
        event.accept()


    def decoder_options(self):
        if self.band=='zigbee':return dict(self.key_options)
        s=self.current()
        return {key:getattr(s,key) for key in ('rx_frequency','channel_width','modulation','rtl433_path','decoder_ids','fsk_detector','ism_decoder')}

    def choose_decoder(self):
        from ..protocols.ism.plugin import executable
        current=executable(self.settings.rtl433_path) or 'Non trouvé'
        path,_=W.QFileDialog.getOpenFileName(self,f'rtl_433 actuel : {current}',str(Path(current).parent) if current!='Non trouvé' else '', 'Exécutable (*.exe);;Tous (*)')
        if path:self.settings.rtl433_path=path;self.apply()

    def switch_band(self,index):
        target=config.BANDS[index]
        if target==self.band and self.switch_target is None:return
        self.switch_target=target
        self.gain_timer.stop()
        if self.active or any(t.is_alive() for t in self.engine.threads):
            self.resume_after_switch=self.resume_after_switch or self.active
            self.engine.stop();self.start_button.setEnabled(False);self.apply_button.setEnabled(False)
            self.statusBar().showMessage('Changement de bande : fin de la capture et libération du SDR…')
        else:self.complete_switch()

    def complete_switch(self):
        if self.switch_target is None:return
        self.settings=self.current();config.save(self.settings)
        attributes=('settings','packets','demodulated','decoded_candidates','pending','engine','key_options','newest_first','water','water_index',
                    'water_count','water_key','water_times','last_plot','last_total','last_stats','actual_gain_text')
        state={name:getattr(self,name) for name in attributes if hasattr(self,name)}
        state['paused']=self.pause.isChecked()
        self.views[self.band]=state
        self.band=self.switch_target;self.switch_target=None
        state=self.views.get(self.band)
        if state is None:
            settings=config.load(self.band)
            state={'settings':settings,'packets':deque(maxlen=2000),'demodulated':deque(maxlen=2000),'decoded_candidates':deque(maxlen=2000),'pending':deque(maxlen=2000),
                   'engine':Engine(isolated=True),'key_options':{},'newest_first':settings.newest_first,
                   'water':None,'water_index':0,'water_count':0,'water_key':None,'last_plot':None,
                   'last_total':0,'last_stats':time.monotonic(),'actual_gain_text':'—','paused':False}
        for name,value in state.items():
            if name!='paused':setattr(self,name,value)
        self.active=False;self.last_frequency_range=None;self.last_water_render=0.;self.row_items={};self.demod_row_items={}
        controls=(self.backend,self.center,self.rate,self.span,self.gain,self.agc,self.offset,self.protocol,
                  self.rx_frequency,self.channel_width,self.modulation,self.ism_decoder,self.pause,self.search,self.filter_field,self.filter_value,self.bad,self.favorite_only)
        blockers=[QtCore.QSignalBlocker(control) for control in controls]
        self.protocol.clear();cls=self.plugins[self.band];self.protocol.addItem(cls.name,self.band)
        self.rate.clear();rates=SAMPLE_RATES if self.band=='zigbee' else (1000000,2400000,4000000,8000000)
        self.rate.addItems([f'{rate/1e6:g}' for rate in rates])
        self.fc_slider.setRange(*( (2400,2485) if self.band=='zigbee' else ((430,440) if self.band=='ism433' else (863,870))))
        self.restore();s=self.settings
        self.rx_frequency.setRange(*( (430,440) if self.band=='ism433' else (863,870)))
        self.rx_frequency.setValue(s.rx_frequency/1e6);self.channel_width.setValue(s.channel_width/1e3)
        self.modulation.setCurrentIndex(max(0,self.modulation.findData(s.modulation)));self.decoder_ids.setText(s.decoder_ids);self.fsk_detector.setCurrentText(s.fsk_detector);self.ism_decoder.setCurrentIndex(max(0,self.ism_decoder.findData(s.ism_decoder)));self.ism_decoder.setVisible(self.band=='ism868');self.ism_decoder_label.setVisible(self.band=='ism868')
        self.ism_presets.clear();self.ism_presets.addItem('RX personnalisée',None)
        for frequency in ((433.42,433.92,434.42) if self.band=='ism433' else (868.1,868.3,868.95,869.525)):
            self.ism_presets.addItem(f'RX {frequency:g} MHz',frequency)
        self.pause.setChecked(state['paused']);self.search.setText(s.search);self.bad.setChecked(s.show_bad);self.favorite_only.setChecked(s.favorites_only)
        self.filter_value.setText(s.filter_value)
        del blockers
        self.protocol_changed()
        self.filter_field.setCurrentIndex(max(0,self.filter_field.findData(s.filter_field)))
        self.ism_controls.setVisible(self.band!='zigbee');self.keys_button.setVisible(self.band=='zigbee');self.channel.setVisible(self.band=='zigbee')
        self.table.horizontalHeader().setSortIndicator(1,QtCore.Qt.SortOrder.DescendingOrder if self.newest_first else QtCore.Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeaderItem(4).setText('CRC' if self.band=='zigbee' else 'Contrôle')
        self.table.setColumnWidth(4,45 if self.band=='zigbee' else 90)
        self.table.setRowCount(0);self.demod_table.setRowCount(0)
        for frame in self.demodulated:self.add_demodulated_row(frame)
        self.details.clear();self.raw.clear();self.refresh_table()
        self.image.clear();self.curve.clear();self.water_palette=None
        if self.last_plot is not None:
            axis,power,ts,rate,center=self.last_plot;self.curve.setData(axis/1e6,power)
            if self.water is not None and self.water_count:
                indices=(self.water_index-1-np.linspace(0,self.water_count-1,min(600,self.water_count)).astype(int))%len(self.water)
                self.image.setImage(self.water[indices],autoLevels=False,levels=None)
                self.image.setLookupTable(pg.colormap.get(s.palette).getLookupTable(nPts=256));self.water_palette=s.palette
                duration=max(.05,ts-self.water_times[indices[-1]])
                self.image.setRect(QtCore.QRectF((center-rate/2)/1e6,0,rate/1e6,duration))
                self.waterfall.setYRange(0,duration,padding=0)
        self.decode_label.setText('Chaîne DSP à l’arrêt');self.level_label.setText('Niveaux I/Q : —');self.transfer_label.setText('Débit I/Q transféré : —');self.dsp_label.setText('Traitement DSP : —')
        self.start_button.setEnabled(True);self.start_button.setText('Démarrer');self.apply_button.setEnabled(True);self.backend.setEnabled(True)
        self.set_range();self.gain.setEnabled(not self.agc.isChecked());self.last_stats=0
        resume=self.resume_after_switch;self.resume_after_switch=False
        if resume:self.toggle()
        self.statusBar().showMessage(f'{self.tabs.tabText(self.tabs.currentIndex())} · réglages restaurés')
