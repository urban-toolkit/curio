import time
import uuid

from flask import request
from flask_socketio import join_room, leave_room, emit
from utk_curio.backend.extensions import socketio

# {room: {nodeId: {userId, color}}}
_locked_nodes: dict = {}

# {room: {userId: {color, sid}}}
_room_users: dict = {}

# {room: {nodes: {id: node}, edges: {id: edge}}}  — live graph state
_room_graph: dict = {}

# {room: {nodeId: output_value}}  — execution outputs per node
_room_outputs: dict = {}

# {room: {nodes: {nodeId: revision}, edges: {edgeId: revision}}}
_room_versions: dict = {}

# {room: {nodes: {nodeId: {updatedBy, updatedAt}}, edges: {...}}}
_room_meta: dict = {}

# {room: {nodes: {nodeId: tombstone}, edges: {edgeId: tombstone}}}
_room_tombstones: dict = {}

# {room: [activity, ...]}
_room_activity: dict = {}

# {room: {proposalId: proposal}} - pending shared-code changes awaiting approval
_room_code_proposals: dict = {}

_ACTIVITY_LIMIT = 50

_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12',
    '#9b59b6', '#1abc9c', '#e67e22', '#16a085',
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _assign_color(room: str, user_id: str) -> str:
    users = _room_users.get(room, {})
    keys = list(users.keys())
    if user_id in keys:
        return users[user_id]['color']
    return _COLORS[len(keys) % len(_COLORS)]


def _display_name(data: dict, user_id: str) -> str:
    raw = (data.get('userName') or '').strip()
    if raw:
        return raw[:40]
    return f'User {str(user_id)[:6]}'


def _user_payload(room: str, user_id: str, fallback_name: str | None = None) -> dict:
    info = _room_users.get(room, {}).get(user_id, {})
    return {
        'userId': user_id,
        'name': info.get('name') or fallback_name or f'User {str(user_id)[:6]}',
        'color': info.get('color') or '#3498db',
    }


def _version_bucket(room: str, kind: str) -> dict:
    return _room_versions.setdefault(room, {'nodes': {}, 'edges': {}})[kind]


def _meta_bucket(room: str, kind: str) -> dict:
    return _room_meta.setdefault(room, {'nodes': {}, 'edges': {}})[kind]


def _tombstone_bucket(room: str, kind: str) -> dict:
    return _room_tombstones.setdefault(room, {'nodes': {}, 'edges': {}})[kind]


def _current_revision(room: str, kind: str, entity_id: str) -> int:
    return int(_version_bucket(room, kind).get(entity_id, 0))


def _bump_revision(room: str, kind: str, entity_id: str, user_id: str) -> int:
    versions = _version_bucket(room, kind)
    revision = int(versions.get(entity_id, 0)) + 1
    versions[entity_id] = revision
    _meta_bucket(room, kind)[entity_id] = {
        'updatedBy': user_id,
        'updatedAt': _now_ms(),
    }
    return revision


def _has_conflicting_revision(room: str, kind: str, entity_id: str, base_revision: int, user_id: str) -> bool:
    current_revision = _current_revision(room, kind, entity_id)
    meta = _meta_bucket(room, kind).get(entity_id, {})
    updated_by = meta.get('updatedBy')
    return current_revision > base_revision and updated_by is not None and updated_by != user_id


def _downstream_nodes(room: str, start_ids: list[str]) -> list[str]:
    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    seen: set[str] = set()
    queue = list(start_ids)
    edges = list(graph.get('edges', {}).values())

    while queue:
        current = queue.pop(0)
        for edge in edges:
            if edge.get('source') != current:
                continue
            target = edge.get('target')
            if target and target not in seen:
                seen.add(target)
                queue.append(target)

    return list(seen)


def _edge_feeds_existing_work(room: str, edge: dict | None) -> bool:
    if not edge:
        return False

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    target_id = edge.get('target')
    source_id = edge.get('source')
    target = graph.get('nodes', {}).get(target_id, {})
    target_data = target.get('data', {}) if isinstance(target, dict) else {}
    source_value = target_data.get('source')

    if source_value == source_id:
        return True
    if isinstance(source_value, list) and source_id in source_value:
        return True
    if target_id in _room_outputs.get(room, {}):
        return True

    return False


def _record_activity(room: str, kind: str, user_id: str, label: str, entity_id: str | None = None, details: dict | None = None) -> dict:
    activity = {
        'id': str(uuid.uuid4()),
        'kind': kind,
        'label': label,
        'entityId': entity_id,
        'details': details or {},
        'timestamp': _now_ms(),
        'user': _user_payload(room, user_id),
    }
    activities = _room_activity.setdefault(room, [])
    activities.insert(0, activity)
    del activities[_ACTIVITY_LIMIT:]
    emit('activity_recorded', activity, to=room)
    return activity


def _make_conflict(room: str, conflict_type: str, user_id: str, message: str, entity_id: str | None = None, **extra) -> dict:
    conflict = {
        'conflictId': str(uuid.uuid4()),
        'type': conflict_type,
        'message': message,
        'entityId': entity_id,
        'timestamp': _now_ms(),
        'actor': _user_payload(room, user_id),
    }
    conflict.update(extra)
    emit('conflict_detected', conflict, to=room)
    _record_activity(room, 'conflict_detected', user_id, message, entity_id, {'type': conflict_type})
    return conflict


def _node_code_snapshot(node: dict | None) -> dict:
    data = node.get('data', {}) if isinstance(node, dict) else {}
    if not isinstance(data, dict):
        data = {}
    effective_code = data.get('code')
    if effective_code in (None, ''):
        effective_code = data.get('defaultCode') or data.get('content')
    return {
        'effectiveCode': effective_code,
        'defaultCode': data.get('defaultCode'),
        'content': data.get('content'),
    }


def _node_code_changed(current_node: dict | None, incoming_node: dict | None) -> bool:
    if not incoming_node:
        return False
    return _node_code_snapshot(current_node) != _node_code_snapshot(incoming_node)


def _output_display(output: dict | None) -> dict:
    if isinstance(output, dict) and output.get('path'):
        return {
            'code': 'success',
            'content': f"Shared output available.\nSaved to file: {output.get('path')}\nType: {output.get('dataType') or 'unknown'}",
            'outputType': output.get('dataType') or '',
        }
    if output:
        return {
            'code': 'success',
            'content': 'Shared output available.',
            'outputType': '',
        }
    return {
        'code': '',
        'content': 'No output available.',
        'outputType': '',
    }


def _pending_code_proposals(room: str) -> dict:
    return _room_code_proposals.setdefault(room, {})


def _proposal_payload(proposal: dict) -> dict:
    return {
        'proposalId': proposal['proposalId'],
        'nodeId': proposal['nodeId'],
        'node': proposal['node'],
        'currentNode': proposal.get('currentNode'),
        'proposedBy': proposal['proposedBy'],
        'requiredUserIds': proposal.get('requiredUserIds', []),
        'approvals': proposal.get('approvals', {}),
        'comments': proposal.get('comments', {}),
        'changeSummary': proposal.get('changeSummary', []),
        'timestamp': proposal.get('timestamp'),
        'status': proposal.get('status', 'pending'),
    }


def _find_pending_code_proposal(room: str, node_id: str, proposed_by: str | None = None) -> dict | None:
    for proposal in _pending_code_proposals(room).values():
        if proposal.get('status') != 'pending':
            continue
        if proposal.get('nodeId') != node_id:
            continue
        if proposed_by is not None and proposal.get('proposedBy', {}).get('userId') != proposed_by:
            continue
        return proposal
    return None


def _has_pending_code_proposal(room: str, node_id: str) -> bool:
    return _find_pending_code_proposal(room, node_id) is not None


def _apply_code_proposal(room: str, proposal_id: str, applied_by: str) -> bool:
    proposal = _pending_code_proposals(room).get(proposal_id)
    if not proposal or proposal.get('status') != 'pending':
        return False

    required = proposal.get('requiredUserIds', [])
    approvals = proposal.get('approvals', {})
    missing = [uid for uid in required if uid not in approvals]
    if missing:
        return False

    node = proposal.get('node') or {}
    node_id = proposal.get('nodeId')
    if not node_id:
        return False

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    graph['nodes'][node_id] = node
    _tombstone_bucket(room, 'nodes').pop(node_id, None)
    revision = _bump_revision(room, 'nodes', node_id, proposal.get('proposedBy', {}).get('userId') or applied_by)

    payload = {
        'sessionId': room,
        'userId': proposal.get('proposedBy', {}).get('userId'),
        'node': node,
        'revision': revision,
        'user': proposal.get('proposedBy'),
        'changeSummary': proposal.get('changeSummary', []),
        'proposalId': proposal_id,
    }
    emit('node_updated', payload, to=room, include_self=True)

    proposal['status'] = 'applied'
    applied_payload = {
        **_proposal_payload(proposal),
        'revision': revision,
        'approvedBy': _user_payload(room, applied_by),
    }
    emit('code_change_applied', applied_payload, to=room)
    _pending_code_proposals(room).pop(proposal_id, None)

    _record_activity(
        room,
        'code_change_applied',
        applied_by,
        f"Applied approved code change for node {node_id[:6]}",
        node_id,
        {'proposalId': proposal_id},
    )

    # First-accept-wins: any other pending proposals on the same node are
    # now based on stale code. Cancel them so they don't overwrite this
    # accepted change if approved later.
    proposals_dict = _pending_code_proposals(room)
    for other_id, other in list(proposals_dict.items()):
        if other.get('nodeId') != node_id:
            continue
        if other.get('status') != 'pending':
            continue
        other['status'] = 'superseded'
        emit('code_change_rejected', _proposal_payload(other), to=room)
        proposals_dict.pop(other_id, None)
        _record_activity(
            room,
            'code_change_superseded',
            applied_by,
            f"Cancelled obsolete proposal for node {node_id[:6]} (another change accepted first)",
            node_id,
            {'proposalId': other_id, 'reason': 'first_accept_wins'},
        )

    return True


def _request_code_change(room: str, user_id: str, node: dict, change_summary: list | None = None) -> dict:
    node_id = node.get('id')
    proposer = _user_payload(room, user_id)
    proposal = _find_pending_code_proposal(room, node_id, user_id)
    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})

    if proposal:
        proposal['node'] = node
        proposal['currentNode'] = graph.get('nodes', {}).get(node_id)
        proposal['changeSummary'] = change_summary or []
        proposal['timestamp'] = _now_ms()
        proposal['approvals'] = {user_id: {'user': proposer, 'timestamp': _now_ms()}}
        proposal['comments'] = {}
    else:
        required = [uid for uid in _room_users.get(room, {}) if uid != user_id]
        proposal = {
            'proposalId': str(uuid.uuid4()),
            'nodeId': node_id,
            'node': node,
            'currentNode': graph.get('nodes', {}).get(node_id),
            'proposedBy': proposer,
            'requiredUserIds': required,
            'approvals': {user_id: {'user': proposer, 'timestamp': _now_ms()}},
            'comments': {},
            'changeSummary': change_summary or [],
            'timestamp': _now_ms(),
            'status': 'pending',
        }
        _pending_code_proposals(room)[proposal['proposalId']] = proposal

    emit('code_change_requested', _proposal_payload(proposal), to=room)
    _record_activity(
        room,
        'code_change_requested',
        user_id,
        f"Requested code change approval for node {node_id[:6]}",
        node_id,
        {'proposalId': proposal['proposalId']},
    )

    _apply_code_proposal(room, proposal['proposalId'], user_id)
    return proposal


def _cleanup_user(room: str, user_id: str) -> None:
    """Remove user from room state and release their node locks."""
    user = _user_payload(room, user_id)

    if room in _room_users and user_id in _room_users[room]:
        del _room_users[room][user_id]

    if room in _locked_nodes:
        unlocked = [
            nid for nid, info in _locked_nodes[room].items()
            if info.get('userId') == user_id
        ]
        for nid in unlocked:
            del _locked_nodes[room][nid]
            emit('node_unlocked', {'nodeId': nid}, to=room)

    for proposal_id, proposal in list(_pending_code_proposals(room).items()):
        required = proposal.get('requiredUserIds', [])
        if user_id in required:
            proposal['requiredUserIds'] = [uid for uid in required if uid != user_id]
            emit('code_change_requested', _proposal_payload(proposal), to=room)
            _apply_code_proposal(room, proposal_id, user_id)

    emit('user_left', user, to=room)
    _record_activity(room, 'user_left', user_id, f"{user['name']} left the session")


# ── Session lifecycle ────────────────────────────────────────────────────────

@socketio.on('join_session')
def on_join(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    user_name = _display_name(data, user_id)
    color = _assign_color(room, user_id)

    join_room(room)

    _room_users.setdefault(room, {})[user_id] = {
        'color': color,
        'sid': request.sid,
        'name': user_name,
    }
    _locked_nodes.setdefault(room, {})
    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    _room_versions.setdefault(room, {'nodes': {}, 'edges': {}})
    _room_meta.setdefault(room, {'nodes': {}, 'edges': {}})
    _room_tombstones.setdefault(room, {'nodes': {}, 'edges': {}})

    # Send full current state to the joining client
    emit('session_state', {
        'color': color,
        'name': user_name,
        'lockedNodes': _locked_nodes[room],
        'connectedUsers': [
            {'userId': uid, 'color': info['color'], 'name': info.get('name') or f'User {uid[:6]}'}
            for uid, info in _room_users[room].items()
            if uid != user_id
        ],
        'nodes': list(graph['nodes'].values()),
        'edges': list(graph['edges'].values()),
        'outputs': _room_outputs.get(room, {}),
        'nodeRevisions': _room_versions[room]['nodes'],
        'edgeRevisions': _room_versions[room]['edges'],
        'activityLog': _room_activity.get(room, []),
        'codeChangeProposals': [
            _proposal_payload(proposal)
            for proposal in _pending_code_proposals(room).values()
            if proposal.get('status') == 'pending'
        ],
    })

    # Tell everyone else a new user arrived
    emit('user_joined', {'userId': user_id, 'color': color, 'name': user_name}, to=room, include_self=False)
    _record_activity(room, 'user_joined', user_id, f'{user_name} joined the session')


@socketio.on('set_user_profile')
def on_set_user_profile(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    user_name = _display_name(data, user_id)

    if room in _room_users and user_id in _room_users[room]:
        _room_users[room][user_id]['name'] = user_name
        payload = _user_payload(room, user_id)
        emit('user_updated', payload, to=room)
        _record_activity(room, 'user_updated', user_id, f'{user_name} updated their profile')


@socketio.on('leave_session')
def on_leave(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId')
    leave_room(room)
    _cleanup_user(room, user_id)


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for room, users in list(_room_users.items()):
        for user_id, info in list(users.items()):
            if info.get('sid') == sid:
                _cleanup_user(room, user_id)
                return


# ── Graph change events (store + relay to room, skip sender) ─────────────────

@socketio.on('node_added')
def on_node_added(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    node = data.get('node', {})
    if node.get('id'):
        _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})['nodes'][node['id']] = node
        _tombstone_bucket(room, 'nodes').pop(node['id'], None)
        revision = _bump_revision(room, 'nodes', node['id'], user_id)
        payload = {**data, 'revision': revision, 'user': _user_payload(room, user_id)}
        emit('node_added', payload, to=room, include_self=False)
        emit('state_ack', {'entity': 'node', 'id': node['id'], 'revision': revision, 'action': 'added'})
        _record_activity(room, 'node_added', user_id, f"Added node {node['id'][:6]}", node['id'])


@socketio.on('node_updated')
def on_node_updated(data):
    """Sync node data changes (e.g. execution output, code edits)."""
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    node = data.get('node', {})
    node_id = node.get('id')
    if not node_id:
        return

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    force = data.get('force') is True
    base_revision = int(data.get('baseRevision') or 0)
    tombstone = _tombstone_bucket(room, 'nodes').get(node_id)

    if tombstone and node_id not in graph['nodes'] and not force:
        _make_conflict(
            room,
            'node_deleted',
            user_id,
            f"Node {node_id[:6]} was deleted before this edit could be saved",
            node_id,
            nodeId=node_id,
            operation='node_updated',
            baseRevision=base_revision,
            serverRevision=_current_revision(room, 'nodes', node_id),
            incomingNode=node,
            currentNode=None,
            deletedBy=_user_payload(room, tombstone.get('deletedBy')),
            changeSummary=data.get('changeSummary') or [],
        )
        return

    if not force and _has_conflicting_revision(room, 'nodes', node_id, base_revision, user_id):
        meta = _meta_bucket(room, 'nodes').get(node_id, {})
        _make_conflict(
            room,
            'node_edit',
            user_id,
            f"Node {node_id[:6]} changed since this user started editing",
            node_id,
            nodeId=node_id,
            operation='node_updated',
            baseRevision=base_revision,
            serverRevision=_current_revision(room, 'nodes', node_id),
            incomingNode=node,
            currentNode=graph['nodes'].get(node_id),
            currentOwner=_user_payload(room, meta.get('updatedBy')),
            affectedNodeIds=_downstream_nodes(room, [node_id]),
            changeSummary=data.get('changeSummary') or [],
        )
        return

    if not force and _node_code_changed(graph['nodes'].get(node_id), node):
        _request_code_change(room, user_id, node, data.get('changeSummary') or [])
        return

    graph['nodes'][node_id] = node
    _tombstone_bucket(room, 'nodes').pop(node_id, None)
    revision = _bump_revision(room, 'nodes', node_id, user_id)
    payload = {**data, 'revision': revision, 'user': _user_payload(room, user_id)}
    emit('node_updated', payload, to=room, include_self=force)
    emit('state_ack', {'entity': 'node', 'id': node_id, 'revision': revision, 'action': 'updated'})
    _record_activity(
        room,
        'node_updated',
        user_id,
        f"Updated node {node_id[:6]}",
        node_id,
        {'changeSummary': data.get('changeSummary') or []},
    )


@socketio.on('request_code_change')
def on_request_code_change(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    node = data.get('node', {})
    node_id = node.get('id')
    if not node_id:
        return

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    current_node = graph['nodes'].get(node_id)
    if not _node_code_changed(current_node, node):
        return

    _request_code_change(room, user_id, node, data.get('changeSummary') or ['code'])


@socketio.on('node_removed')
def on_node_removed(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    node_id = data.get('nodeId')
    if not node_id:
        return

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    force = data.get('force') is True
    base_revision = int(data.get('baseRevision') or 0)
    lock = _locked_nodes.get(room, {}).get(node_id)

    if lock and lock.get('userId') != user_id and not force:
        _make_conflict(
            room,
            'node_delete',
            user_id,
            f"Node {node_id[:6]} is being edited by {lock.get('name') or lock.get('userId', '')[:6]}",
            node_id,
            nodeId=node_id,
            operation='node_removed',
            baseRevision=base_revision,
            serverRevision=_current_revision(room, 'nodes', node_id),
            currentNode=graph['nodes'].get(node_id),
            lockedBy=lock,
            affectedNodeIds=_downstream_nodes(room, [node_id]),
        )
        return

    if not force and _has_conflicting_revision(room, 'nodes', node_id, base_revision, user_id):
        meta = _meta_bucket(room, 'nodes').get(node_id, {})
        _make_conflict(
            room,
            'node_delete',
            user_id,
            f"Node {node_id[:6]} changed before it could be deleted",
            node_id,
            nodeId=node_id,
            operation='node_removed',
            baseRevision=base_revision,
            serverRevision=_current_revision(room, 'nodes', node_id),
            currentNode=graph['nodes'].get(node_id),
            currentOwner=_user_payload(room, meta.get('updatedBy')),
            affectedNodeIds=_downstream_nodes(room, [node_id]),
        )
        return

    removed = graph['nodes'].pop(node_id, None)
    if removed:
        _tombstone_bucket(room, 'nodes')[node_id] = {
            'node': removed,
            'deletedBy': user_id,
            'deletedAt': _now_ms(),
        }
    revision = _bump_revision(room, 'nodes', node_id, user_id)
    if node_id:
        _room_outputs.get(room, {}).pop(node_id, None)
    payload = {**data, 'revision': revision, 'user': _user_payload(room, user_id)}
    emit('node_removed', payload, to=room, include_self=force)
    emit('state_ack', {'entity': 'node', 'id': node_id, 'revision': revision, 'action': 'removed'})
    _record_activity(room, 'node_removed', user_id, f"Deleted node {node_id[:6]}", node_id)


@socketio.on('edge_added')
def on_edge_added(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    edge = data.get('edge', {})
    edge_id = edge.get('id')
    if not edge_id:
        return

    force = data.get('force') is True
    target_id = edge.get('target')
    lock = _locked_nodes.get(room, {}).get(target_id)
    if lock and lock.get('userId') != user_id and not force:
        _make_conflict(
            room,
            'edge_dependency',
            user_id,
            f"Connection changes input for node {str(target_id)[:6]} while it is being edited",
            edge_id,
            edgeId=edge_id,
            nodeId=target_id,
            operation='edge_added',
            incomingEdge=edge,
            lockedBy=lock,
            affectedNodeIds=_downstream_nodes(room, [target_id]),
        )
        return

    _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})['edges'][edge_id] = edge
    _tombstone_bucket(room, 'edges').pop(edge_id, None)
    revision = _bump_revision(room, 'edges', edge_id, user_id)
    payload = {**data, 'revision': revision, 'user': _user_payload(room, user_id)}
    emit('edge_added', payload, to=room, include_self=force)
    emit('state_ack', {'entity': 'edge', 'id': edge_id, 'revision': revision, 'action': 'added'})
    _record_activity(room, 'edge_added', user_id, f"Connected edge {edge_id[:6]}", edge_id)


@socketio.on('edge_removed')
def on_edge_removed(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    edge_id = data.get('edgeId')
    if not edge_id:
        return

    graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
    force = data.get('force') is True
    base_revision = int(data.get('baseRevision') or 0)
    current_edge = graph['edges'].get(edge_id)
    tombstone = _tombstone_bucket(room, 'edges').get(edge_id)

    if tombstone and current_edge is None and not force:
        _make_conflict(
            room,
            'edge_deleted',
            user_id,
            f"Edge {edge_id[:6]} was already deleted",
            edge_id,
            edgeId=edge_id,
            operation='edge_removed',
            deletedBy=_user_payload(room, tombstone.get('deletedBy')),
        )
        return

    target_id = current_edge.get('target') if current_edge else data.get('target')
    lock = _locked_nodes.get(room, {}).get(target_id)
    changes_dependency = _edge_feeds_existing_work(room, current_edge)

    if not force and (changes_dependency or (lock and lock.get('userId') != user_id)):
        _make_conflict(
            room,
            'edge_dependency',
            user_id,
            f"Removing edge {edge_id[:6]} affects downstream node {str(target_id)[:6]}",
            edge_id,
            edgeId=edge_id,
            nodeId=target_id,
            operation='edge_removed',
            baseRevision=base_revision,
            serverRevision=_current_revision(room, 'edges', edge_id),
            currentEdge=current_edge,
            lockedBy=lock,
            affectedNodeIds=[target_id] + _downstream_nodes(room, [target_id]) if target_id else [],
        )
        return

    removed = graph['edges'].pop(edge_id, None)
    if removed:
        _tombstone_bucket(room, 'edges')[edge_id] = {
            'edge': removed,
            'deletedBy': user_id,
            'deletedAt': _now_ms(),
        }
    revision = _bump_revision(room, 'edges', edge_id, user_id)
    payload = {**data, 'revision': revision, 'user': _user_payload(room, user_id)}
    emit('edge_removed', payload, to=room, include_self=force)
    emit('state_ack', {'entity': 'edge', 'id': edge_id, 'revision': revision, 'action': 'removed'})
    _record_activity(room, 'edge_removed', user_id, f"Removed edge {edge_id[:6]}", edge_id)


# ── Output sync ──────────────────────────────────────────────────────────────

@socketio.on('output_produced')
def on_output_produced(data):
    """Sync execution outputs so all browsers can propagate data on new connections."""
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    node_id = data.get('nodeId')
    output = data.get('output')
    if node_id:
        if _has_pending_code_proposal(room, node_id):
            _record_activity(
                room,
                'output_blocked',
                user_id,
                f"Blocked output for node {node_id[:6]} until code change is approved",
                node_id,
            )
            return
        _room_outputs.setdefault(room, {})[node_id] = output
        graph = _room_graph.setdefault(room, {'nodes': {}, 'edges': {}})
        if node_id in graph['nodes']:
            node_data = graph['nodes'][node_id].setdefault('data', {})
            if isinstance(node_data, dict):
                node_data['output'] = _output_display(output)
                node_data['lastOutput'] = output
                if isinstance(output, dict):
                    node_data['outputRef'] = output.get('path')
                    node_data['outputDataType'] = output.get('dataType')
        _record_activity(room, 'output_produced', user_id, f"Produced output for node {node_id[:6]}", node_id)
    emit('output_produced', {**data, 'user': _user_payload(room, user_id)}, to=room, include_self=False)


@socketio.on('node_exec_display')
def on_node_exec_display(data):
    """Broadcast execution display state (running/success/error) to collaborators."""
    room = data.get('sessionId', 'default')
    emit('node_exec_display', data, to=room, include_self=False)


@socketio.on('approve_code_change')
def on_approve_code_change(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    proposal_id = data.get('proposalId')
    proposal = _pending_code_proposals(room).get(proposal_id)
    if not proposal or proposal.get('status') != 'pending':
        return

    proposal.setdefault('approvals', {})[user_id] = {
        'user': _user_payload(room, user_id),
        'timestamp': _now_ms(),
    }
    proposal.setdefault('comments', {}).pop(user_id, None)
    emit('code_change_approved', _proposal_payload(proposal), to=room)
    _record_activity(
        room,
        'code_change_approved',
        user_id,
        f"Approved code change for node {proposal.get('nodeId', '')[:6]}",
        proposal.get('nodeId'),
        {'proposalId': proposal_id},
    )
    _apply_code_proposal(room, proposal_id, user_id)


@socketio.on('reject_code_change')
def on_reject_code_change(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    proposal_id = data.get('proposalId')
    comment = (data.get('comment') or '').strip()[:500]
    proposal = _pending_code_proposals(room).get(proposal_id)
    if not proposal or proposal.get('status') != 'pending':
        return

    proposal.setdefault('approvals', {}).pop(user_id, None)
    proposal.setdefault('comments', {})[user_id] = {
        'user': _user_payload(room, user_id),
        'comment': comment,
        'timestamp': _now_ms(),
    }
    emit('code_change_rejected', _proposal_payload(proposal), to=room)
    _record_activity(
        room,
        'code_change_rejected',
        user_id,
        f"Commented on code change for node {proposal.get('nodeId', '')[:6]}",
        proposal.get('nodeId'),
        {'proposalId': proposal_id, 'comment': comment},
    )


# ── Node lock / conflict detection ──────────────────────────────────────────

@socketio.on('node_lock')
def on_node_lock(data):
    room = data.get('sessionId', 'default')
    node_id = data.get('nodeId')
    user_id = data.get('userId') or request.sid
    user = _user_payload(room, user_id)
    color = user['color']

    locks = _locked_nodes.setdefault(room, {})
    existing = locks.get(node_id)

    if existing and existing['userId'] != user_id:
        # Two users on the same node → conflict
        _make_conflict(
            room,
            'node_lock',
            user_id,
            f"Node {str(node_id)[:6]} is already being edited",
            node_id,
            nodeId=node_id,
            operation='node_lock',
            lockedBy=existing,
            requestedBy={**user, 'color': color},
        )
        return

    locks[node_id] = {'userId': user_id, 'color': color, 'name': user['name']}
    emit('node_locked', {'nodeId': node_id, 'userId': user_id, 'color': color, 'name': user['name']},
         to=room, include_self=False)


@socketio.on('node_unlock')
def on_node_unlock(data):
    room = data.get('sessionId', 'default')
    node_id = data.get('nodeId')
    user_id = data.get('userId') or request.sid

    locks = _locked_nodes.get(room, {})
    if locks.get(node_id, {}).get('userId') == user_id:
        del locks[node_id]
        emit('node_unlocked', {'nodeId': node_id}, to=room, include_self=False)


@socketio.on('resolve_conflict')
def on_resolve_conflict(data):
    room = data.get('sessionId', 'default')
    user_id = data.get('userId') or request.sid
    action = data.get('action')
    conflict = data.get('conflict') or {}
    operation = conflict.get('operation')
    conflict_id = conflict.get('conflictId')

    actor_id = (conflict.get('actor') or {}).get('userId')
    is_actor = bool(actor_id) and user_id == actor_id

    if action == 'keep_mine' and is_actor:
        # Original actor forces their action through.
        if operation == 'node_updated' and conflict.get('incomingNode'):
            on_node_updated({
                'sessionId': room,
                'userId': user_id,
                'node': conflict['incomingNode'],
                'force': True,
                'changeSummary': conflict.get('changeSummary') or [],
            })
        elif operation == 'node_removed' and conflict.get('nodeId'):
            on_node_removed({
                'sessionId': room,
                'userId': user_id,
                'nodeId': conflict['nodeId'],
                'force': True,
            })
        elif operation == 'edge_added' and conflict.get('incomingEdge'):
            on_edge_added({
                'sessionId': room,
                'userId': user_id,
                'edge': conflict['incomingEdge'],
                'force': True,
            })
        elif operation == 'edge_removed' and conflict.get('edgeId'):
            on_edge_removed({
                'sessionId': room,
                'userId': user_id,
                'edgeId': conflict['edgeId'],
                'force': True,
            })
        _record_activity(room, 'conflict_resolved', user_id, 'Resolved conflict by keeping local change', conflict.get('entityId'))
    elif action == 'keep_mine' and not is_actor:
        # A bystander wants to keep the current server state (the actor's
        # action stays rejected). The actor's local state may be ahead of
        # the server (e.g. they removed an edge locally before the server
        # rejected it), so emit the canonical server entity back to the
        # room to restore the actor's view.
        if operation == 'edge_removed' and conflict.get('currentEdge'):
            edge = conflict['currentEdge']
            emit('edge_added', {
                'edge': edge,
                'revision': _current_revision(room, 'edges', edge.get('id')),
                'user': _user_payload(room, user_id),
            }, to=room, include_self=False)
        elif operation == 'node_removed' and conflict.get('currentNode'):
            node = conflict['currentNode']
            emit('node_added', {
                'node': node,
                'revision': _current_revision(room, 'nodes', node.get('id')),
                'user': _user_payload(room, user_id),
            }, to=room, include_self=False)
        elif operation == 'edge_added' and conflict.get('incomingEdge'):
            edge = conflict['incomingEdge']
            emit('edge_removed', {
                'edgeId': edge.get('id'),
                'user': _user_payload(room, user_id),
            }, to=room, include_self=False)
        elif operation == 'node_updated' and conflict.get('currentNode'):
            node = conflict['currentNode']
            emit('node_updated', {
                'node': node,
                'revision': _current_revision(room, 'nodes', node.get('id')),
                'user': _user_payload(room, user_id),
            }, to=room, include_self=False)
        _record_activity(room, 'conflict_resolved', user_id, 'Resolved conflict by keeping current state', conflict.get('entityId'))
    elif action == 'accept_other' and not is_actor:
        # A bystander accepts the actor's proposed action — force it through.
        # (For the original actor, "accept_other" means giving up on their
        # own change; the frontend reverts their local view to the server
        # snapshot, and the server doesn't need to do anything.)
        if operation == 'node_updated' and conflict.get('incomingNode'):
            on_node_updated({
                'sessionId': room,
                'userId': actor_id or user_id,
                'node': conflict['incomingNode'],
                'force': True,
                'changeSummary': conflict.get('changeSummary') or [],
            })
        elif operation == 'node_removed' and conflict.get('nodeId'):
            on_node_removed({
                'sessionId': room,
                'userId': actor_id or user_id,
                'nodeId': conflict['nodeId'],
                'force': True,
            })
        elif operation == 'edge_added' and conflict.get('incomingEdge'):
            on_edge_added({
                'sessionId': room,
                'userId': actor_id or user_id,
                'edge': conflict['incomingEdge'],
                'force': True,
            })
        elif operation == 'edge_removed' and conflict.get('edgeId'):
            on_edge_removed({
                'sessionId': room,
                'userId': actor_id or user_id,
                'edgeId': conflict['edgeId'],
                'force': True,
            })
        _record_activity(room, 'conflict_resolved', user_id, 'Resolved conflict by accepting remote change', conflict.get('entityId'))
    elif action == 'accept_other':
        _record_activity(room, 'conflict_resolved', user_id, 'Resolved conflict by accepting remote change', conflict.get('entityId'))
    elif action == 'manual':
        _record_activity(room, 'conflict_manual', user_id, 'Marked conflict for manual resolution', conflict.get('entityId'))
    else:
        _record_activity(room, 'conflict_cancelled', user_id, 'Cancelled local conflicting change', conflict.get('entityId'))

    emit('conflict_resolved', {
        'conflictId': conflict_id,
        'action': action,
        'resolvedBy': _user_payload(room, user_id),
    }, to=room)
