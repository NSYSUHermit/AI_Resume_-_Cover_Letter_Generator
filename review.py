"""What the AI rewrite changed, and applying the user's edits back onto it.

Pure functions, no Streamlit - same reason workspace.py exists: app.py is a
top-level script and nothing defined there can be unit-tested in place.

The change list is computed here by comparing the Career Profile with the
optimized resume, not taken from the model's own account of what it did. So
it can neither list a change that did not happen nor miss one the model
forgot to mention. The model only supplies the "why", as {"path", "reason"}
pairs (see ai.build_rewrite_prompt()), matched to each change by path.

A change is a dict:
    id        stable string id, e.g. "experience.0.details.2"; removed
              content is "removed:<path in the ORIGINAL resume>"
    group     heading it is shown under, e.g. "Experience · Acme — Engineer"
    kind      EDITED, ADDED or REMOVED
    path      tuple into the optimized resume (None for REMOVED)
    before    the original text (None when ADDED)
    after     the optimized text (None when REMOVED)
    reason    the model's explanation, "" when it gave none
    is_list   True for skills: edited as one comma-separated line
    restore   REMOVED only: how apply_edits() puts the content back
"""

import copy
import difflib
import re

EDITED, ADDED, REMOVED = "edited", "added", "removed"


def _norm(text):
    return " ".join(str(text or "").split())


def _key(text):
    return _norm(text).lower()


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _bullet_text(detail):
    if isinstance(detail, dict):
        return str(detail.get("description") or "")
    return detail if isinstance(detail, str) else ""


def _bullet_path(entry_index, bullet_index, detail):
    path = ("experience", entry_index, "details", bullet_index)
    return path + ("description",) if isinstance(detail, dict) else path


def _entry_label(entry):
    company = _norm(entry.get("company")) or "Unknown company"
    role = _norm(entry.get("role"))
    return f"{company} — {role}" if role else company


# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------
def normalize_path(path):
    """"experience[0].details[2].description" -> "experience.0.details.2".

    The model is asked for paths into the optimized resume; this accepts
    either bracket or dot indexes, and a bullet's trailing ".description",
    so a reason still lands whichever spelling it chose.
    """
    path = str(path or "").strip()
    prefix = ""
    if path.lower().startswith("removed:"):
        prefix, path = "removed:", path[len("removed:"):].strip()
    parts = [p for p in re.sub(r"\[(\d+)\]", r".\1", path).split(".") if p]
    if len(parts) == 5 and parts[0] == "experience" and parts[2] == "details" and parts[4] == "description":
        parts = parts[:4]
    return prefix + ".".join(parts)


def _reason_index(reasons):
    index = {}
    for item in _list(reasons):
        if isinstance(item, dict) and item.get("path") and item.get("reason"):
            index.setdefault(normalize_path(item["path"]), _norm(item["reason"]))
    return index


def _reason_for(change_id, index):
    """The reason for `change_id`, else for its nearest ancestor - a reason
    given for a whole experience entry covers each of its bullets."""
    prefix = "removed:" if change_id.startswith("removed:") else ""
    parts = change_id[len(prefix):].split(".")
    while parts:
        reason = index.get(prefix + ".".join(parts))
        if reason:
            return reason
        parts.pop()
    return ""


# ---------------------------------------------------------------------------
# Matching original content to optimized content
# ---------------------------------------------------------------------------
def _match_entries(originals, optimized):
    """optimized index -> original index, for experience entries: same
    company and role, else same company. Each original is used once."""
    used, match = set(), {}
    for keyfn in (lambda e: (_key(e.get("company")), _key(e.get("role"))), lambda e: _key(e.get("company"))):
        for i, entry in enumerate(optimized):
            if i in match:
                continue
            for j, original in enumerate(originals):
                if j not in used and keyfn(original) == keyfn(entry):
                    match[i] = j
                    used.add(j)
                    break
    return match


def _match_by_name(originals, optimized, field="name"):
    used, match = set(), {}
    for i, item in enumerate(optimized):
        for j, original in enumerate(originals):
            if j not in used and _key(original.get(field)) == _key(item.get(field)):
                match[i] = j
                used.add(j)
                break
    return match


def _pair_bullets(original_texts, optimized_texts):
    """optimized index -> original index. Most similar pairs first, so a
    reordered bullet is still compared with the bullet it came from; what is
    left over on either side was added or removed."""
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, _key(a), _key(b)).ratio(), oi, pi)
            for oi, a in enumerate(original_texts)
            for pi, b in enumerate(optimized_texts)
        ),
        reverse=True,
    )
    used_original, pairs = set(), {}
    for _, oi, pi in scored:
        if oi not in used_original and pi not in pairs:
            used_original.add(oi)
            pairs[pi] = oi
    return pairs


# ---------------------------------------------------------------------------
# collect_changes
# ---------------------------------------------------------------------------
def _change(change_id, group, kind, path, before, after, is_list=False, restore=None):
    return {
        "id": change_id, "group": group, "kind": kind, "path": path,
        "before": before, "after": after, "reason": "", "is_list": is_list,
        "restore": restore,
    }


def _scalar(changes, field, group, original, optimized):
    before = _norm(original.get(field))
    after = optimized.get(field)
    if not isinstance(after, str) or _norm(after) == before:
        return
    changes.append(_change(field, group, EDITED if before else ADDED, (field,),
                           original.get(field) if before else None, after))


def _experience(changes, original, optimized):
    originals = [e for e in _list(original.get("experience")) if isinstance(e, dict)]
    entries = _list(optimized.get("experience"))
    match = _match_entries(originals, [e if isinstance(e, dict) else {} for e in entries])
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        group = f"Experience · {_entry_label(entry)}"
        details = _list(entry.get("details"))
        source = originals[match[i]] if i in match else {}
        source_details = _list(source.get("details"))
        original_texts = [_bullet_text(d) for d in source_details]
        texts = [_bullet_text(d) for d in details]
        pairs = _pair_bullets(original_texts, texts)
        for j, detail in enumerate(details):
            if not _norm(texts[j]):
                continue
            before = original_texts[pairs[j]] if j in pairs else None
            if before is not None and _key(before) == _key(texts[j]):
                continue
            changes.append(_change(
                f"experience.{i}.details.{j}", group, EDITED if before is not None else ADDED,
                _bullet_path(i, j, detail), before, texts[j],
            ))
        if i in match:
            paired = set(pairs.values())
            for oj, detail in enumerate(source_details):
                if oj not in paired and _norm(original_texts[oj]):
                    changes.append(_change(
                        f"removed:experience.{match[i]}.details.{oj}", group, REMOVED, None,
                        original_texts[oj], None,
                        restore={"into": ("experience", i, "details"), "index": oj, "value": copy.deepcopy(detail)},
                    ))
    matched = set(match.values())
    for oi, entry in enumerate(originals):
        if oi in matched:
            continue
        bullets = [_bullet_text(d) for d in _list(entry.get("details")) if _norm(_bullet_text(d))]
        changes.append(_change(
            f"removed:experience.{oi}", f"Experience · {_entry_label(entry)}", REMOVED, None,
            "\n".join([_entry_label(entry), *(f"• {b}" for b in bullets)]), None,
            restore={"into": ("experience",), "index": oi, "value": copy.deepcopy(entry)},
        ))


def _named_items(changes, section, label, original, optimized):
    """Projects / patents: matched by name, compared on description."""
    originals = [p for p in _list(original.get(section)) if isinstance(p, dict)]
    items = _list(optimized.get(section))
    match = _match_by_name(originals, [p if isinstance(p, dict) else {} for p in items])
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        after = item.get("description")
        before = originals[match[i]].get("description") if i in match else None
        if not isinstance(after, str) or (before is not None and _key(before) == _key(after)):
            continue
        name = _norm(item.get("name")) or "Untitled"
        changes.append(_change(
            f"{section}.{i}.description", f"{label} · {name}", EDITED if i in match else ADDED,
            (section, i, "description"), before, after,
        ))
    matched = set(match.values())
    for oi, item in enumerate(originals):
        if oi in matched:
            continue
        name = _norm(item.get("name")) or "Untitled"
        description = _norm(item.get("description"))
        changes.append(_change(
            f"removed:{section}.{oi}", f"{label} · {name}", REMOVED, None,
            f"{name} — {description}" if description else name, None,
            restore={"into": (section,), "index": oi, "value": copy.deepcopy(item)},
        ))


def _skills(changes, original, optimized):
    originals = _dict(original.get("skills"))
    sets = _dict(optimized.get("skills"))
    used = set()

    def find(key, skill_set):
        for okey, oset in originals.items():
            if okey not in used and isinstance(oset, dict) and _key(oset.get("title")) == _key(skill_set.get("title")):
                return okey
        return key if key in originals and key not in used and isinstance(originals[key], dict) else None

    for key, skill_set in sets.items():
        if not isinstance(skill_set, dict) or not isinstance(skill_set.get("items"), list):
            continue
        okey = find(key, skill_set)
        if okey is not None:
            used.add(okey)
        items = [_norm(i) for i in skill_set["items"] if _norm(i)]
        before_items = [_norm(i) for i in _list(originals[okey].get("items")) if _norm(i)] if okey is not None else None
        if before_items is not None and [i.lower() for i in before_items] == [i.lower() for i in items]:
            continue
        changes.append(_change(
            f"skills.{key}.items", f"Skills · {_norm(skill_set.get('title')) or key}",
            EDITED if okey is not None else ADDED, ("skills", key, "items"),
            ", ".join(before_items) if before_items is not None else None, ", ".join(items), is_list=True,
        ))
    for okey, oset in originals.items():
        if okey in used or not isinstance(oset, dict):
            continue
        items = [_norm(i) for i in _list(oset.get("items")) if _norm(i)]
        if not items:
            continue
        changes.append(_change(
            f"removed:skills.{okey}", f"Skills · {_norm(oset.get('title')) or okey}", REMOVED, None,
            ", ".join(items), None, is_list=True,
            restore={"into": ("skills",), "key": okey, "value": copy.deepcopy(oset)},
        ))


def collect_changes(original, optimized, reasons=None):
    """Every change between `original` (the Career Profile) and `optimized`,
    in resume order, each with the model's reason attached where it gave one.

    Education and the heading are not compared: the rewrite's evidence rules
    forbid changing them, and target_company / target_role are new fields,
    not rewrites.
    """
    if not isinstance(optimized, dict):
        return []
    original = _dict(original)
    changes = []
    _scalar(changes, "summary", "Summary", original, optimized)
    _experience(changes, original, optimized)
    _named_items(changes, "projects", "Projects", original, optimized)
    _named_items(changes, "patents", "Patents", original, optimized)
    _skills(changes, original, optimized)
    _scalar(changes, "cover_letter", "Cover letter", original, optimized)
    index = _reason_index(reasons)
    for change in changes:
        change["reason"] = _reason_for(change["id"], index)
    return changes


# ---------------------------------------------------------------------------
# apply_edits
# ---------------------------------------------------------------------------
def _set_path(data, path, text):
    node = data
    for step in path[:-1]:
        node = node[step]
    last = path[-1]
    if isinstance(node[last], list):
        node[last] = [part.strip() for part in text.split(",") if part.strip()]
    else:
        node[last] = text


def _get_path(data, path):
    node = data
    for step in path:
        node = node[step]
    return node


def apply_edits(optimized, edits, restores=()):
    """A copy of `optimized` with `edits` ({path: text}) written in and the
    REMOVED changes in `restores` put back. `optimized` is not modified.

    A path whose current value is a list (skills) takes comma-separated text.
    Restored content is appended to the end of its list, not reinserted at its
    old position: inserting would shift the index of everything after it, and
    the model's reasons are keyed by those indexes. A path that no longer
    exists is skipped rather than raising: the data may have been edited
    elsewhere since the change list was built.
    """
    data = copy.deepcopy(optimized)
    for path, text in edits.items():
        try:
            _set_path(data, path, text)
        except (KeyError, IndexError, TypeError):
            continue
    for change in sorted(restores, key=lambda c: (c["restore"]["into"], c["restore"].get("index", 0))):
        # Sorted so several restores into one list keep their original order.
        restore = change["restore"]
        try:
            target = _get_path(data, restore["into"])
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(target, list):
            target.append(copy.deepcopy(restore["value"]))
        elif isinstance(target, dict):
            key = restore["key"]
            while key in target:
                key += "_restored"
            target[key] = copy.deepcopy(restore["value"])
    return data
