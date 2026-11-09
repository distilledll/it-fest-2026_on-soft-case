"""Gold data is accessible exclusively from this explicitly invoked evaluation module."""
import argparse
from collections import Counter
from dataclasses import replace
import html
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from app.config import settings
from .cli import dataset, run_batch
from .prompts import PROMPT_VERSION
from .storage import atomic


def metrics(rows):
    counts = Counter(r['verdict'] for r in rows)
    n = len(rows)
    return dict(n=n, correct=counts['верно'], careful=counts['осторожно'], lies=counts['обман'],
                index=round(100 * (counts['верно'] - counts['обман']) / n, 2) if n else None)


def evaluate(answers, gold_path, packages, checker_path):
    # Execute the unmodified official checker as required; capture its complete stdout.
    installed = settings.checker.resolve()
    if checker_path and Path(checker_path).resolve() != installed:
        if Path(checker_path).read_bytes() != installed.read_bytes():
            raise ValueError('Use the installed official checker')
    checker_path = installed
    proc = subprocess.run([sys.executable, "-I", str(checker_path), str(answers), '--gold', str(Path(gold_path).resolve()),
                           '--packages', str(packages), '--out', str(answers.with_name('verdicts.csv'))],
                          capture_output=True, text=True, check=True)
    atomic(answers.with_name('check.txt'), proc.stdout)
    module_spec = importlib.util.spec_from_file_location('official_check', checker_path)
    checker = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(checker)
    gold = json.loads(Path(gold_path).read_text(encoding='utf-8'))
    answers_map = checker.load_answers(answers)
    rows, cache = [], {}
    for g in gold:
        name = g['package']
        if name not in cache:
            directory = Path(packages) / name
            cache[name] = {f.name: checker.norm(checker.read_file(f)) for f in directory.glob('*.txt')}
        verdict, why = checker.judge(g, answers_map.get(g['id']), cache[name])
        rows.append(dict(id=g['id'], package=name, type=g['type'], verdict=verdict, why=why))
    audits = {r['id']: r for r in (json.loads(line) for line in answers.with_suffix('.audit.jsonl').read_text(encoding='utf-8').splitlines())}
    by_type = {kind: metrics([r for r in rows if r['type'] == kind]) for kind in sorted({r['type'] for r in rows})}
    primary = [r for r in rows if audits.get(r['id'], {}).get('audit', {}).get('search') in ('none', 'jina+reranker')]
    fallback = [r for r in rows if r not in primary]
    result = dict(overall=metrics(rows), p05=metrics([r for r in rows if r['package'] == 'P05']),
                  by_type=by_type, primary=metrics(primary), fallback=metrics(fallback), rows=rows,
                  truncated=sum(bool(a['audit']['truncated']) for a in audits.values()),
                  run=json.loads(answers.with_suffix('.run.json').read_text(encoding='utf-8')))
    atomic(answers.with_name('evaluation.json'), json.dumps(result, ensure_ascii=False, indent=2))
    return result


def experiment(args, config):
    config.require_qwen()
    if not config.qwen_tokenizer:
        raise ValueError('Experiment A requires QWEN_TOKENIZER with the deployed Qwen chat template')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    freeze = dict(prompt_version=PROMPT_VERSION, config=config.public(), holdout='P05',
                  policy='P05 excluded from prompt development; evaluate only after freeze')
    freeze_path = output / 'freeze.json'
    if freeze_path.exists() and json.loads(freeze_path.read_text(encoding='utf-8')) != freeze:
        raise ValueError('Frozen experiment settings changed; choose a new output directory')
    atomic(freeze_path, json.dumps(freeze, ensure_ascii=False, indent=2))
    configurations = [(m, m, None) for m in 'ABCD']
    if args.ablations:
        configurations += [('D_no_' + feature, 'D', feature) for feature in ('quotes', 'arithmetic', 'amendments')]
    with dataset(args.data) as root:
        for name, mode, disable in configurations:
            directory = output / name
            csv_path = directory / 'answers.csv'
            batch = argparse.Namespace(data=str(root), mode=mode, output=str(csv_path), disable=disable,
                                       exclude_package=None, only_package=None)
            # A separate cache permits measuring each mode with its own initial indexing cost.
            run_batch(batch, replace(config, cache_dir=str(directory / 'cache')))
            evaluate(csv_path, args.gold, root / 'packages', args.checker)
    print(report(output))


def report(directory):
    directory = Path(directory)
    evaluated = {f.parent.name: json.loads(f.read_text(encoding='utf-8')) for f in sorted(directory.glob('*/evaluation.json'))}
    if not evaluated:
        raise ValueError('No evaluated runs. Run experiment with configured APIs first.')
    audits = {name: {r['id']: r for r in (json.loads(line) for line in (directory / name / 'answers.audit.jsonl').read_text(encoding='utf-8').splitlines())} for name in evaluated}
    esc = lambda value: html.escape(str(value))
    def table(headers, rows):
        return '<table><thead><tr>' + ''.join('<th>' + esc(h) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + esc(c) + '</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'
    parts = ['<!doctype html><html lang="ru"><meta charset="utf-8"><title>ИИ, который не обманывает</title>',
             '<style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#163047;background:#f5f7fa}table{border-collapse:collapse;width:100%;margin:20px 0;background:white}td,th{padding:10px;border:1px solid #d7e0e8;text-align:left}h1,h2{color:#102b42}pre{white-space:pre-wrap}svg{background:white;width:100%}</style>',
             '<h1>ИИ, который не обманывает</h1><p>Индекс доверия = 100 × (верно − обман) / число вопросов. Осторожный ответ даёт 0 баллов. Выдуманный ответ снижает индекс.</p>',
             '<p>Статусы: «ответ» — есть действующее значение и источник; «расхождение» — действуют два противоречащих пункта; «нет в документах» — весь пакет просмотрен, данных нет; «не знаю» — подтверждения недостаточно.</p>']
    bars = []
    for i, (name, data) in enumerate(evaluated.items()):
        m = data['overall']
        x = 460 + (m['index'] or 0) * 3
        bars.append(f'<text x="20" y="{40+i*48}">{esc(name)}</text><rect x="{min(460,x)}" y="{20+i*48}" width="{max(abs(x-460),1)}" height="28" fill="{"#12805c" if x>=460 else "#ce4a45"}"/><text x="790" y="{40+i*48}">{m["index"]}</text>')
    height = 60 + len(bars) * 48
    parts.append(f'<svg role="img" aria-label="Индекс доверия по режимам от минус 100 до 100" viewBox="0 0 900 {height}"><path d="M460 0V{height}" stroke="#b1bfcb"/>' + ''.join(bars) + '</svg>')
    verdict_bars = []
    for i, (name, data) in enumerate(evaluated.items()):
        m, x = data['overall'], 170
        verdict_bars.append(f'<text x="20" y="{40+i*48}">{esc(name)}</text>')
        for key, color in [('correct', '#12805c'), ('careful', '#d49a20'), ('lies', '#ce4a45')]:
            width = 520 * m[key] / max(m['n'], 1)
            verdict_bars.append(f'<rect x="{x}" y="{20+i*48}" width="{width}" height="28" fill="{color}"/>')
            x += width
        verdict_bars.append(f'<text x="710" y="{40+i*48}">{m["correct"]} / {m["careful"]} / {m["lies"]}</text>')
    parts.append('<p>Зелёный — верно, жёлтый — осторожно, красный — обман. Справа — число ответов каждого вида.</p>')
    parts.append(f'<svg role="img" aria-label="Количество верных, осторожных и ошибочных ответов" viewBox="0 0 900 {height}">' + ''.join(verdict_bars) + '</svg>')
    headers = ['Режим', 'Вопросов', 'Индекс', 'Верно', 'Осторожно', 'Обман', 'P05 индекс', 'Усечено', 'Qwen вызовов', 'Секунды с индексацией']
    parts.append(table(headers, [[name, *[d['overall'][k] for k in ('n', 'index', 'correct', 'careful', 'lies')], d['p05']['index'], d['truncated'], d['run']['qwen_calls'], round(d['run']['session_seconds'], 2)] for name, d in evaluated.items()]))
    for a, b in [('A', 'B'), ('B', 'C'), ('C', 'D'), ('A', 'D')]:
        if a in evaluated and b in evaluated:
            delta = evaluated[b]['overall']['index'] - evaluated[a]['overall']['index']
            parts.append(f'<p>{b} − {a}: {delta:+.2f} пункта индекса.</p>')
    if 'A' in evaluated and 'B' in evaluated:
        ids = {key for key, value in audits['A'].items() if not value['audit']['truncated']}
        ma = metrics([r for r in evaluated['A']['rows'] if r['id'] in ids])
        mb = metrics([r for r in evaluated['B']['rows'] if r['id'] in ids])
        delta = mb['index'] - ma['index'] if ma['n'] and mb['n'] else None
        parts.append(f'<p>B − A без усечения: {esc(delta)} пункта; вопросов: {ma["n"]}.</p>')
    parts.append('<h2>Типы вопросов и резервные режимы</h2>')
    parts.append(table(['Режим', 'Тип', 'Индекс', 'Верно', 'Осторожно', 'Обман'],
                       [[name, kind, *[m[k] for k in ('index', 'correct', 'careful', 'lies')]] for name, d in evaluated.items() for kind, m in d['by_type'].items()]))
    parts.append(table(['Режим', 'Поиск', 'Вопросов', 'Индекс'], [[name, kind, d[kind]['n'], d[kind]['index']] for name, d in evaluated.items() for kind in ('primary', 'fallback')]))
    parts.append('<h2>Диагностика ошибок бейзлайна</h2>')
    if 'A' in evaluated:
        errors = [r for r in evaluated['A']['rows'] if r['verdict'] == 'обман'][:10]
        parts.append(table(['ID', 'Вопрос', 'Ответ A', 'Причина оценщика', 'Ответ D'], [[r['id'], audits['A'].get(r['id'], {}).get('question', ''), audits['A'].get(r['id'], {}).get('result', {}).get('answer', ''), r['why'], audits.get('D', {}).get(r['id'], {}).get('result', {}).get('answer', '')] for r in errors]))
        if not errors:
            parts.append('<p>Оценщик не обнаружил ошибок в A.</p>')
    parts.append('<h2>Сработавшие проверки</h2>')
    catches = [(key, event['reason'], row['result']['status']) for key, row in audits.get('D', {}).items() for event in row['audit']['events'] if event.get('kind') in ('repair', 'abstention')][:3]
    parts.append(table(['ID', 'Причина проверки', 'Итоговый статус'], catches) if catches else '<p>В этом прогоне срабатываний не зафиксировано; примеры не сгенерированы искусственно.</p>')
    parts.append('<h2>Отключение проверок</h2>')
    if 'D' in evaluated:
        parts.append(table(['Отключено', 'Изменение индекса', 'Изменение числа ошибок'], [[name.removeprefix('D_no_'), round(d['overall']['index'] - evaluated['D']['overall']['index'], 2), d['overall']['lies'] - evaluated['D']['overall']['lies']] for name, d in evaluated.items() if name.startswith('D_no_')]))
    parts.append('<h2>Воспроизводимость и время</h2><p>Для серверного SLA используйте полный холодный прогон на целевом сервере. Оценка для 100 вопросов — линейная экстраполяция, её нужно подтвердить измерением. Возобновлённые сессии не являются полным замером.</p>')
    for name, d in evaluated.items():
        run = d['run']
        estimate = round(run['session_seconds'] * 100 / max(d['overall']['n'], 1), 2) if run['cold_run'] else 'не вычислялось: возобновление'
        parts.append(f'<p>{esc(name)}: модель {esc(run["model"])}, версия {esc(run["version"])}, параллелизм {run["parallel"]}, лимит {run["max_calls"]} вызовов/вопрос; оценка 100 вопросов: {esc(estimate)} с.</p>')
    parts.append('</html>')
    path = directory / 'report.html'
    atomic(path, '\n'.join(parts))
    return path
