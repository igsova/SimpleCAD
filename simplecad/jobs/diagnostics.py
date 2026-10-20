"""Bounded worker failure details, collected before temporary files are removed."""
import json


def log_tail(path, limit=8192):
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-limit))
            return stream.read(limit).decode('utf-8', errors='replace').strip()
    except OSError:
        return ''


def failure_details(folder, code, crashed=False):
    stage = ''
    try:
        value = json.loads((folder/'progress.json').read_text()).get('stage')
        if isinstance(value,str):
            stage = ' '.join(value.split())[:180]
    except (OSError, ValueError, AttributeError):
        pass
    action = 'crashed' if crashed else 'stopped without a usable result'
    summary = 'The mesh worker %s%s (exit code %s). Original mesh unchanged.' % (
        action, ' during '+stage if stage else '', code)
    logs = [summary]
    for name in ('worker-error.log','worker.log'):
        tail = log_tail(folder/name)
        if tail:
            logs.append(name+':\n'+tail)
    return summary+' See Report view for details.', '\n'.join(logs)
