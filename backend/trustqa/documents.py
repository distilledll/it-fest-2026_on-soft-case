from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re


def norm(s):
    s = (s or "").lower().replace("ё", "е").replace("\u00a0", " ").replace("\u202f", " ")
    s = re.sub('[«»„“”"\']', '"', s)
    s = re.sub("[–—−]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class Chunk:
    file: str
    start: int
    end: int
    text: str
    clause: str = ""

    def data(self):
        return dict(file=self.file, start=self.start, end=self.end, clause=self.clause, text=self.text)


@dataclass
class Package:
    name: str
    documents: dict[str, str] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    amendments: list[dict] = field(default_factory=list)

    def add_text(self, filename, text, size, overlap):
        if "\x00" in text:
            raise ValueError("binary data")
        self.documents[filename] = text
        if not text.strip():
            self.issues.append(dict(file=filename, reason="empty file"))
        self.chunks.extend(chunk_text(filename, text, size, overlap))

    @property
    def incomplete(self):
        return not self.documents or bool(self.issues)

    @property
    def fingerprint(self):
        return sha256(repr((sorted(self.documents.items()), self.issues)).encode()).hexdigest()


def chunk_text(file, text, size=1800, overlap=240):
    if not 0 <= overlap < size:
        raise ValueError("Overlap must be smaller than chunk size")
    starts = sorted(set([0, len(text)] + [m.start() for m in re.finditer(r"(?m)^\s*\d+(?:\.\d+)*\.\s", text)]))
    chunks = []
    for a, b in zip(starts, starts[1:]):
        clause = re.match(r"\s*(\d+(?:\.\d+)*)\.", text[a:b])
        for start in range(a, b, size - overlap):
            end = min(start + size, b)
            if text[start:end].strip():
                chunks.append(Chunk(file, start, end, text[start:end], clause[1] if clause else ""))
            if end == b:
                break
    return chunks


def parse_amendments(package):
    # Only an explicit file reference plus an exact old-clause prefix authorizes replacement.
    pattern = re.compile(r'Пункт\s+«(?P<old>.*?)»\s*\((?P<file>[^()]+\.txt)\)\s*изложить в следующей редакции:\s*«(?P<new>.*?)»', re.S | re.I)
    for source, text in package.documents.items():
        if len(list(re.finditer(r'изложить в следующей редакции', text, re.I))) != len(list(pattern.finditer(text))):
            package.issues.append(dict(file=source, reason='unsupported amendment syntax'))
        for m in pattern.finditer(text):
            target = m['file'].strip()
            prefix = norm(m['old'].rstrip(".… "))
            candidates = {(c.start, c.end, c.clause) for c in package.chunks
                          if c.file == target and prefix and prefix in norm(c.text)}
            if len(candidates) != 1:
                package.issues.append(dict(file=source, reason="ambiguous amendment target"))
                continue
            start, end, clause = candidates.pop()
            if any(a['target'] == target and a['start'] == start for a in package.amendments):
                package.issues.append(dict(file=source, reason='ambiguous amendment target'))
            package.amendments.append(dict(source=source, target=target, start=start, end=end,
                                           clause=clause, old=m['old'], new=m['new'], quote=m[0]))


def load_package(root, name, size=1800, overlap=240):
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Package must be a single directory name")
    directory = Path(root).resolve() / name
    package = Package(name)
    if directory.is_symlink():
        raise ValueError("Symlink package directories are not allowed")
    if not directory.is_dir():
        package.issues.append(dict(file=name, reason="missing package"))
        return package
    for file in sorted(directory.glob("*.txt")):
        try:
            if file.is_symlink():
                raise ValueError("symlink document")
            raw = file.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1251")
            package.add_text(file.name, text, size, overlap)
        except (OSError, UnicodeError, ValueError) as exc:
            package.issues.append(dict(file=file.name, reason=type(exc).__name__))
    parse_amendments(package)
    return package
