"""Deterministic conversation compaction (W2 D10-11).

When the prompt nears the cost-derived context budget, large old tool_result
contents are replaced in place with one-line stubs. No LLM summarization
call, no messages or blocks added or removed — the tool_use/tool_result
pairing the API requires is untouchable. What must survive compaction
(PLAN D10-11): files touched (tool_use inputs are never elided, and every
stub names its tool + target), hypotheses (assistant messages are never
touched), test results (run_tests results keep their parsed summary header,
never fully elided).

Elision is oldest-first in one big pass down to a low-water mark: rare,
large compactions keep the compacted prefix stable afterwards, which is
what prompt caching (D12-13) needs — every compaction event invalidates
the cached prefix once.

The full tool results were logged to the trajectory when they happened
(tool_result_full, rule 5), so eliding them from the model's context loses
no post-hoc analysis data.
"""

PROTECT_LAST_TURNS = 3     # newest assistant turns whose results are never elided
MIN_ELIDE_CHARS = 500      # smaller blocks never earn a stub; also makes passes
                           # idempotent — stubs themselves fall under this floor
CHARS_PER_TOKEN = 4        # same +/-20% estimate the analysis scripts use


def prompt_tokens(usage) -> int:
    """Full prompt size of the request that produced this usage object:
    fresh + cache-read + cache-written input tokens (cache fields are 0
    until D12-13 caching lands, so the sum is future-proof)."""
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return usage.input_tokens + cache_read + cache_write


def estimate_tokens(chars: int) -> int:
    return chars // CHARS_PER_TOKEN


def _battr(block, key, default=None):
    """Read a field from either a dict block (our tool_result messages) or an
    SDK/fake object block (assistant content)."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _tool_use_index(messages) -> dict:
    """tool_use_id -> (tool name, tool input) across all assistant messages.
    tool_result blocks don't carry the tool name; stubs and the run_tests
    special case need it."""
    index = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg["content"]:
            if _battr(block, "type") == "tool_use":
                index[_battr(block, "id")] = (_battr(block, "name"), _battr(block, "input") or {})
    return index


def _target(name: str, tool_input: dict) -> str:
    """One-line what-was-this summary for a stub: enough for the model to
    re-issue the call if it turns out to matter."""
    if name == "read_file":
        path = tool_input.get("path", "?")
        start, end = tool_input.get("start_line"), tool_input.get("end_line")
        return f"{path}:{start}-{end}" if start or end else path
    if name in ("edit_file",):
        return tool_input.get("path", "?")
    if name == "bash":
        cmd = tool_input.get("command", "?")
        return cmd if len(cmd) <= 60 else cmd[:57] + "..."
    if name == "grep_glob":
        return " ".join(f"{k}={v}" for k, v in tool_input.items() if k in ("pattern", "glob"))
    return ""


def _stub(name: str, tool_input: dict, chars: int, turn: int, is_error) -> str:
    err = " (was an error)" if is_error else ""
    target = _target(name or "?", tool_input)
    return (f"[elided at turn {turn}: {name} {target} — {chars:,} chars{err}; "
            f"re-run the tool if this result is needed again]")


def compact_messages(messages: list, *, target_tokens: int, turn: int,
                     protect_last_turns: int = PROTECT_LAST_TURNS) -> dict:
    """Mutate `messages` in place, eliding oldest-first until ~target_tokens
    (estimated) are removed or eligible blocks run out. Returns stats for the
    trajectory meta line. Only dict blocks with type=="tool_result" and str
    content inside user messages are candidates; message count and per-message
    block count are invariants."""
    stats = {"blocks_elided": 0, "chars_removed": 0, "est_tokens_removed": 0,
             "target_met": False, "elided_tool_use_ids": []}
    if target_tokens <= 0:
        stats["target_met"] = True
        return stats

    # Protect the working set: everything from the protect_last_turns-th
    # newest assistant message onward stays verbatim.
    assistant_idx = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(assistant_idx) <= protect_last_turns:
        return stats
    boundary = assistant_idx[-protect_last_turns]

    index = _tool_use_index(messages)
    # Index 0 is the task prompt (a plain string, filtered by the list check
    # anyway) — start at 1 for clarity.
    for i in range(1, boundary):
        msg = messages[i]
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            content = block.get("content")
            if not isinstance(content, str) or len(content) < MIN_ELIDE_CHARS:
                continue
            name, tool_input = index.get(block.get("tool_use_id"), (None, {}))
            if name == "run_tests":
                # Test results are preserved by contract: keep the parsed
                # summary header, elide only the traceback/output tail.
                header, _, tail = content.partition("\n")
                if len(tail) < MIN_ELIDE_CHARS:
                    continue
                replacement = (header + f"\n[elided at turn {turn}: run_tests output tail — "
                               f"{len(tail):,} chars; re-run run_tests for full output]")
            else:
                replacement = _stub(name, tool_input, len(content), turn, block.get("is_error"))
            if len(replacement) >= len(content):
                continue
            block["content"] = replacement
            stats["blocks_elided"] += 1
            stats["chars_removed"] += len(content) - len(replacement)
            stats["elided_tool_use_ids"].append(block.get("tool_use_id"))
            if estimate_tokens(stats["chars_removed"]) >= target_tokens:
                stats["est_tokens_removed"] = estimate_tokens(stats["chars_removed"])
                stats["target_met"] = True
                return stats
    stats["est_tokens_removed"] = estimate_tokens(stats["chars_removed"])
    return stats
