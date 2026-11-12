"""The registry of extra lanes: more brains behind the same four-field reply.

Each provider is its own module (gemini_lane, openrouter_lane, glm_lane,
vertex_lane) built on the shared gate in lane_base. This file only names them and
forwards harness.request_reply to the matching lane, so the edit to
harness.request_reply stays one dispatch branch.

| Shortcut | --engine     | Model (default)       | Key                           | Reply |
|----------|--------------|-----------------------|-------------------------------|-------|
| g2       | gemini       | gemini-4-carbon       | state/gemini-api-key          | strict four-field JSON, web via Google Search |
| g3       | openrouter   | z-ai/glm-5.3          | state/openrouter-api-key      | strict four-field JSON, web via the web plugin |
| g4       | glm          | glm-george (LoRA v11) | none (public Modal endpoint)  | plain text wrapped as an observation |
| gv       | vertex       | claude-opus-5-5       | gcloud token (ADC)            | strict four-field JSON (emit_reply), web via web_search |
"""
from __future__ import annotations

import gemini_lane
import glm_lane
import lane_base
import openrouter_lane
import vertex_lane

LaneError = lane_base.LaneError

LANES = {
    'gemini': gemini_lane.LANE,
    'openrouter': openrouter_lane.LANE,
    'glm': glm_lane.LANE,
    'vertex': vertex_lane.LANE,
}


def is_lane(engine: str) -> bool:
    return engine in LANES


def lane_model(lane, requested=None):
    return lane_base.lane_model(lane, requested)


def request_reply(raw_input, *, engine='gemini', **kwargs):
    return lane_base.request_reply(LANES[engine], raw_input, **kwargs)
