"""Step-0 gate for D12-13 prompt caching (rule 1): exact size of the stable
prefix (tools + system) vs Haiku 4.5's 4096-token minimum cacheable prefix.

count_tokens is free. The number decides the breakpoint layout: if the stable
prefix is under 4096, a breakpoint on the system block alone can never cache
and all caching rides on the conversation breakpoint (whose cumulative prefix
crosses the minimum within a couple of turns).

Usage: python -m analysis.measure_prefix [model] [min_cacheable]
(defaults: claude-haiku-4-5 / 4096 — W3: pass claude-sonnet-5 with its minimum,
which the cached reference table omits; candidates are 1,024 per the D15 live
pin or 2,048 per the Sonnet-4.6 row. Token counts are model-tokenizer-specific:
Sonnet 5 counts ~30% more than Haiku for the same bytes.)
"""

import os
import sys

import anthropic

from agent.loop import SYSTEM_PROMPT
from agent.tools import TOOL_SCHEMAS

MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-4-5"
HAIKU_MIN_CACHEABLE = int(sys.argv[2]) if len(sys.argv) > 2 else 4096


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1
    client = anthropic.Anthropic(api_key=api_key)

    # count_tokens needs a non-empty messages array; use a 1-token placeholder
    # and also measure it alone so we can subtract it out.
    placeholder = [{"role": "user", "content": "x"}]

    full = client.messages.count_tokens(
        model=MODEL, system=SYSTEM_PROMPT, tools=TOOL_SCHEMAS, messages=placeholder
    ).input_tokens
    no_tools = client.messages.count_tokens(
        model=MODEL, system=SYSTEM_PROMPT, messages=placeholder
    ).input_tokens
    bare = client.messages.count_tokens(model=MODEL, messages=placeholder).input_tokens

    tools_tok = full - no_tools
    system_tok = no_tools - bare
    prefix = tools_tok + system_tok

    print(f"model                 : {MODEL}")
    print(f"tools (5 schemas)     : ~{tools_tok} tok")
    print(f"system prompt         : ~{system_tok} tok")
    print(f"stable prefix (t+s)   : ~{prefix} tok")
    print(f"min cacheable prefix  : {HAIKU_MIN_CACHEABLE} tok")
    if prefix >= HAIKU_MIN_CACHEABLE:
        print("VERDICT: stable prefix alone is cacheable — breakpoint 1 (system "
              "block) will produce cross-run cache reads on its own.")
    else:
        deficit = HAIKU_MIN_CACHEABLE - prefix
        print(f"VERDICT: stable prefix alone is {deficit} tok UNDER the minimum — "
              "breakpoint 1 never caches by itself; caching rides on the "
              "conversation breakpoint once cumulative prefix >= 4096. "
              "Cross-run cache_read on run 2 may legitimately be 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
