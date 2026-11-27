"""Install the two workshop skills from their public GitHub release."""

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


LIMIT = 4 * 1024 * 1024
JOURNAL = '.tv-workshop-rollback.zip'
PREFIX = 'TV-Workshop/.opencode/skills/'
DOCS = {'TV-Workshop/' + name for name in ('AGENTS.md', 'README.md', 'Начать практику.md')}


def download(repository, tag):
    url = f'{repository}/releases/download/{tag}/tv-workshop.zip'
    with urlopen(url, timeout=10) as response:
        location = urlsplit(response.geturl())
        if location.scheme != 'https' or location.hostname not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('unexpected asset host')
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('oversized asset')
    return data


def ordinary(path):
    st = path.lstat()
    return not (stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def validate_tree(root, files):
    if not all(ordinary(p) and p.is_dir() for p in (root.parent, root)):
        raise ValueError('unexpected skills directory')
    for name in files:
        path = root/name
        for parent in path.relative_to(root).parents:
            directory = root/parent
            if not ordinary(directory) or not directory.is_dir():
                raise ValueError('unexpected directory')
        if not ordinary(path) or not path.is_file() or not 0 < path.stat().st_size <= LIMIT:
            raise ValueError(name)


def release_files(data, tag, files):
    with ZipFile(BytesIO(data)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        names = {item.filename for item in entries}
        wanted = {PREFIX + name for name in files}
        if len(names) != len(entries) or not wanted <= names <= wanted | DOCS or sum(i.file_size for i in entries) > LIMIT:
            raise ValueError('unexpected archive contents')
        if any(stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG) or i.flag_bits & 1 for i in entries):
            raise ValueError('unsupported entry')
        contents = {name:archive.read(PREFIX + name) for name in files}
    if not all(contents.values()) or contents['tv-workshop/VERSION'].decode().strip() != tag:
        raise ValueError('unexpected archive version')
    return contents


@contextmanager
def locked(root):
    path = root.parent/'.tv-workshop.lock'
    if os.path.lexists(path) and (not ordinary(path) or not path.is_file()):
        raise ValueError('invalid lock')
    with path.open('ab') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def recover(root, files):
    journal = root.parent/JOURNAL
    if not os.path.lexists(journal):
        return
    if not ordinary(journal) or not journal.is_file() or journal.stat().st_size > LIMIT * 2:
        raise ValueError('invalid rollback archive')
    with ZipFile(journal) as archive, TemporaryDirectory(dir=root.parent) as temporary:
        names = archive.namelist()
        if not names or len(set(names)) != len(names) or not set(names) <= set(files) or sum(i.file_size for i in archive.infolist()) > LIMIT:
            raise BadZipFile('invalid rollback contents')
        validate_tree(root, names)
        if archive.testzip() is not None:
            raise BadZipFile('invalid rollback CRC')
        for name in names:
            staged = Path(temporary)/'restore'
            staged.write_bytes(archive.read(name))
            staged.chmod((archive.getinfo(name).external_attr >> 16) & 0o777)
            os.replace(staged, root/name)
    journal.unlink()


def install(root, tag, files, repository):
    contents = release_files(download(repository, tag), tag, files)
    changed = [name for name in contents if contents[name] != (root/name).read_bytes()]
    # Commit VERSION last so an interrupted copy never advertises a completed release.
    changed.sort(key=lambda name: name == 'tv-workshop/VERSION')
    if not changed:
        return
    journal = root.parent/JOURNAL
    with TemporaryDirectory(dir=root.parent) as temporary:
        stage = Path(temporary)
        with ZipFile(stage/'rollback.zip', 'w') as backup:
            for name in changed:
                dest = stage/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(contents[name])
                shutil.copymode(root/name, dest)
                backup.write(root/name, name)
        (stage/'rollback.zip').chmod(0o600)
        os.replace(stage/'rollback.zip', journal)
        for name in changed:
            os.replace(stage/name, root/name)
        journal.unlink()
