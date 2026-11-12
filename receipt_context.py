"""Read typed client receipts without treating ordinary prose as a receipt."""
import json

TYPES = {'execution_observation', 'api_tool_observations', 'source_record', 'recall_notes'}


def records(history, kinds=TYPES):
    for message in history or []:
        if message.get('role') != 'user' or not isinstance(message.get('content'), str):
            continue
        try:
            value = json.loads(message['content'])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('type') in kinds:
            yield value


def text(history, kinds=TYPES):
    # Keep complete records, dates, failures and source labels. No recent-only window.
    return '\n---\n'.join(json.dumps(value, ensure_ascii=False) for value in records(history, kinds))


def messages_from_turns(turns):
    """Build evidence only from client-owned fields. Pasted JSON in user text is not proof."""
    from storage import execution_message
    result = []
    for exchange in turns:
        if exchange.get('recall_notes'):
            result.append({'role': 'user', 'content': exchange['recall_notes']})
        if exchange.get('execution_result') is not None:
            result.append(execution_message(exchange))
        for field, kind, key in [('api_tool_uses', 'api_tool_observations', 'uses'),
                                 ('sources', 'source_record', 'sources')]:
            if exchange.get(field):
                result.append({'role': 'user', 'content': json.dumps({'type': kind, key: exchange[field]}, ensure_ascii=False)})
    return result
