"""Repeatable GUI/DSP benchmark with no hardware and isolated preferences."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import argparse,json,time,tempfile
from pathlib import Path
from PySide6 import QtWidgets,QtGui
from sdr_debug import config
from sdr_debug.ui.main_window import MainWindow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=15);parser.add_argument('--rate',type=float,default=4)
    parser.add_argument('--offset',type=float,default=1);parser.add_argument('--output');parser.add_argument('--screenshot');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sdr-benchmark-') as folder:
        config.PROFILE=Path(folder)
        app=QtWidgets.QApplication([]);QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf');app.setFont(QtGui.QFont('Segoe UI',9))
        w=MainWindow();w.resize(1500,900);w.backend.setCurrentText('Démonstration');w.channel.setCurrentIndex(w.channel.findData(15))
        w.center.setValue(2425+args.offset);w.rate.setCurrentText(f'{args.rate:g}');w.show();w.toggle()
        startup=time.monotonic()
        while not w.engine.ready.is_set():
            app.processEvents();time.sleep(.01)
            if time.monotonic()-startup>30:raise RuntimeError('DSP startup timeout')
        start=time.monotonic();durations=[];performance=[]

        while time.monotonic()-start<args.seconds:
            before=time.perf_counter();app.processEvents();durations.append(time.perf_counter()-before)
            if w.engine.performance:performance.append(w.engine.performance[-1])
            if getattr(w,'last_performance',None) is not None and (not performance or performance[-1]!=w.last_performance):performance.append(w.last_performance)
            time.sleep(.001)
        elapsed=time.monotonic()-start
        if args.screenshot:w.grab().save(args.screenshot)
        w.engine.stop()
        for t in w.engine.threads:t.join(5)
        result={'seconds':elapsed,'sample_rate_msps':args.rate,'channel_offset_mhz':args.offset,'counts':dict(w.engine.counts),'gui_max_ms':max(durations)*1000,
                'workers_stopped':not any(t.is_alive() for t in w.engine.threads),'queue_at_end':w.engine.blocks.qsize()}
        if performance:
            result['performance']=performance[-1]
            result['max_queue_blocks']=max(p['queue_blocks'] for p in performance)
        result['startup_seconds']=start-startup
        result['performance_samples']=performance
        print(json.dumps(result,indent=2))
        if args.output:Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf8')
        w.close();app.processEvents()


if __name__=='__main__':main()
