#!/usr/bin/env python3
"""
claude_mcp_server.py — MCP server for managing Claude.ai Projects.

Exposes tools for reading and writing Claude.ai Project instructions,
knowledge files, and memory via the internal web API.

Auth: Firefox session cookies (same cascading pattern as notion-agents).

Usage:
  python cli/claude_mcp_server.py                        # stdio transport
  claude mcp add claude-projects -- python cli/claude_mcp_server.py
"""

import io
import json
import os
import re
import sys
import zipfile

# Allow running from project root or cli/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

import claude_cookie_extract
import claude_client as _claude_client

mcp = FastMCP("claude-projects")

_claude_project_client = None


def _get_client() -> _claude_client.ClaudeProjectClient:
    global _claude_project_client
    if _claude_project_client is None:
        cookie_header = claude_cookie_extract.get_cookie_header()
        org_id = os.environ.get("CLAUDE_ORG_ID")
        if not org_id:
            from urllib.request import Request, urlopen
            req = Request("https://claude.ai/api/organizations")
            req.add_header("Cookie", cookie_header)
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0")
            with urlopen(req) as resp:
                orgs = json.loads(resp.read())
            if not orgs:
                raise ValueError("No Claude.ai organizations found.")
            org_id = orgs[0]["uuid"]
        _claude_project_client = _claude_client.ClaudeProjectClient(cookie_header, org_id)
    return _claude_project_client


@mcp.tool()
def claude_list_projects(limit: int = 30) -> str:
    """List Claude.ai Projects."""
    client = _get_client()
    projects = client.list_projects(limit=limit)
    lines = []
    for p in projects:
        try:
            docs = client.list_docs(p["uuid"])
            doc_count = len(docs)
        except Exception:
            doc_count = "?"
        lines.append(f'{p["uuid"]}  {p["name"]}  ({doc_count} docs)')
    return "\n".join(lines)


@mcp.tool()
def claude_list_docs(project_id: str) -> str:
    """List knowledge files in a Claude.ai Project."""
    client = _get_client()
    docs = client.list_docs(project_id)
    lines = []
    for d in docs:
        tokens = d.get("estimated_token_count", "?")
        lines.append(f'{d["uuid"]}  {d["file_name"]}  ({tokens} tokens)')
    return "\n".join(lines)


@mcp.tool()
def claude_get_instructions(project_id: str) -> str:
    """Get the system prompt / instructions for a Claude.ai Project."""
    client = _get_client()
    project = client.get_project(project_id)
    return project.get("prompt_template", "")


@mcp.tool()
def claude_set_instructions(project_id: str, instructions: str) -> str:
    """Update the system prompt / instructions for a Claude.ai Project.

    Args:
        project_id: The project UUID.
        instructions: The full instructions text to set.
    """
    client = _get_client()
    client.update_project(project_id, prompt_template=instructions)
    return f"Instructions updated for project {project_id}."


@mcp.tool()
def claude_upload_doc(project_id: str, file_name: str, content: str) -> str:
    """Upload a knowledge file to a Claude.ai Project.

    Args:
        project_id: The project UUID.
        file_name: Name for the file in the project.
        content: The file content (text/markdown).
    """
    client = _get_client()
    result = client.upload_doc(project_id, file_name, content)
    tokens = result.get("estimated_token_count", "?")
    return f'Uploaded {file_name} → {result["uuid"]} ({tokens} tokens)'


@mcp.tool()
def claude_delete_doc(project_id: str, doc_uuid: str) -> str:
    """Delete a knowledge file from a Claude.ai Project.

    Args:
        project_id: The project UUID.
        doc_uuid: The UUID of the doc to delete (from claude_list_docs).
    """
    client = _get_client()
    client.delete_doc(project_id, doc_uuid)
    return f"Deleted {doc_uuid}"


@mcp.tool()
def claude_delete_doc_by_name(project_id: str, file_name: str) -> str:
    """Delete a knowledge file from a Claude.ai Project by filename.

    Args:
        project_id: The project UUID.
        file_name: The filename to delete (from claude_list_docs).
    """
    client = _get_client()
    docs = client.list_docs(project_id)
    matches = [d for d in docs if d["file_name"] == file_name]
    if not matches:
        return f"No doc named '{file_name}' found in project {project_id}."
    doc = matches[0]
    client.delete_doc(project_id, doc["uuid"])
    return f"Deleted {file_name} ({doc['uuid']})"


@mcp.tool()
def claude_read_doc(project_id: str, identifier: str) -> str:
    """Read the full content of a knowledge file in a Claude.ai Project.

    Args:
        project_id: The project UUID.
        identifier: Either a doc UUID or a filename (from claude_list_docs).
    """
    client = _get_client()
    # Try as UUID first; fall back to name lookup
    docs = client.list_docs(project_id)
    by_uuid = {d["uuid"]: d for d in docs}
    by_name = {d["file_name"]: d for d in docs}

    if identifier in by_uuid:
        doc_uuid = identifier
        file_name = by_uuid[identifier]["file_name"]
    elif identifier in by_name:
        doc_uuid = by_name[identifier]["uuid"]
        file_name = identifier
    else:
        return f"No doc matching '{identifier}' in project {project_id}."

    doc = by_uuid.get(doc_uuid) or by_name.get(file_name, {})
    content = doc.get("content", "")
    tokens = doc.get("estimated_token_count", "?")
    return f"# {file_name}  ({tokens} tokens)\n\n{content}"


@mcp.tool()
def claude_search_docs(project_id: str, query: str) -> str:
    """Search for a string across all knowledge files in a Claude.ai Project.

    Returns matching excerpts with surrounding context.

    Args:
        project_id: The project UUID.
        query: Case-insensitive substring to search for.
    """
    client = _get_client()
    docs = client.list_docs(project_id)
    query_lower = query.lower()
    results = []

    for d in docs:
        content = d.get("content", "")
        if query_lower not in content.lower():
            continue
        lines = content.splitlines()
        excerpts = []
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                excerpt = "\n".join(lines[start:end])
                excerpts.append(f"  …line {i + 1}…\n{excerpt}")
        results.append(f"### {d['file_name']}\n" + "\n---\n".join(excerpts))

    if not results:
        return f"No matches for '{query}' in project {project_id}."
    return f"Found in {len(results)} doc(s):\n\n" + "\n\n".join(results)


def _extract_text(content) -> str:
    """Pull plain text out of a Claude.ai message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or block.get("content", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def _get_messages(client, conv_uuid: str) -> list[dict]:
    data = client.get_conversation(conv_uuid)
    raw_messages = data.get("chat_messages", []) if data else []
    return [
        {
            "role": m.get("sender", m.get("role", "?")),
            "text": _extract_text(m.get("text", m.get("content", ""))),
        }
        for m in raw_messages
    ]


def _safe_chat_stem(title: str, conv_uuid: str) -> str:
    base = title or conv_uuid
    safe = re.sub(r"[^\w\s-]", "", base).strip()
    safe = re.sub(r"\s+", "_", safe)[:80]
    return safe or conv_uuid


def _render_chat_markdown(conv: dict, messages: list[dict]) -> str:
    title = conv.get("name", "(untitled)")
    created = conv.get("created_at", "")[:10]
    lines = [f"# {title}\n", f"*{created} · {len(messages)} turns*\n"]
    for m in messages:
        role = m["role"].upper()
        lines.append(f"\n## [{role}]\n\n{m['text'].strip()}\n")
    return "\n".join(lines)


def _resolve_chat_matches(convs: list[dict], identifier: str) -> list[dict]:
    by_uuid = {c["uuid"]: c for c in convs}
    if identifier in by_uuid:
        return [by_uuid[identifier]]
    return [c for c in convs if identifier.lower() in c.get("name", "").lower()]


def _resolve_chat_targets(convs: list[dict], identifiers: str) -> tuple[list[dict], list[str]]:
    seen = set()
    resolved = []
    errors = []

    for raw_identifier in identifiers.split(","):
        identifier = raw_identifier.strip()
        if not identifier:
            continue
        matches = _resolve_chat_matches(convs, identifier)
        if not matches:
            errors.append(f"No conversation matching '{identifier}'.")
            continue
        if len(matches) > 1:
            opts = "\n".join(f'  {c["uuid"]}  {c.get("name", "")}' for c in matches)
            errors.append(f"Multiple matches for '{identifier}' — use a UUID:\n{opts}")
            continue
        conv = matches[0]
        if conv["uuid"] in seen:
            continue
        seen.add(conv["uuid"])
        resolved.append(conv)

    return resolved, errors


@mcp.tool()
def claude_list_chats(project_id: str, limit: int = 50) -> str:
    """List conversations (chats) in a Claude.ai Project.

    Args:
        project_id: The project UUID.
        limit: Max number of conversations to return (default 50).
    """
    client = _get_client()
    convs = client.list_conversations(project_id, limit=limit)
    if not convs:
        return "No conversations found."
    lines = []
    for c in convs:
        created = c.get("created_at", "")[:10]
        lines.append(f'{c["uuid"]}  {c.get("name", "(untitled)")}  [{created}]')
    return "\n".join(lines)


@mcp.tool()
def claude_read_chat(project_id: str, identifier: str) -> str:
    """Read the full transcript of a conversation in a Claude.ai Project.

    Args:
        project_id: The project UUID.
        identifier: Conversation UUID or a title substring (from claude_list_chats).
    """
    client = _get_client()
    convs = client.list_conversations(project_id, limit=200)
    matches = _resolve_chat_matches(convs, identifier)
    if not matches:
        return f"No conversation matching '{identifier}'."
    if len(matches) > 1:
        opts = "\n".join(f'  {c["uuid"]}  {c.get("name", "")}' for c in matches)
        return f"Multiple matches — use a UUID:\n{opts}"
    conv = matches[0]

    messages = _get_messages(client, conv["uuid"])
    lines = [f'# {conv.get("name", "(untitled)")}  ({len(messages)} turns)\n']
    for m in messages:
        role = m["role"].upper()
        lines.append(f"[{role}]\n{m['text'].strip()}\n")
    return "\n".join(lines)


@mcp.tool()
def claude_extract_chats(project_id: str, identifiers: str, output_dir: str) -> str:
    """Extract one or more Claude.ai Project chats to local Markdown files.

    Args:
        project_id: The project UUID.
        identifiers: Comma-separated conversation UUIDs or title substrings.
        output_dir: Absolute path to destination directory (created if absent).
    """
    client = _get_client()
    convs = client.list_conversations(project_id, limit=200)
    resolved, errors = _resolve_chat_targets(convs, identifiers)
    if errors:
        return "\n\n".join(errors)
    if not resolved:
        return "No conversations selected."

    os.makedirs(output_dir, exist_ok=True)
    log = []
    used_names = set()
    for conv in resolved:
        messages = _get_messages(client, conv["uuid"])
        stem = _safe_chat_stem(conv.get("name", ""), conv["uuid"])
        fname = f"{stem}.md"
        if fname in used_names:
            fname = f"{stem}_{conv['uuid'][:8]}.md"
        used_names.add(fname)
        with open(os.path.join(output_dir, fname), "w") as f:
            f.write(_render_chat_markdown(conv, messages))
        log.append(f"  chat → {fname}  ({len(messages)} turns)")

    summary = f"Extracted {len(resolved)} chat(s) from project {project_id} to {output_dir}\n\n"
    return summary + "\n".join(log)


@mcp.tool()
def claude_search_chats(project_id: str, query: str, limit: int = 50) -> str:
    """Search for a string across all conversations in a Claude.ai Project.

    Returns matching excerpts with the conversation title and role.

    Args:
        project_id: The project UUID.
        query: Case-insensitive substring to search for.
        limit: Max number of conversations to search (default 50).
    """
    client = _get_client()
    convs = client.list_conversations(project_id, limit=limit)
    query_lower = query.lower()
    results = []

    for c in convs:
        messages = _get_messages(client, c["uuid"])
        hits = []
        for m in messages:
            text = m["text"]
            if query_lower not in text.lower():
                continue
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    excerpt = "\n".join(lines[start:end])
                    hits.append(f"  [{m['role'].upper()}] …line {i + 1}…\n{excerpt}")
        if hits:
            results.append(f"### {c.get('name', c['uuid'])}\n" + "\n---\n".join(hits))

    if not results:
        return f"No matches for '{query}' in project {project_id} chats."
    return f"Found in {len(results)} conversation(s):\n\n" + "\n\n".join(results)


@mcp.tool()
def claude_sync_docs(project_id: str, files: str) -> str:
    """Sync local files to a Claude.ai Project's knowledge base.

    Replaces docs with matching filenames (delete + re-upload). Adds new ones.
    Skips files whose content hasn't changed.

    Args:
        project_id: The project UUID.
        files: Comma-separated list of absolute file paths to sync.
    """
    client = _get_client()
    remote_docs = client.list_docs(project_id)
    remote_by_name = {d["file_name"]: d for d in remote_docs}

    file_paths = [f.strip() for f in files.split(",")]
    lines = []
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        with open(file_path) as f:
            content = f.read()

        if file_name in remote_by_name:
            remote_doc = remote_by_name[file_name]
            if remote_doc.get("content", "").strip() == content.strip():
                lines.append(f"  skip  {file_name} (unchanged)")
                continue
            client.delete_doc(project_id, remote_doc["uuid"])
            result = client.upload_doc(project_id, file_name, content)
            lines.append(f"  update  {file_name} → {result['uuid']}")
        else:
            result = client.upload_doc(project_id, file_name, content)
            lines.append(f"  add  {file_name} → {result['uuid']}")

    return "\n".join(lines)


@mcp.tool()
def claude_get_memory(project_id: str) -> str:
    """Get the project memory entries for a Claude.ai Project."""
    client = _get_client()
    memory = client.get_memory(project_id)
    return json.dumps(memory, indent=2)


@mcp.tool()
def claude_clone_project(project_id: str, output_dir: str) -> str:
    """Clone a Claude.ai Project to a local directory.

    Saves:
      INSTRUCTIONS.md       — project system prompt
      docs/<filename>       — all knowledge files
      chats/<title>.md      — all conversation transcripts

    Args:
        project_id: The project UUID.
        output_dir: Absolute path to destination directory (created if absent).
    """
    client = _get_client()
    os.makedirs(output_dir, exist_ok=True)

    log = []

    # -- Instructions --
    project = client.get_project(project_id)
    instructions = project.get("prompt_template", "")
    instr_path = os.path.join(output_dir, "INSTRUCTIONS.md")
    with open(instr_path, "w") as f:
        f.write(instructions)
    log.append(f"  instructions → INSTRUCTIONS.md")

    # -- Docs --
    docs_dir = os.path.join(output_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    docs = client.list_docs(project_id)
    for d in docs:
        fname = d["file_name"]
        content = d.get("content", "")
        with open(os.path.join(docs_dir, fname), "w") as f:
            f.write(content)
        log.append(f"  doc → docs/{fname}")

    # -- Chats --
    chats_dir = os.path.join(output_dir, "chats")
    os.makedirs(chats_dir, exist_ok=True)
    convs = client.list_conversations(project_id, limit=200)
    for c in convs:
        title = c.get("name", c["uuid"]) or c["uuid"]
        fname = f"{_safe_chat_stem(title, c['uuid'])}.md"
        messages = _get_messages(client, c["uuid"])
        with open(os.path.join(chats_dir, fname), "w") as f:
            f.write(_render_chat_markdown(c, messages))
        log.append(f"  chat → chats/{fname}  ({len(messages)} turns)")

    summary = f"Cloned project {project_id} to {output_dir}\n"
    summary += f"  {len(docs)} docs, {len(convs)} chats\n\n"
    return summary + "\n".join(log)


@mcp.tool()
def claude_list_skills() -> str:
    """List all skills from claude.ai/customize/skills.

    Returns id, name, creator_type (user/anthropic), enabled status, and last updated.
    """
    client = _get_client()
    skills = client.list_skills()
    lines = []
    for s in skills:
        creator = s.get("creator_type", "?")
        enabled = "on" if s.get("enabled") else "off"
        updated = s.get("updated_at", "")[:10]
        lines.append(f'{s["id"]}  {s["name"]}  [{creator}] [{enabled}] {updated}')
    return "\n".join(lines) if lines else "No skills found."


@mcp.tool()
def claude_get_skill(skill_id: str) -> str:
    """Download and return the SKILL.md content for a skill from claude.ai.

    Args:
        skill_id: The skill ID (from claude_list_skills).
    """
    client = _get_client()
    zip_bytes = client.download_skill_zip(skill_id)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        skill_files = [n for n in zf.namelist() if n.endswith("SKILL.md")]
        if not skill_files:
            return f"No SKILL.md found in archive. Contents: {zf.namelist()}"
        content = zf.read(skill_files[0]).decode("utf-8")
    return content


@mcp.tool()
def claude_sync_skills(output_dir: str, creator_type: str = "user") -> str:
    """Download skills from claude.ai and write them to a local directory.

    Creates one subdirectory per skill containing SKILL.md.

    Args:
        output_dir: Absolute path to destination directory (created if absent).
        creator_type: Filter by creator — 'user' (default), 'anthropic', or 'all'.
    """
    client = _get_client()
    skills = client.list_skills()

    if creator_type != "all":
        skills = [s for s in skills if s.get("creator_type") == creator_type]

    os.makedirs(output_dir, exist_ok=True)
    log = []
    for s in skills:
        skill_dir = os.path.join(output_dir, s["name"])
        os.makedirs(skill_dir, exist_ok=True)
        try:
            zip_bytes = client.download_skill_zip(s["id"])
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                skill_files = [n for n in zf.namelist() if n.endswith("SKILL.md")]
                if skill_files:
                    content = zf.read(skill_files[0]).decode("utf-8")
                    skill_path = os.path.join(skill_dir, "SKILL.md")
                    with open(skill_path, "w") as f:
                        f.write(content)
                    log.append(f"  {s['name']} → {skill_dir}/SKILL.md")
                else:
                    log.append(f"  {s['name']} — no SKILL.md in archive")
        except Exception as e:
            log.append(f"  {s['name']} — ERROR: {e}")

    return f"Synced {len(log)} skill(s) to {output_dir}\n\n" + "\n".join(log)


if __name__ == "__main__":
    mcp.run()
