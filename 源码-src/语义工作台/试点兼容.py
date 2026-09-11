"""Read-only candidate/evidence inspection; never issues execution authorization."""
import argparse
import json
from collections import deque
from pathlib import Path, PureWindowsPath
import sys
from urllib.parse import quote

KINDS = {'rule', 'entity', 'state', 'decision'}
STATUSES = {'recorded_current', 'candidate', 'production_evidence', 'historical', 'unknown'}
RELATIONS = {'depends_on', 'constrains', 'describes', 'supersedes', 'supported_by'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def string(value, name):
    require(isinstance(value, str) and bool(value.strip()), f'{name}: nonempty string required')


def fields(value, names, name):
    require(isinstance(value, dict), f'{name}: object required')
    require(set(names) <= value.keys(), f'{name}: missing fields {set(names) - value.keys()}')


def unique(value, name):
    require(isinstance(value, list), f'{name}: list required')
    found = set()
    for item in value:
        fields(item, ['id'], name)
        string(item['id'], name + '.id')
        require(item['id'] not in found, f'{name}: duplicate id {item["id"]}')
        found.add(item['id'])
    return found


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_model(path):
    def invalid_constant(value):
        raise ValueError(f'non-JSON number: {value}')
    model = json.loads(Path(path).read_text(encoding='utf-8'),
                       object_pairs_hook=reject_duplicates, parse_constant=invalid_constant)
    json.dumps(model, ensure_ascii=False).encode('utf-8')  # Reject lone surrogate code points.
    fields(model, ['schema', 'project_root', 'status', 'sources', 'nodes', 'relations'], 'model')
    require(model['schema'] == 'agent-rule-pilot/v1', 'unsupported schema')
    require(model['status'] == 'candidate', 'model must remain candidate')
    string(model['project_root'], 'project_root')
    root = Path(model['project_root'])
    require(root.is_absolute() and root.is_dir(), 'project_root must be an existing absolute directory')
    root = root.resolve()
    source_ids = unique(model['sources'], 'sources')
    node_ids = unique(model['nodes'], 'nodes')
    require(source_ids and node_ids, 'sources and nodes must not be empty')
    require(not source_ids & node_ids, 'source and node IDs must be disjoint')
    texts = {}
    for source in model['sources']:
        fields(source, ['id', 'path', 'title', 'snapshot_text'], 'source')
        string(source['path'], 'source.path')
        string(source['title'], 'source.title')
        relative = Path(source['path'])
        windows = PureWindowsPath(source['path'])
        require(not relative.is_absolute() and not windows.drive and not windows.root,
                'source path must be relative')
        resolved = (root / relative).resolve()
        require(resolved.is_relative_to(root), 'source path escapes project_root')
        texts[source['id']] = resolved.read_text(encoding='utf-8')
        require(isinstance(source['snapshot_text'], str), 'snapshot_text must be a string')
        require(texts[source['id']] == source['snapshot_text'], f'source_changed: {source["id"]}')
    for node in model['nodes']:
        fields(node, ['id', 'kind', 'label', 'model_status', 'source_status', 'statement', 'evidence'], 'node')
        require(isinstance(node['kind'], str) and node['kind'] in KINDS, 'invalid node kind')
        require(node['model_status'] == 'candidate', 'node must remain candidate')
        require(isinstance(node['source_status'], str) and node['source_status'] in STATUSES, 'invalid source_status')
        for key in ['label', 'statement']:
            string(node[key], key)
        require(isinstance(node['evidence'], list) and node['evidence'], 'nonempty evidence required')
        for evidence in node['evidence']:
            fields(evidence, ['source_id', 'quote'], 'evidence')
            string(evidence['source_id'], 'evidence.source_id')
            require(evidence['source_id'] in source_ids, 'unresolved evidence source')
            string(evidence['quote'], 'evidence.quote')
            require(evidence['quote'] in texts[evidence['source_id']], f'quote not found for {node["id"]}')
        if 'semantic' in node:
            fields(node['semantic'], ['subject', 'modality', 'action', 'object', 'conditions', 'scope'], 'semantic')
            for key in ['subject', 'modality', 'action', 'scope']:
                string(node['semantic'][key], 'semantic.' + key)
            objects = node['semantic']['object']
            if isinstance(objects, list):
                require(bool(objects), 'semantic.object: nonempty list required')
                for item in objects:
                    string(item, 'semantic.object item')
            else:
                string(objects, 'semantic.object')
    require(isinstance(model['relations'], list), 'relations: list required')
    for rel in model['relations']:
        fields(rel, ['from', 'to', 'type', 'reason'], 'relation')
        for key in ['from', 'to', 'type', 'reason']:
            string(rel[key], 'relation.' + key)
        require(rel['from'] in node_ids and rel['to'] in node_ids, 'unresolved relation endpoint')
        require(rel['type'] in RELATIONS, 'invalid relation type')
    return model


def query(model, node_id, impact=False):
    nodes = {n['id']: n for n in model['nodes']}
    require(node_id in nodes, f'unknown node: {node_id}')
    adjacency = {key: [] for key in nodes}
    for rel in model['relations']:
        if not impact:
            adjacency[rel['from']].append((rel['to'], rel))
            adjacency[rel['to']].append((rel['from'], rel))
        elif rel['type'] in {'depends_on', 'supported_by'}:
            adjacency[rel['to']].append((rel['from'], rel))
        elif rel['type'] == 'constrains':
            adjacency[rel['from']].append((rel['to'], rel))
    paths = {node_id: []}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        for target, rel in adjacency[current]:
            if target not in paths:
                paths[target] = paths[current] + [rel]
                queue.append(target)
    selected = [nodes[key] for key in paths]
    used_sources = {e['source_id'] for n in selected for e in n['evidence']}
    return {
        'mode': 'source_evidence_only', 'executable_authorization': False,
        'model_status': 'candidate', 'query': 'impact' if impact else 'context', 'target': node_id,
        'scope_note': ('Explicit dependency paths only; not automatic invalidation or proof of breakage.'
                       if impact else 'Conservative bidirectional closure; historical/superseded evidence is not current authorization.'),
        'nodes': selected,
        'sources': [{key: s[key] for key in ['id', 'path', 'title']} for s in model['sources'] if s['id'] in used_sources],
        'relations': [r for r in model['relations'] if r['from'] in paths and r['to'] in paths],
        'pending_review': [{'node_id': key, 'path': path} for key, path in paths.items() if key != node_id] if impact else [],
    }


def export_turtle(model):
    def iri(kind, identifier):
        return '<urn:workbench:jiaoben:' + kind + ':' + quote(identifier, safe='') + '>'
    def literal(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        # JSON control/quote escaping is valid Turtle; preserve non-BMP Unicode as text.
        return json.dumps(text, ensure_ascii=False)
    node_ids = {node['id'] for node in model['nodes']}
    lines = ['@prefix wb: <urn:workbench:vocab:> .',
             '@prefix skos: <http://www.w3.org/2004/02/skos/core#> .',
             '<urn:workbench:jiaoben:model> wb:status "candidate" ; wb:executableAuthorization false .']
    for source in model['sources']:
        subject = iri('source', source['id'])
        for key in ['id', 'path', 'title', 'snapshot_text']:
            lines.append(f'{subject} wb:{key} {literal(source[key])} .')
    for node_index, node in enumerate(model['nodes']):
        subject = iri('node', node['id'])
        lines.append(f'{subject} a skos:Concept ; skos:prefLabel {literal(node["label"])}@zh .')
        for key in ['id', 'kind', 'label', 'model_status', 'source_status', 'statement', 'semantic', 'attributes']:
            if key in node:
                lines.append(f'{subject} wb:{key} {literal(node[key])} .')
        if 'semantic' in node:
            for key in ['subject', 'modality', 'action', 'object', 'scope']:
                values = node['semantic'][key]
                for value in values if isinstance(values, list) else [values]:
                    target = iri('node', value) if value in node_ids else literal(value)
                    lines.append(f'{subject} wb:{key} {target} .')
            lines.append(f'{subject} wb:conditions {literal(node["semantic"]["conditions"])} .')
        for evidence_index, evidence in enumerate(node['evidence']):
            evidence_id = f'_:e{node_index}_{evidence_index}'
            lines.extend([f'{subject} wb:evidence {evidence_id} .',
                          f'{evidence_id} wb:source {iri("source", evidence["source_id"])} .',
                          f'{evidence_id} wb:quote {literal(evidence["quote"])} .'])
    for relation_index, rel in enumerate(model['relations']):
        subject = f'_:r{relation_index}'
        lines.extend([f'{iri("node", rel["from"])} wb:{rel["type"]} {iri("node", rel["to"])} .',
                      f'{subject} wb:from {iri("node", rel["from"])} ; wb:to {iri("node", rel["to"])} ; wb:type {literal(rel["type"])} ; wb:reason {literal(rel["reason"])} .'])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=Path(__file__).with_name('model.json'))
    parser.add_argument('command', choices=['validate', 'context', 'impact', 'export-turtle'])
    parser.add_argument('node', nargs='?')
    args = parser.parse_args(argv)
    try:
        require((args.command in {'context', 'impact'}) == (args.node is not None), 'node required only for context/impact')
        model = load_model(args.model)
        if args.command == 'export-turtle':
            print(export_turtle(model), end='')
            return 0
        result = ({'valid': True, 'status': 'candidate', 'executable_authorization': False,
                   'nodes': len(model['nodes']), 'sources': len(model['sources']),
                   'semantic_equivalence_verified': False} if args.command == 'validate'
                  else query(model, args.node, args.command == 'impact'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, RecursionError) as exc:
        print(json.dumps({'valid': False, 'error': str(exc), 'executable_authorization': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
