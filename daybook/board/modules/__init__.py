# the module list. a module is a python file here with collect(ctx) -> json, plus web/modules/<name>.js
from . import agent, fleet, today

MODULES = [
    {"name": "today", "title": "Today", "room": "today", "collect": today.collect},
    {"name": "agent", "title": "Agent", "room": "agent", "collect": agent.collect},
    {"name": "fleet", "title": "Fleet", "room": "fleet", "collect": fleet.collect},
]


def layout():
    from ..agent import agent_name
    # the agent room carries the configured name
    return [{"name": m["name"], "title": agent_name() if m["name"] == "agent" else m["title"], "room": m["room"]}
            for m in MODULES]
