import csv
import hashlib
import io
import json
import os
from pathlib import Path
from contextlib import contextmanager

FIELDS = ['id', 'status', 'answer', 'quote', 'file']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8', newline='') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def read_questions(path, exclude=None, only=None):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        if reader.fieldnames != ['id', 'package', 'question']:
            raise ValueError('Expected questions header id;package;question')
        rows = list(reader)
    ids = set()
    for row in rows:
        if None in row or any(not row.get(k) for k in ('id', 'package', 'question')) or row['id'] in ids:
            raise ValueError('Invalid/duplicate input question ID')
        ids.add(row['id'])
    return [r for r in rows if r['package'] != exclude and (not only or r['package'] == only)]


@contextmanager
def run_lock(output):
    # Advisory OS lock is released on crashes; concurrent writers cannot corrupt a run.
    import fcntl
    lock = Path(output).parent / (Path(output).name + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another process is writing this output') from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class RunStore:
    def __init__(self, output, manifest, questions):
        self.output, self.questions = Path(output), questions
        self.directory = self.output.parent / (self.output.stem + '.state')
        self.directory.mkdir(parents=True, exist_ok=True)
        config_path = self.directory / 'manifest.json'
        if config_path.exists():
            previous = json.loads(config_path.read_text(encoding='utf-8'))
            if previous['signature'] != digest(manifest):
                raise ValueError('Resume inputs/settings changed; choose a new output path')
        else:
            if self.output.exists():
                raise ValueError('Output exists without checkpoint manifest; choose a new output path')
            atomic(config_path, json.dumps(dict(signature=digest(manifest), manifest=manifest), ensure_ascii=False, indent=2))
        self.completed = {}
        for row in questions:
            path = self.directory / (digest(row['id']) + '.json')
            if path.exists():
                record = json.loads(path.read_text(encoding='utf-8'))
                if record['id'] != row['id']:
                    raise ValueError('Corrupt checkpoint')
                self.completed[row['id']] = record
        self.export()

    def save(self, record):
        atomic(self.directory / (digest(record['id']) + '.json'), json.dumps(record, ensure_ascii=False, indent=2))
        self.completed[record['id']] = record
        self.export()

    def export(self):
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        ordered = [self.completed[q['id']] for q in self.questions if q['id'] in self.completed]
        for row in ordered:
            writer.writerow(dict(id=row['id'], **{k: row['result'].get(k, '') for k in FIELDS if k != 'id'}))
        atomic(self.output, buffer.getvalue())
        atomic(self.output.with_suffix('.audit.jsonl'), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered))
