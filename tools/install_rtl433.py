"""Install the pinned official Windows rtl_433 release into the local runtime."""
import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

URL='https://github.com/merbanan/rtl_433/releases/download/25.12/rtl_433-win-x64-25.12.zip'
SHA256='ed42651d2a2a94f6419f7675955bd65449d8247e27822c65c363595b715b7de6'


def main():
    target=Path(__file__).resolve().parents[1]/'runtime'/'rtl_433'
    data=urllib.request.urlopen(URL,timeout=60).read()
    if hashlib.sha256(data).hexdigest()!=SHA256:raise RuntimeError('Archive checksum mismatch')
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            resolved=(target/member.filename).resolve()
            if not resolved.is_relative_to(target.resolve()):raise ValueError('Unsafe archive path')
        archive.extractall(target)
    print(f'rtl_433 25.12 installed in {target}')


if __name__=='__main__':main()
