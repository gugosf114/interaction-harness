"""The thread tree, rebuilt from the thread-tree mod for the lanes.

George branches deep while he reads and loses the parent topic. After each turn a small model reads his
message (and the start of the answer) against the open trail and says how the trail moves: push (deeper),
pop (branch closed, back up), switch (sideways), new (a fresh top topic) or stay. It also says whether the
answer closed the deepest branch, and then the lane offers the way back in one line.

The tree lives in the session file under "thread_tree": every topic node with its parent and state, and the
stack of open nodes from the top topic down to the current one. /where prints it. /up closes the current
branch by hand. All tree logic here is pure; the model call is in lane_mods.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re

MAX_LABEL = 40
ACTIONS = ('push', 'pop', 'switch', 'new', 'stay')
STOP = set('the a an to of in on for and or but so is it this that what how why where when which who whose do does '
           'did you i we can ok okay yeah yes no now my me'.split())

SYSTEM = ('You track the branch structure of a conversation. Given the current topic trail (top-level first, '
          'deepest last), the user\'s newest message and the start of the answer, decide how the message moves the '
          'trail. Labels are 2-4 words. JSON only.')


def empty() -> dict:
    return {'nodes': [], 'stack': [], 'popped': False}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _node(tree, label, parent):
    tree['nodes'].append({'label': label, 'parent': parent, 'state': 'open', 'opened': _now()})
    return len(tree['nodes']) - 1


def _close(tree, index):
    if 0 <= index < len(tree['nodes']) and tree['nodes'][index]['state'] == 'open':
        tree['nodes'][index]['state'] = 'closed'
        tree['nodes'][index]['closed'] = _now()


def apply(tree: dict, action: str, label: str = '') -> dict:
    """Fold one action into the tree, in place. Returns the tree. Pure apart from the timestamps."""
    label = ' '.join((label or '').split())[:MAX_LABEL]
    stack = tree['stack']
    tree['popped'] = False
    if action == 'push' and label:
        stack.append(_node(tree, label, stack[-1] if stack else None))
    elif action == 'pop' and len(stack) > 1:
        _close(tree, stack.pop())
        tree['popped'] = True
    elif action == 'switch' and label:
        if stack:
            _close(tree, stack.pop())
        stack.append(_node(tree, label, stack[-1] if stack else None))
    elif action == 'new' and label:
        for index in stack:
            _close(tree, index)
        stack[:] = [_node(tree, label, None)]
    return tree


def seed_label(prompt: str) -> str:
    words = [w for w in re.sub(r'[^a-z0-9\s]', ' ', prompt.lower()).split() if w not in STOP]
    return ' '.join((words or prompt.lower().split())[:4])[:30] or 'topic'


def parse(raw: str | None) -> tuple[str, str, bool]:
    match = re.search(r'\{.*\}', raw or '', re.S)
    try:
        obj = json.loads(match.group(0)) if match else {}
    except ValueError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    action = str(obj.get('action') or 'stay').lower()
    return (action if action in ACTIONS else 'stay'), str(obj.get('label') or ''), obj.get('done') is True


def labels(tree: dict) -> list[str]:
    return [tree['nodes'][i]['label'] for i in tree['stack']]


def move_prompt(tree: dict, message: str, answer: str) -> str:
    trail = '\n'.join(f'{n}. {label}' for n, label in enumerate(labels(tree), 1)) or '(empty)'
    return (f'CURRENT TRAIL (top first, deepest last):\n{trail}\n\n'
            f"USER'S NEWEST MESSAGE:\n{message}\n\n"
            f'THE ANSWER IT GOT:\n{answer}\n\n'
            'Choose ONE action:\n'
            '- push: the message goes DEEPER into a sub-topic of the deepest item. Give a short label.\n'
            '- pop: the message CLOSES the current branch and returns to the parent. No label.\n'
            '- switch: a sideways move to a sibling topic at the same depth. Give a label.\n'
            '- new: a brand-new top-level topic unrelated to the trail. Give a label.\n'
            '- stay: same topic as the deepest item. No label.\n'
            'Also say "done": true when the answer fully settles the deepest item, so the user can go back up.\n'
            'Return ONLY JSON: {"action":"push","label":"send gate","done":false}')


def update(tree: dict, raw: str | None, message: str) -> tuple[dict, bool]:
    """Apply the model's reading; seed an empty tree from the message. Returns (tree, branch_done)."""
    action, label, done = parse(raw)
    apply(tree, action, label)
    if not tree['stack']:
        apply(tree, 'new', seed_label(message))
    return tree, done


def up(tree: dict) -> str | None:
    """Close the current branch by hand. The parent's label, or None when already at the top."""
    if len(tree['stack']) < 2:
        return None
    apply(tree, 'pop')
    return labels(tree)[-1]


def after_turn_line(tree: dict, done: bool) -> str | None:
    """The one line shown after the answer: back up after a pop, or the offer when a branch is settled."""
    trail = labels(tree)
    if tree.get('popped') and trail:
        return f'↑ back to: {trail[-1]}'
    if done and len(trail) > 1:
        return f'↑ "{trail[-1]}" looks settled. Back to "{trail[-2]}": type /up.'
    return None


def render(tree: dict) -> str:
    """/where: the breadcrumb, then the whole tree with each node's state."""
    if not tree.get('nodes'):
        return 'Thread tree: empty.'
    trail = labels(tree)
    lines = ['Where we are: ' + ' › '.join(trail) if trail else 'Where we are: (no open topic)', '']
    children = {}
    for index, node in enumerate(tree['nodes']):
        children.setdefault(node['parent'], []).append(index)
    current = tree['stack'][-1] if tree['stack'] else None

    def walk(index, depth):
        node = tree['nodes'][index]
        mark = '  ◀ here' if index == current else ('' if node['state'] == 'open' else '  (closed)')
        lines.append('  ' * depth + ('└ ' if depth else '') + node['label'] + mark)
        for child in children.get(index, []):
            walk(child, depth + 1)

    for root in children.get(None, []):
        walk(root, 0)
    return '\n'.join(lines)
