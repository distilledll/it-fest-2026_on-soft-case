import ast
from collections import Counter
from decimal import Decimal, InvalidOperation
import re
from .documents import norm

STATUSES = ("ответ", "расхождение", "нет в документах", "не знаю")
UNITS = {"rub", "percent", "calendar_day", "working_day", "month", "count", "datetime", "text", "boolean"}


class VerificationError(ValueError):
    pass


def numbers(text):
    return [Decimal(re.sub(r"[ \u00a0\u202f]", "", x).replace(",", "."))
            for x in re.findall(r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?", text)]


def answer_numbers(text):
    """Numbers that assert a value; clause and file references are not evidence claims."""
    text = re.sub(r'\b\d+_[^\s,;:()]+\.txt', ' ', text, flags=re.I)
    text = re.sub(r'(?:п\.|пункт[а-яё]*|файл[а-яё]*|№)\s*\d+(?:\.\d+)*', ' ', text, flags=re.I)
    return numbers(text)


STEM_STOP = frozenset('''
какой какая какое какие каков какова сколько нужна нужен нужно ли ответьте да или нет
в на по для от до из с со к у о об и не что кто чей чья чьи должен должна должны должно
быть был была было этом эта этот эти его ее их все всего лишь также можно только
участник участника участнику участники участников закупки закупка закупке закупок
размере размер рублей рублях процентах месяцах днях дня дней установлено установлен
требуется требование требования наличии наличие настоящей является если чем где когда
более менее него нее них свой своя свои имеет иметь может могут являются указан указана
указано соответствии согласно либо
'''.split())


def stems(text):
    """Short stems for content-word overlap; generic question words are removed."""
    return [word[:5] for word in re.findall(r'[а-яёa-z0-9]+', text.lower().replace('ё', 'е'))
            if len(word) > 2 and word not in STEM_STOP]


def content_anchors(question, package):
    """Rare question terms (document frequency 1-2) that an evidence quote must share.
    Data-driven: no hardcoded entities, so new questions about other licences/regulators work."""
    query = set(stems(question))
    frequency = Counter()
    for text in package.documents.values():
        frequency.update(set(stems(text)))
    return {term: frequency[term] for term in query if 0 < frequency[term] <= 2}


def anchor_issue(quote, unit, anchors):
    """Missing distinctive terms for boolean/text evidence; empty set means the quote fits."""
    if unit not in ('boolean', 'text') or not anchors:
        return set()
    words = set(stems(quote))
    rare = {term for term, frequency in anchors.items() if frequency == 1}
    if rare:
        return rare - words
    return set() if set(anchors) & words else set(anchors)


def number(value):
    try:
        result = Decimal(str(value).replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace(",", "."))
        if not result.is_finite():
            raise InvalidOperation()
        return result
    except InvalidOperation:
        raise VerificationError("Invalid decimal value") from None


def original_quote(text, quote):
    """Recover an exact original substring under the evaluator's normalization."""
    target = norm(quote)
    normalized, positions = [], []
    for index, char in enumerate(text):
        piece = norm(char) if not char.isspace() else " "
        if piece == " " and (not normalized or normalized[-1] == " "):
            continue
        normalized.extend(piece)
        positions.extend([index] * len(piece))
    haystack = "".join(normalized)
    at = haystack.find(target)
    if len(target) < 8 or at < 0:
        raise VerificationError("Quote absent or shorter than 8 normalized characters")
    return text[positions[at]:positions[at + len(target) - 1] + 1]


def source(package, file, quote, check_quotes=True, amendments=True):
    if file not in package.documents:
        raise VerificationError("Source file does not belong to this package")
    if not isinstance(quote, str) or len(norm(quote)) < 8:
        raise VerificationError("Missing quote")
    text = package.documents[file]
    exact = original_quote(text, quote) if check_quotes else quote
    if amendments:
        for amendment in package.amendments:
            if file == amendment['source'] and norm(exact) in norm(amendment['quote']) and norm(exact) not in norm(amendment['new']):
                raise VerificationError("Amendment evidence must quote the new wording only")
            if file == amendment['target']:
                old = text[amendment['start']:amendment['end']]
                active = text[:amendment['start']] + text[amendment['end']:]
                if norm(exact) in norm(old) and norm(exact) not in norm(active):
                    raise VerificationError("Evidence is from a superseded clause")
    return exact


def evidence(package, item, check_quotes=True, amendments=True):
    required = ('file', 'quote', 'subject', 'scope', 'value', 'unit', 'basis')
    if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in required):
        raise VerificationError("Invalid evidence schema")
    item = {k: item[k] for k in required}
    if not item['subject'] or not item['scope'] or not item['value'] or item['unit'] not in UNITS:
        raise VerificationError("Evidence lacks subject, scope, value or canonical unit")
    item['quote'] = source(package, item['file'], item['quote'], check_quotes, amendments)
    if item['unit'] in {"rub", "percent", "calendar_day", "working_day", "month", "count"}:
        if number(item['value']) not in numbers(item['quote']):
            raise VerificationError(f"Numeric value {item['value']} is not grounded in its own quote ({item['subject']})")
        patterns = {'rub': r'руб|₽', 'percent': r'%|процент', 'calendar_day': r'календарн|\bдень\b|\bдн(?:я|ей|и|ю|ем)\b',
                    'working_day': r'рабоч', 'month': r'месяц', 'count': r'.'}
        if not re.search(patterns[item['unit']], norm(item['quote'])):
            raise VerificationError("Unit is not grounded in quote")
        if item['unit'] == 'calendar_day' and re.search(r'рабоч', norm(item['quote'])):
            raise VerificationError("Working days require unit working_day")
    elif item['unit'] == 'datetime':
        if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', item['value']):
            raise VerificationError("Invalid datetime format")
        if not all(v in norm(item['quote']) for v in item['value'].split()):
            raise VerificationError("Date/time not grounded")
    elif item['unit'] == 'text' and norm(item['value']) not in norm(item['quote']):
        absent = re.search(r'не установлен|не требуется|отсутств|не предусмотрен', norm(item['quote']))
        if not (absent and norm(item['value']) in ('не требуется', 'не установлен', 'нет')):
            raise VerificationError("Text value is not grounded")
    elif item['unit'] == 'boolean':
        value = norm(item['value'])
        positive = {'да', 'требуется', 'установлено', 'есть', 'обязательно', 'необходимо'}
        negative = {'нет', 'не требуется', 'не установлено', 'отсутствует', 'не нужно'}
        if value in positive:
            item['value'] = 'да'
        elif value in negative:
            item['value'] = 'нет'
        else:
            raise VerificationError("Boolean must be да or нет")
    return item


CONFLICT_GENERIC = {'лицен', 'налич', 'треб', 'устан'}


def conflict_shared_subject(items):
    """A real conflict is about the same condition; generic words alone do not make it one."""
    if len(items) < 2:
        return True
    sets = [set(stems(item.get('quote', ''))) - CONFLICT_GENERIC for item in items]
    return bool(set.intersection(*sets))


def conflict_groups(items):
    groups = {}
    for item in items:
        key = tuple(norm(item[k]) for k in ('subject', 'scope', 'unit', 'basis'))
        value = str(number(item['value']).normalize()) if item['unit'] in {"rub", "percent", "calendar_day", "working_day", "month", "count"} else norm(item['value'])
        groups.setdefault(key, {}).setdefault(value, []).append(item)
    return [group for group in groups.values() if len(group) > 1]


def calculate(package, calculation, check_quotes=True, amendments=True):
    if not isinstance(calculation, dict) or calculation.get('unit') not in UNITS:
        raise VerificationError("Invalid calculation schema")
    operands = calculation.get('operands', [])
    if not operands or len(operands) > 12:
        raise VerificationError("Missing calculation operands")
    values = {}
    for item in operands:
        name = item.get('name', '')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name) or name in values:
            raise VerificationError("Invalid/duplicate operand name")
        evidence(package, dict(item, subject=name, scope='calculation', basis=''), check_quotes, amendments)
        values[name] = number(item['value'])
    try:
        tree = ast.parse(calculation['expression'], mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 80:
            raise VerificationError("Calculation too complex")
        used = set()
        def run(node):
            if isinstance(node, ast.Name) and node.id in values:
                used.add(node.id)
                return values[node.id]
            if isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value in (1, 100):
                return Decimal(str(node.value))
            if isinstance(node, ast.BinOp):
                a, b = run(node.left), run(node.right)
                if isinstance(node.op, ast.Add): return a + b
                if isinstance(node.op, ast.Sub): return a - b
                if isinstance(node.op, ast.Mult): return a * b
                if isinstance(node.op, ast.Div): return a / b
            raise VerificationError("Unsafe or unsupported calculation")
        result = run(tree.body)
        if used != set(values) or not result.is_finite():
            raise VerificationError("Unused operand or invalid result")
        # Procurement percentage calculation: enforce dimensions and approved expression.
        units = {item['name']: item['unit'] for item in operands}
        if calculation['unit'] == 'rub' and set(units.values()) == {'rub', 'percent'} and len(operands) == 2:
            rub = next(k for k, v in units.items() if v == 'rub')
            pct = next(k for k, v in units.items() if v == 'percent')
            if result != values[rub] * values[pct] / 100:
                raise VerificationError("Percentage arithmetic/dimensions mismatch")
        return result
    except (SyntaxError, TypeError, KeyError, ArithmeticError, RecursionError):
        raise VerificationError("Invalid calculation") from None


def verify(package, result, question, full_scan, check_quotes=True, arithmetic=True, amendments=True):
    if result.get('status') not in STATUSES:
        raise VerificationError("Invalid status")
    result = dict(result)
    for key in ('answer', 'quote', 'file'):
        if not isinstance(result.get(key), str):
            raise VerificationError("Missing output field")
    if result['status'] in ('нет в документах', 'не знаю'):
        if result['status'] == 'нет в документах' and (not full_scan or package.incomplete):
            raise VerificationError("Absence requires complete readable package scan")
        if result.get('evidence') and result['status'] == 'нет в документах':
            raise VerificationError("Absence contradicts supplied evidence")
        result.update(answer='', quote='', file='')
        return result
    items = [evidence(package, x, check_quotes, amendments) for x in result.get('evidence', [])]
    if not items:
        raise VerificationError("No structured evidence")
    anchors = content_anchors(question, package)
    if anchors:
        for item in items:
            missing = anchor_issue(item['quote'], item['unit'], anchors)
            if missing:
                raise VerificationError("Evidence quote does not mention " + ", ".join(sorted(missing)))
    result['evidence'] = items
    result['quote'] = source(package, result['file'], result['quote'], check_quotes, amendments)
    if not any(x['file'] == result['file'] and norm(x['quote']) == norm(result['quote']) for x in items):
        raise VerificationError("CSV source must be one of the evidence sources")
    conflicts = conflict_groups(items)
    if result['status'] == 'расхождение':
        if not conflicts:
            raise VerificationError("Conflict requires two applicable sources with same subject, unit and basis")
        for group in conflicts:
            all_sources = [s for values in group.values() for s in values]
            if not conflict_shared_subject(all_sources):
                raise VerificationError("Conflict quotes refer to different subjects")
            for sources in group.values():
                if not any(norm(s['value']) in norm(result['answer']) or
                           (s['unit'] in {'rub', 'percent', 'calendar_day', 'working_day', 'month', 'count'} and number(s['value']) in numbers(result['answer'])) for s in sources):
                    raise VerificationError("Conflict answer must contain every value")
    elif conflicts:
        raise VerificationError("Unresolved conflict")
    calc = result.get('calculation')
    calculation_question = bool(re.search(r'сколько рублей.*обеспечен|рассчита|вычисл', question.lower()))
    if arithmetic and calculation_question and not calc and result['answer'] != 'не требуется':
        raise VerificationError("Calculation question requires grounded operands")
    if arithmetic and calc:
        value = calculate(package, calc, check_quotes, amendments)
        result['answer'] = format(value.quantize(Decimal('.01')), 'f') + (' руб.' if calc['unit'] == 'rub' else ' ' + calc['unit'])
    elif not calc:
        for value in answer_numbers(result['answer']):
            if not any(value in numbers(item['value']) for item in items):
                raise VerificationError("Answer number has no evidence")
    if re.search(r'да или нет', question.lower()) and result['status'] == 'ответ' and result['answer'] not in ('да', 'нет'):
        raise VerificationError("Yes/no answer must be exactly да or нет")
    if result['status'] == 'ответ' and not calc and result['answer'] != 'не требуется':
        if re.search(r'в рублях', question.lower()) and not any(x['unit'] == 'rub' for x in items):
            raise VerificationError('Question requests rubles but evidence has another unit')
        if re.search(r'в процентах', question.lower()) and not any(x['unit'] == 'percent' for x in items):
            raise VerificationError('Question requests percent but evidence has another unit')
        if re.search(r'да или нет', question.lower()) and not any(x['unit'] == 'boolean' and x['value'] == result['answer'] for x in items):
            raise VerificationError('Yes/no answer disagrees with structured evidence')
    return result
