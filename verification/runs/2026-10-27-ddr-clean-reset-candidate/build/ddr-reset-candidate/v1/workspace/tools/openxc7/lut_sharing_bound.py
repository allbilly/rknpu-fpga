"""Optimistic plain-LUT sharing bounds; never a placement or execution input.

The source-bound backend forbids pairing six-connected-input logic LUTs and
requires at most five distinct input nets for a pair. Two five-distinct-input
LUTs can pair only within one identical-input group. A five-input LUT can
pair with a smaller LUT only when the smaller input set is a subset.

Compute the exact maximum five-to-smaller bipartite matching, treating group
counts as capacities. Bound identical-five internal pairs independently of
that matching (optimistically double-allowing their cells), and allow every
remaining smaller cell to pair regardless of its actual inputs. This gives
an UPPER bound on total pairs, hence a LOWER bound on physical LUT positions.
All cluster, OUTMUX, FF, routing, electrical and timing constraints are ignored.
"""
from collections import deque
from itertools import combinations

class Flow:
    def __init__(self, nodes):
        self.edges = [[] for _ in range(nodes)]

    def add(self, source, target, capacity):
        assert type(capacity) is int and capacity >= 0
        a = [target, capacity, len(self.edges[target]), capacity]
        b = [source, 0, len(self.edges[source]), 0]
        self.edges[source].append(a)
        self.edges[target].append(b)

    def maximum(self, source, sink):
        total = 0
        while True:
            levels = [-1] * len(self.edges)
            levels[source] = 0
            queue = deque([source])
            while queue:
                node = queue.popleft()
                for target, capacity, _, _ in self.edges[node]:
                    if capacity and levels[target] < 0:
                        levels[target] = levels[node] + 1
                        queue.append(target)
            if levels[sink] < 0:
                reachable = {node for node, level in enumerate(levels) if level >= 0}
                cut = sum(original for node in reachable for target, _, _, original in self.edges[node]
                    if target not in reachable)
                assert cut == total, 'Flow does not match the residual minimum-cut certificate'
                return total, cut
            cursor = [0] * len(self.edges)

            def push(node, available, depth=0):
                assert depth < 900, 'Unsupported excessive residual path depth'
                if node == sink:
                    return available
                while cursor[node] < len(self.edges[node]):
                    edge = self.edges[node][cursor[node]]
                    target, capacity, reverse, _ = edge
                    if capacity and levels[target] == levels[node] + 1:
                        sent = push(target, min(available, capacity), depth + 1)
                        if sent:
                            edge[1] -= sent
                            self.edges[target][reverse][1] += sent
                            return sent
                    cursor[node] += 1
                return 0
            while True:
                sent = push(source, 1 << 60)
                if not sent:
                    break
                total += sent

def sharing_bound(groups, whole, positions):
    assert type(whole) is int and whole >= 0
    assert type(positions) is int and positions > 0
    assert all(isinstance(inputs, frozenset) and 1 <= len(inputs) <= 5
        and all(type(bit) is int and bit >= 2 for bit in inputs)
        and type(count) is int and count > 0 for inputs, count in groups.items())
    five = {inputs: count for inputs, count in groups.items() if len(inputs) == 5}
    smaller = {inputs: count for inputs, count in groups.items() if len(inputs) < 5}
    five_keys, small_keys = list(five), list(smaller)
    five_count, small_count = sum(five.values()), sum(smaller.values())
    source, sink = len(five_keys) + len(small_keys), len(five_keys) + len(small_keys) + 1
    flow = Flow(sink + 1)
    small_nodes = {inputs: len(five_keys) + i for i, inputs in enumerate(small_keys)}
    for inputs, node in small_nodes.items():
        flow.add(node, sink, smaller[inputs])
    arcs, lonely = 0, 0
    for node, inputs in enumerate(five_keys):
        flow.add(source, node, five[inputs])
        neighbors = []
        for size in range(1, 5):
            for subset in combinations(inputs, size):
                partner = frozenset(subset)
                if partner in small_nodes:
                    neighbors.append(partner)
                    flow.add(node, small_nodes[partner], min(five[inputs], smaller[partner]))
                    arcs += 1
        if five[inputs] == 1 and not neighbors:
            lonely += 1
    matching, cut = flow.maximum(source, sink)
    assert 0 <= matching <= min(five_count, small_count)
    internal = sum(count // 2 for count in five.values())
    eligible = five_count + small_count
    pair_upper = min((small_count + matching) // 2 + internal, eligible // 2)
    matching_lower = whole + eligible - pair_upper
    isolated_lower = whole + lonely + (eligible - lonely + 1) // 2
    lower = max(matching_lower, isolated_lower)
    return dict(lut_cells=whole + eligible, whole_input_LUTs=whole,
        five_input_LUTs=five_count, smaller_input_LUTs=small_count,
        five_input_groups=len(five), smaller_input_groups=len(smaller), subset_arcs=arcs,
        maximum_five_to_smaller_matching=matching, minimum_cut_capacity=cut,
        optimistic_independent_identical_five_pairs=internal,
        unpaired_isolated_five_input_LUTs=lonely, total_pair_upper_bound=pair_upper,
        matching_position_lower_bound=matching_lower, isolated_position_lower_bound=isolated_lower,
        necessary_position_lower_bound=lower, physical_LUT_positions=positions,
        lower_bound_exceeds_device=lower > positions,
        physical_fit_verified=False, native_placement_executed=False)
