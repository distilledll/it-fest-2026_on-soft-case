import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import CancelledError
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

from .api import Jina, Qwen, ServiceUnavailable
from .config import Config
from .context import Window
from .documents import load_package
from .engine import Engine
from .prompts import PROMPT_VERSION
from .retrieval import Retriever
from .storage import RunStore, atomic, read_questions, run_lock


@contextmanager
def dataset(path):
    path = Path(path)
    if path.is_dir():
        yield path
        return
    with tempfile.TemporaryDirectory(prefix='trustqa-') as tmp:
        with zipfile.ZipFile(path) as archive:
            total = 0
            members = archive.infolist()
            if len(members) > 20000:
                raise ValueError('Archive contains too many entries')
            for member in members:
                target = (Path(tmp) / member.filename).resolve()
                total += member.file_size
                if not target.is_relative_to(Path(tmp).resolve()) or total > 512 * 1024 * 1024:
                    raise ValueError('Unsafe or oversized archive')
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Archive symlinks are not allowed')
                # Gold answers and other artifacts never enter the inference workspace.
                rel = Path(member.filename)
                if member.is_dir() or not (rel.name == 'questions.csv' or (rel.suffix == '.txt' and 'packages' in rel.parts)):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
        roots = sorted(Path(tmp).rglob('questions.csv'))
        if len(roots) != 1:
            raise ValueError('Archive must contain exactly one questions.csv')
        yield roots[0].parent


def make_engine(config):
    config.require_qwen()
    return Engine(config, Window(config), Retriever(config, Jina(config)), lambda: Qwen(config))


def run_batch(args, config, engine=None):
    started = time.monotonic()
    engine = engine or make_engine(config)
    with dataset(args.data) as root:
        questions = read_questions(root / 'questions.csv', args.exclude_package, args.only_package)
        if not questions:
            raise ValueError('No questions selected')
        packages = {name: load_package(root / 'packages', name, config.chunk_chars, config.overlap)
                    for name in sorted({q['package'] for q in questions})}
        manifest = dict(config=config.public(), prompt_version=PROMPT_VERSION, mode=args.mode,
                        disable=args.disable, questions=questions, tokenizer=engine.window.policy,
                        packages={name: p.fingerprint for name, p in packages.items()})
        with run_lock(args.output):
            store = RunStore(args.output, manifest, questions)
            resumed = len(store.completed)
            def solve(row):
                begin = time.monotonic()
                result, audit = engine.answer(packages[row['package']], row['question'], args.mode, args.disable)
                return dict(**row, result=result, audit=audit, seconds=time.monotonic() - begin)
            executor = ThreadPoolExecutor(max_workers=config.parallel)
            futures = {executor.submit(solve, q): q for q in questions if q['id'] not in store.completed}
            errors = []
            try:
                for future in as_completed(futures):
                    try:
                        record = future.result()
                        store.save(record)
                        print(f"{record['id']}: {record['result'].get('status', '')} ({record['audit']['calls']} Qwen calls)", file=sys.stderr)
                    except ServiceUnavailable as exc:
                        errors.append(dict(id=futures[future]['id'], reason=str(exc)))
                        for pending in futures:
                            pending.cancel()
                    except CancelledError:
                        pass
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
                elapsed = time.monotonic() - started
                summary = dict(completed=len(store.completed), total=len(questions), resumed=resumed,
                               session_seconds=elapsed, parallel=config.parallel, max_calls=config.max_calls,
                               qwen_calls=sum(r['audit']['calls'] for r in store.completed.values()),
                               cold_run=resumed == 0, model=config.qwen_model, version=config.qwen_model_version,
                               errors=errors, prompt_version=PROMPT_VERSION)
                atomic(Path(args.output).with_suffix('.run.json'), json.dumps(summary, ensure_ascii=False, indent=2))
            if errors:
                raise ServiceUnavailable(errors[0]['reason'] + '; run paused, rerun the same command to resume')
    return summary


def parser():
    p = argparse.ArgumentParser(description='ИИ, который не обманывает — procurement QA')
    sub = p.add_subparsers(dest='command', required=True)
    batch = sub.add_parser('run', help='Process a dataset directory or ZIP archive')
    batch.add_argument('--data', default='school21-onsoft-data')
    batch.add_argument('--output', default='results/D/answers.csv')
    batch.add_argument('--mode', choices=list('ABCD'), default='D')
    batch.add_argument('--disable', choices=['quotes', 'arithmetic', 'amendments'])
    batch.add_argument('--exclude-package')
    batch.add_argument('--only-package')
    ask = sub.add_parser('ask', help='Single question using the same pipeline')
    ask.add_argument('--packages', default='school21-onsoft-data/packages')
    ask.add_argument('--package', required=True)
    ask.add_argument('--question', required=True)
    ask.add_argument('--mode', choices=list('ABCD'), default='D')
    inspect = sub.add_parser('inspect', help='Validate ingestion without any API calls')
    inspect.add_argument('--data', default='school21-onsoft-data')
    inspect.add_argument('--exclude-package', default='P05')
    experiment = sub.add_parser('experiment', help='Frozen A–D evaluation and ablations')
    experiment.add_argument('--data', default='school21-onsoft-data')
    experiment.add_argument('--gold', required=True)
    experiment.add_argument('--checker', help='Optional reference copy; must match the installed official checker')
    experiment.add_argument('--output-dir', default='results/experiment')
    experiment.add_argument('--ablations', action='store_true')
    report = sub.add_parser('report', help='Rebuild HTML comparison from evaluated runs')
    report.add_argument('--directory', default='results/experiment')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.from_env()
        if args.command == 'run':
            if args.disable and args.mode != 'D':
                raise ValueError('--disable is only supported for mode D')
            print(json.dumps(run_batch(args, config), ensure_ascii=False, indent=2))
        elif args.command == 'ask':
            engine = make_engine(config)
            package = load_package(args.packages, args.package, config.chunk_chars, config.overlap)
            result, audit = engine.answer(package, args.question, args.mode)
            print(json.dumps(dict(result=result, audit=audit), ensure_ascii=False, indent=2))
        elif args.command == 'inspect':
            with dataset(args.data) as root:
                questions = read_questions(root / 'questions.csv', args.exclude_package)
                for name in sorted({q['package'] for q in questions}):
                    package = load_package(root / 'packages', name, config.chunk_chars, config.overlap)
                    print(json.dumps(dict(package=name, files=len(package.documents), chunks=len(package.chunks),
                                          issues=package.issues, amendments=len(package.amendments)), ensure_ascii=False))
        elif args.command == 'experiment':
            from .evaluation import experiment
            experiment(args, config)
        elif args.command == 'report':
            from .evaluation import report
            print(report(Path(args.directory)))
        return 0
    except (ValueError, OSError, ServiceUnavailable, zipfile.BadZipFile) as exc:
        print('trustqa: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted. Completed answers are saved; rerun the same command.', file=sys.stderr)
        return 130
