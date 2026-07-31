#!/usr/bin/env python3
"""One-time converter: schema.txt → schema.json (DataSchema + subclasses format).

The output JSON is consumed by KBSource.import_database_schema for the DataSchema
portion (entities / relations) and by _seed_schema for the subclasses list.

Usage:
    python tools/convert_schema.py \
        lib/src/blue_data_user_source/data/schema.txt \
        lib/src/blue_data_user_source/data/schema.json
"""

import json
import re
import sys
from pathlib import Path


def parse_schema_txt(text: str) -> dict:
    """Parse schema.txt Cypher-like notation into an intermediate dict."""
    example_start = text.find("# EXAMPLE GRAPH USING SCHEMA")
    if example_start != -1:
        text = text[:example_start]

    nodes: dict[str, dict] = {}
    name_to_var: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []

    def _props(s: str) -> dict:
        result: dict = {}
        for m in re.finditer(r"(\w+):\s*'([^']*)'", s):
            result[m.group(1)] = m.group(2)
        for m in re.finditer(r"(\w+):\s*(true|false)\b", s):
            result[m.group(1)] = m.group(2) == "true"
        return result

    def _register(var: str, label: str, props_str: str) -> None:
        if var in nodes:
            return
        props = _props(props_str)
        name = props.get("name", var.upper())
        data: dict = {"label": label, "name": name, "description": props.get("description", "")}
        if label == "RELATION":
            data["is_symmetric"] = props.get("is_symmetric", False)
        nodes[var] = data
        name_to_var[name] = var

    for m in re.finditer(r'\((\w+):(CLASS|RELATION|PROPERTY)\s*\{([^}]+)\}\)', text):
        _register(m.group(1), m.group(2), m.group(3))
    for m in re.finditer(r'\((\w+):(CLASS|RELATION|PROPERTY)\)\s*\{([^}]+)\}', text):
        _register(m.group(1), m.group(2), m.group(3))

    edge_rx = r'\((\w+)\)-\[:(IS_SUBCLASS_OF|DEFINE_PROPERTY|DOMAIN|RANGE)\]->\((\w+)\)'
    for m in re.finditer(edge_rx, text):
        edges.append((m.group(1), m.group(2), m.group(3)))

    return {"nodes": nodes, "name_to_var": name_to_var, "edges": edges}


def convert(schema_txt: str) -> dict:
    """Convert schema.txt content to an extended DataSchema dict.

    The returned dict has three keys:
    - "entities"   — DataSchema entity definitions (CLASS nodes)
    - "relations"  — DataSchema relation definitions (RELATION nodes with DOMAIN/RANGE)
    - "subclasses" — list of {child, parent} name pairs for IS_SUBCLASS_OF edges,
                     handled separately after import_database_schema because
                     IS_SUBCLASS_OF is a structural graph edge, not a RELATION node.
    """
    from blue_data.core.schema import DataSchema

    parsed = parse_schema_txt(schema_txt)
    nodes = parsed["nodes"]
    edges = parsed["edges"]

    outgoing: dict[str, list[tuple[str, str]]] = {}
    incoming: dict[str, list[tuple[str, str]]] = {}
    for from_var, etype, to_var in edges:
        outgoing.setdefault(from_var, []).append((etype, to_var))
        incoming.setdefault(to_var, []).append((etype, from_var))

    schema = DataSchema()

    # CLASS nodes → entities
    for var, data in nodes.items():
        if data["label"] == "CLASS":
            schema.add_entity(data["name"], description=data["description"])

    # RELATION nodes → relations (DOMAIN=source, RANGE=target)
    rel_var_to_key: dict[str, str] = {}
    for var, data in nodes.items():
        if data["label"] != "RELATION":
            continue
        domains = [
            nodes[to]["name"]
            for etype, to in outgoing.get(var, [])
            if etype == "DOMAIN" and to in nodes
        ]
        ranges = [
            nodes[to]["name"]
            for etype, to in outgoing.get(var, [])
            if etype == "RANGE" and to in nodes
        ]
        source = domains[0] if domains else "*"
        target = ranges[0] if ranges else "*"
        rel_key = schema.add_relation(
            source, data["name"], target, description=data["description"]
        )
        rel_var_to_key[var] = rel_key

    # PROPERTY nodes → attributes on owning CLASS or RELATION
    for var, data in nodes.items():
        if data["label"] != "PROPERTY":
            continue
        for etype, owner_var in incoming.get(var, []):
            if etype != "DEFINE_PROPERTY":
                continue
            owner = nodes.get(owner_var)
            if owner is None:
                continue
            if owner["label"] == "CLASS":
                schema.add_entity_attribute(
                    owner["name"], data["name"], "str", description=data["description"]
                )
            elif owner["label"] == "RELATION":
                rel_key = rel_var_to_key.get(owner_var)
                if rel_key:
                    schema.add_relation_attribute(
                        rel_key, data["name"], "str", description=data["description"]
                    )

    # IS_SUBCLASS_OF pairs — separate from DataSchema (structural edges, not RELATION nodes).
    # child_label / parent_label are included so _seed_schema can skip PROPERTY→PROPERTY pairs
    # (KBSource.add_is_subclass_of only accepts CLASS or RELATION nodes).
    subclasses = []
    for from_var, etype, to_var in edges:
        if etype != "IS_SUBCLASS_OF":
            continue
        child_data = nodes.get(from_var)
        parent_data = nodes.get(to_var)
        if child_data and parent_data:
            subclasses.append({
                "child": child_data["name"],
                "child_label": child_data["label"],
                "parent": parent_data["name"],
                "parent_label": parent_data["label"],
            })

    result = schema.to_json()
    result["subclasses"] = subclasses
    return result


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <schema.txt> <schema.json>", file=sys.stderr)
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)

    schema_dict = convert(src.read_text())
    dst.write_text(json.dumps(schema_dict, indent=2))

    n_ent = len(schema_dict["entities"])
    n_rel = len(schema_dict["relations"])
    n_sub = len(schema_dict.get("subclasses", []))
    print(f"Wrote {dst}")
    print(f"  {n_ent} entity types (CLASS)")
    print(f"  {n_rel} relation types (RELATION)")
    print(f"  {n_sub} IS_SUBCLASS_OF entries")


if __name__ == "__main__":
    main()
