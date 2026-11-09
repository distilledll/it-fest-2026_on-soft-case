from .api import CallLimit, InvalidResponse
from .documents import chunk_text, norm
from .prompts import SCAN, SYNTHESIS, messages
from .validation import (VerificationError, anchor_issue, content_anchors,
                         evidence, verify)


def same_witness(item, candidate):
    """The same source clause may be quoted with different surrounding text."""
    if item.get('file') != candidate.get('file'):
        return False
    left, right = norm(item.get('quote', '')), norm(candidate.get('quote', ''))
    return left == right or left in right or right in left


def unknown(reason):
    return dict(status='не знаю', answer='', quote='', file='', evidence=[], reason=reason)


class Engine:
    def __init__(self, config, window, retriever, qwen_factory):
        self.config, self.window = config, window
        self.retriever, self.qwen_factory = retriever, qwen_factory

    def active_chunks(self, package, amendments=True):
        if not amendments:
            return package.chunks
        result = []
        for file, original in package.documents.items():
            text = original
            for a in sorted(package.amendments, key=lambda a: a['start'], reverse=True):
                if file == a['target']:
                    text = text[:a['start']] + ' ' * (a['end'] - a['start']) + text[a['end']:]
            for a in package.amendments:
                if file == a['source']:
                    # Preserve unrelated provisions in the amendment document too.
                    text = text.replace(a['quote'], a['new'])
            result.extend(chunk_text(file, text, self.config.chunk_chars, self.config.overlap))
        return result

    def answer(self, package, question, mode='D', disable=None):
        client = self.qwen_factory()
        audit = dict(mode=mode, calls=0, usage=[], search='none', events=[], truncated=False,
                     issues=package.issues, amendments=package.amendments, full_scan=False,
                     tokenizer=self.window.policy, disable=disable, evidence=[])
        repaired = False
        files = sorted(package.documents)

        def call(items):
            if not self.window.fits(items):
                raise VerificationError('Mandatory context exceeds Qwen window')
            return client.complete(items)

        def correct(items, bad, reason):
            nonlocal repaired
            if repaired:
                raise VerificationError('Repeated verification failure: ' + reason)
            repaired = True
            audit['events'].append(dict(kind='repair', reason=reason))
            note = ('Единственная попытка исправления. Причина: ' + reason +
                    '. Верни исправленный JSON по исходной схеме.')
            # Upstream rejects a system message that is not first: amend the existing one.
            if items and items[0].get('role') == 'system':
                items = [dict(items[0], content=items[0]['content'] + '\n' + note)] + items[1:]
            else:
                items = [dict(role='system', content=note)] + items
            return call(items + [dict(role='assistant', content=__import__('json').dumps(bad, ensure_ascii=False)),
                                 dict(role='user', content='Исправь ответ с учётом причины.')])

        try:
            if mode in ('C', 'D') and any(i['reason'] in ('ambiguous amendment target', 'unsupported amendment syntax') for i in package.issues):
                raise VerificationError('Cannot determine applicability of an amendment')
            if mode == 'A':
                initial, audit['truncated'] = self.window.baseline(question, package)
            else:
                selected, audit['search'], audit['events'] = self.retriever.search(package, question)
                batches = self.window.pack(question, files, selected)
                # Per-file selection first, then reranker order within the available first window.
                context = batches[0] if batches else []
                audit['retrieval_context_truncated'] = len(batches) > 1
                initial = messages(question, files, context)
            try:
                result = call(initial)
            except InvalidResponse:
                if mode in ('A', 'B'):
                    return unknown('invalid initial JSON; one-call mode'), audit
                result = correct(initial, {}, 'Invalid JSON')
            if mode in ('A', 'B'):
                # No citation verification, correction, reconciliation or additional Qwen call.
                return result, audit
            amendments = disable != 'amendments'
            anchors = content_anchors(question, package)

            def accept(item):
                checked = evidence(package, item, disable != 'quotes', amendments)
                missing = anchor_issue(checked['quote'], checked['unit'], anchors)
                if missing:
                    raise VerificationError("Evidence quote does not mention " + ", ".join(sorted(missing)))
                return checked

            chunks = self.active_chunks(package, amendments)
            batches = self.window.pack(question, files, chunks, SCAN,
                                       dict(issues=package.issues, amendments_enabled=amendments))
            collected = []
            for batch in batches:
                request = messages(question, files, batch, SCAN,
                                   dict(issues=package.issues, amendments_enabled=amendments))
                try:
                    scan = call(request)
                except InvalidResponse:
                    scan = correct(request, {}, 'Invalid scan JSON')
                def scan_ok(value):
                    # A single batch already contains the whole package, so an explicit
                    # complete flag is only required when several batches were sent.
                    return isinstance(value.get('evidence'), list) and (
                        value.get('complete') is True or len(batches) == 1)
                if not scan_ok(scan):
                    scan = correct(request, scan, 'Scan must return evidence array and complete=true')
                if not scan_ok(scan):
                    raise VerificationError('Incomplete package scan')
                for item in scan['evidence']:
                    try:
                        collected.append(accept(item))
                    except (VerificationError, TypeError, KeyError) as exc:
                        audit['events'].append(dict(kind='scan_evidence_rejected', reason=str(exc)))
            audit['full_scan'] = bool(chunks) and len(batches) > 0
            audit['scan_batches'] = len(batches)
            if mode == 'D':
                for item in result.get('evidence', []):
                    try:
                        collected.append(accept(item))
                    except (VerificationError, TypeError, KeyError) as exc:
                        audit['events'].append(dict(kind='first_pass_rejected', reason=str(exc)))
            # Deduplicate exact witnesses before reconciliation to keep context bounded.
            unique = {}
            for item in collected:
                if not isinstance(item, dict):
                    raise VerificationError('Invalid scan evidence')
                key = tuple(str(item.get(k, '')) for k in ('file', 'quote', 'value', 'unit'))
                unique[key] = item
            collected = list(unique.values())
            audit['scan_evidence'] = collected
            final_request = messages(question, files, [], SYNTHESIS, dict(
                first_pass=result, witnesses=collected, issues=package.issues,
                full_scan=audit['full_scan'], amendments=package.amendments if amendments else []))
            try:
                result = call(final_request)
            except InvalidResponse:
                result = correct(final_request, {}, 'Invalid synthesis JSON')
            if mode == 'D':
                def check(candidate):
                    checked = verify(package, candidate, question, audit['full_scan'],
                                     check_quotes=disable != 'quotes', arithmetic=disable != 'arithmetic', amendments=amendments)
                    # A synthesis cannot silently discard different independently found values.
                    if checked['status'] != 'не знаю':
                        for item in collected:
                            if not any(same_witness(item, x)
                                       for x in checked.get('evidence', [])):
                                raise VerificationError('Synthesis discarded independently found witness')
                    return checked
                try:
                    result = check(result)
                except (VerificationError, TypeError, KeyError) as exc:
                    result = check(correct(final_request, result, str(exc)))
            audit['evidence'] = result.get('evidence', [])
            return result, audit
        except (CallLimit, VerificationError, InvalidResponse, ValueError, TypeError, KeyError) as exc:
            audit['events'].append(dict(kind='abstention', reason=str(exc)))
            return unknown(str(exc)), audit
        finally:
            audit['calls'] = client.calls
            audit['usage'] = client.usage
