"""Request knobs the subscription never exposed: temperature, seed, stop words,
prefill (forced first words of the answer), and a faster service tier.

The knobs travel as one small object from the CLI into every lane. A lane sends
only the knobs its wire protocol carries; a knob the provider rejects prints the
provider's exact error once and the lane carries on without it. No knob here
changes a default: every field is None until the operator sets it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Knobs:
    temperature: Optional[float] = None
    seed: Optional[int] = None
    stop: Optional[List[str]] = None
    prefill: Optional[str] = None
    service_tier: Optional[str] = None

    def any(self) -> bool:
        return any(v is not None for v in (self.temperature, self.seed, self.stop, self.prefill, self.service_tier))

    def as_dict(self) -> dict:
        out = {}
        if self.temperature is not None: out['temperature'] = self.temperature
        if self.seed is not None: out['seed'] = self.seed
        if self.stop is not None: out['stop'] = list(self.stop)
        if self.service_tier is not None: out['service_tier'] = self.service_tier
        # prefill is applied to the answer text, not sent as a wire sampling field.
        return out

    def cli_options(self) -> list:
        """Rebuild the exact flags, so chat mode can forward knobs to each turn."""
        opts: list = []
        if self.temperature is not None: opts += ['--temperature', repr(self.temperature)]
        if self.seed is not None: opts += ['--seed', str(self.seed)]
        for word in (self.stop or []): opts += ['--stop', word]
        if self.prefill is not None: opts += ['--prefill', self.prefill]
        if self.service_tier is not None: opts += ['--service-tier', self.service_tier]
        return opts


def add_flags(parser) -> None:
    parser.add_argument('--temperature', type=float, default=None,
                        help='Sampling temperature. Sent where the model accepts it; refused once with the exact error otherwise.')
    parser.add_argument('--seed', type=int, default=None,
                        help='Fixed sampling seed for repeatable output, where the model accepts it.')
    parser.add_argument('--stop', action='append', default=None, metavar='WORD',
                        help='A stop string; repeatable. The answer ends before any stop string the model honors.')
    parser.add_argument('--prefill', default=None, metavar='TEXT',
                        help='Force the first words of the answer. Applied to direct_answer at the harness layer.')
    parser.add_argument('--service-tier', default=None, metavar='TIER',
                        help='Request a faster service tier where the provider offers one.')


def validate(parser, args) -> None:
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        parser.error('--temperature must be between 0 and 2.')
    if args.stop is not None:
        if len(args.stop) > 4:
            parser.error('At most four --stop strings.')
        for word in args.stop:
            if not word:
                parser.error('A --stop string cannot be empty.')
    if args.prefill is not None and not args.prefill.strip():
        parser.error('--prefill text cannot be blank.')


def from_args(args) -> Knobs:
    return Knobs(temperature=args.temperature, seed=args.seed,
                 stop=list(args.stop) if args.stop else None,
                 prefill=args.prefill, service_tier=args.service_tier)


# Knob support on the two built-in lanes, measured live against the production
# models on 2026-11-11. ('send', api_field) applies it; ('skip', error) prints the
# recorded provider error once and carries on; ('prefill', None) is the answer-layer
# forced opening. gpt-6.1-sol and claude-opus-5-5 were the models checked.
BUILTIN_SUPPORT = {
    'openai': {
        'temperature': ('skip', "Unsupported parameter: 'temperature' is not supported with this model."),
        'seed': ('skip', 'The OpenAI Responses API accepts no seed parameter on this model.'),
        'stop': ('skip', 'The OpenAI Responses API accepts no stop parameter; it enforces structured output.'),
        'service_tier': ('send', 'service_tier'),
        'prefill': ('prefill', None),
    },
    'anthropic': {
        'temperature': ('skip', 'temperature: Extra inputs are not permitted (HTTP 400 on this model).'),
        'seed': ('skip', 'The Anthropic Messages API accepts no seed parameter.'),
        'stop': ('send', 'stop_sequences'),
        'service_tier': ('send', 'service_tier'),
        'prefill': ('prefill', None),
    },
}


def resolve_builtin(engine: str, kb: 'Knobs'):
    """For the openai/anthropic lanes: map the set knobs to real API fields and
    collect a one-line note for every knob this model refuses. Returns (wire, notes)."""
    support = BUILTIN_SUPPORT.get(engine, {})
    wire: dict = {}
    notes: list = []
    values = {'temperature': kb.temperature, 'seed': kb.seed, 'stop': kb.stop,
              'service_tier': kb.service_tier, 'prefill': kb.prefill}
    for name, value in values.items():
        if value is None:
            continue
        action, detail = support.get(name, ('skip', 'not supported on this lane.'))
        if action == 'send':
            wire[detail] = list(value) if isinstance(value, list) else value
        elif action == 'skip':
            notes.append(f'[{engine}] knob --{name.replace("_", "-")} refused: {detail}')
    return wire, notes


def apply_prefill(answer: str, prefill: Optional[str]) -> str:
    """Guarantee the answer opens with the forced words. The four-field schema
    forbids a true assistant-message prefill (it would break strict JSON), so the
    forced opening is enforced on the validated text instead."""
    if not prefill:
        return answer
    lead = prefill.rstrip()
    if answer.startswith(lead) or answer.lstrip().startswith(lead):
        return answer
    glue = '' if lead.endswith(('\n', ' ')) else ' '
    return lead + glue + answer
